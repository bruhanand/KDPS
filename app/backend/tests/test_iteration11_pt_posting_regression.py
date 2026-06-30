"""Iteration 11 backend regression.

Inbound line semantics, PT inward posting/reversal, cookie auth fallback.
"""

from __future__ import annotations

import os
import time
from pathlib import Path
from typing import Any

import pytest
import requests

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "").rstrip("/")
assert BASE_URL, "REACT_APP_BACKEND_URL not set"
API = f"{BASE_URL}/api"
# Repo-relative so the fixture resolves in Claude Code, Emergent (/app) and CI alike.
PT_SAMPLE = str(
    Path(__file__).resolve().parents[3] / "docs/data-from-kdps/Q&A-req-recieved/PT FILE/MUFTI.xlsx"
)


def _login(username: str, password: str) -> dict[str, Any]:
    r = requests.post(
        f"{API}/auth/login",
        json={"username": username, "password": password},
        timeout=30,
    )
    assert r.status_code == 200, f"login failed {username}: {r.status_code} {r.text[:250]}"
    body = r.json()
    assert body.get("access")
    return body


def _headers(access: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {access}", "Content-Type": "application/json"}


def _list_of(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict):
        results = payload.get("results")
        if isinstance(results, list):
            return results
    return []


def _pick_id(endpoint: str, headers: dict[str, str], key_name: str = "id") -> int:
    r = requests.get(f"{API}{endpoint}", headers=headers, timeout=30)
    assert r.status_code == 200, f"GET {endpoint} -> {r.status_code} {r.text[:250]}"
    rows = _list_of(r.json())
    if not rows:
        pytest.skip(f"no rows found at {endpoint}")
    value = rows[0].get(key_name)
    assert isinstance(value, int), f"invalid id from {endpoint}: {rows[0]}"
    return value


def _upload_pt(access: str, file_path: str) -> dict[str, Any]:
    with open(file_path, "rb") as fh:
        r = requests.post(
            f"{API}/ptmapper/files",
            headers={"Authorization": f"Bearer {access}"},
            files={"file": (Path(file_path).name, fh)},
            timeout=180,
        )
    assert r.status_code in (200, 201), f"upload failed: {r.status_code} {r.text[:300]}"
    return r.json()


def _wait_pt(access: str, pt_id: int, *, retries: int = 50) -> dict[str, Any]:
    last: dict[str, Any] = {}
    for _ in range(retries):
        r = requests.get(
            f"{API}/ptmapper/files/{pt_id}",
            headers={"Authorization": f"Bearer {access}"},
            timeout=30,
        )
        assert r.status_code == 200, r.text[:200]
        last = r.json()
        if (last.get("row_count") or 0) > 0:
            return last
        if last.get("status") == "failed":
            break
        time.sleep(1.5)
    return last


# module and feature: accounts.authentication CookieOrHeaderJWTAuthentication
def test_cookie_only_auth_me_supported() -> None:
    s = requests.Session()
    login = s.post(
        f"{API}/auth/login",
        json={"username": "owner", "password": "Owner@123"},
        timeout=30,
    )
    assert login.status_code == 200, login.text[:250]
    assert "access_token=" in (login.headers.get("set-cookie") or "")

    me = s.get(f"{API}/auth/me", timeout=30)
    assert me.status_code == 200, me.text[:250]
    body = me.json()
    assert body.get("username") == "owner"


# module and feature: inbound.views _add_grn_line helpers
def test_grn_direct_line_keeps_received_and_damaged_qty() -> None:
    auth = _login("owner", "Owner@123")
    h = _headers(auth["access"])
    store_id = _pick_id("/masters/stores", h)

    payload = {
        "store_id": store_id,
        "vendor_name": "TEST_ITER11_DIRECT",
        "invoice_number": f"ITER11-DIR-{int(time.time())}",
        "lines": [
            {
                "style_code": "ITER11-DIRECT-STYLE",
                "size": "L",
                "color": "Navy",
                "barcode": f"ITER11-D-{int(time.time())}",
                "received_qty": 3,
                "damaged_qty": 2,
                "remark": "direct-line-check",
            }
        ],
    }
    create = requests.post(f"{API}/inbound/grns", headers=h, json=payload, timeout=30)
    assert create.status_code == 201, (
        f"direct GRN create failed: {create.status_code} {create.text[:250]}"
    )
    grn = create.json()
    assert grn.get("is_direct") is True
    assert isinstance(grn.get("lines"), list) and grn["lines"]
    line = grn["lines"][0]
    assert int(line.get("received_qty") or 0) == 3
    assert int(line.get("damaged_qty") or 0) == 2


# module and feature: stockledger.posting post_pt_inward/reverse_pt_inward + inbound variance
def test_pt_posting_reconcile_vendor_bill_reverse_append_only_and_booking_variance() -> None:
    owner = _login("owner", "Owner@123")
    access = owner["access"]
    h = _headers(access)

    store_id = _pick_id("/masters/stores", h)
    vendor_id = _pick_id("/vendors", h)
    brand_id = _pick_id("/masters/brands", h)
    season_id = _pick_id("/masters/seasons", h)

    assert Path(PT_SAMPLE).exists(), f"missing PT sample file: {PT_SAMPLE}"
    uploaded = _upload_pt(access, PT_SAMPLE)
    pt_id = int(uploaded["id"])
    detail = _wait_pt(access, pt_id)
    rows = detail.get("rows") or []
    if not rows:
        pytest.skip("PT sample did not produce rows in this environment")

    mapped = rows[0].get("data") or {}
    style_code = str(mapped.get("DESIGN") or "").strip()
    size = str(mapped.get("SIZE") or "").strip()
    if not style_code:
        pytest.skip("PT first row has empty DESIGN; cannot verify booking reconciliation")

    booking_payload = {
        "vendor": vendor_id,
        "brand": brand_id,
        "season": season_id,
        "destination_store": store_id,
        "vendor_ref": f"ITER11-{int(time.time())}",
        "lines": [{"style_code": style_code, "size": size, "booked_qty": 500, "mrp": 999}],
    }
    bk = requests.post(f"{API}/bookings", headers=h, json=booking_payload, timeout=30)
    assert bk.status_code == 201, f"booking create failed: {bk.status_code} {bk.text[:250]}"
    booking = bk.json()
    booking_id = int(booking["id"])
    booking_line = booking["lines"][0]
    prev_inwarded = int(booking_line.get("inwarded_qty") or 0)

    variance_payload = {
        "store_id": store_id,
        "booking_id": booking_id,
        "invoice_number": f"ITER11-VAR-{int(time.time())}",
        "lines": [{"style_code": "ITER11-VARIANCE", "size": "M", "received_qty": 1}],
    }
    grn = requests.post(f"{API}/inbound/grns", headers=h, json=variance_payload, timeout=30)
    assert grn.status_code == 201, (
        f"booking variance GRN failed: {grn.status_code} {grn.text[:250]}"
    )
    grn_line = grn.json()["lines"][0]
    assert grn_line.get("is_variance") is True

    send = requests.post(f"{API}/ptmapper/files/{pt_id}/send", headers=h, json={}, timeout=30)
    assert send.status_code == 200, f"PT send failed: {send.status_code} {send.text[:250]}"

    post = requests.post(
        f"{API}/ptmapper/files/{pt_id}/post",
        headers=h,
        json={"booking_id": booking_id},
        timeout=60,
    )
    assert post.status_code == 200, f"PT post failed: {post.status_code} {post.text[:250]}"
    posted = post.json()
    post_result = posted.get("post_result") or {}
    assert int(post_result.get("entries") or 0) > 0
    assert int(post_result.get("reconciled_lines") or 0) >= 1
    # NOTE: a vendor bill is intentionally NOT asserted here. Liability timing is
    # commercial-model dependent (Outright/Correction → at PT; SOR → on Sale;
    # Consignment → never from PT). Per-commercial-model golden tests are added in
    # the supervised money-slice rebuild (Phase E); asserting "a bill is always
    # raised" here would re-cement the model-blind liability defect.
    doc_number = str(post_result.get("doc_number"))

    bk_after = requests.get(f"{API}/bookings/{booking_id}", headers=h, timeout=30)
    assert bk_after.status_code == 200
    updated_line = bk_after.json()["lines"][0]
    assert int(updated_line.get("inwarded_qty") or 0) > prev_inwarded

    ledger = requests.get(
        f"{API}/stockledger/entries?doc_number={doc_number}",
        headers=h,
        timeout=30,
    )
    assert ledger.status_code == 200
    entries = _list_of(ledger.json())
    assert entries, "no stock ledger entries for PT inward doc"
    assert all(e.get("kind") == "pt_inward" for e in entries)
    assert all(int(e.get("qty") or 0) > 0 for e in entries)

    # Vendor-bill existence is deliberately not asserted (see note above): whether a
    # PT raises liability is decided by the booking's commercial model, validated by
    # the Phase E per-model golden suite, not this stock-posting regression.

    rev = requests.post(f"{API}/ptmapper/files/{pt_id}/reverse", headers=h, json={}, timeout=60)
    assert rev.status_code == 200, f"PT reverse failed: {rev.status_code} {rev.text[:250]}"
    reverse_result = rev.json().get("reverse_result") or {}
    assert int(reverse_result.get("entries") or 0) > 0
    reverse_doc = str(reverse_result.get("doc_number") or "")
    assert reverse_doc

    rev_ledger = requests.get(
        f"{API}/stockledger/entries?doc_number={reverse_doc}",
        headers=h,
        timeout=30,
    )
    assert rev_ledger.status_code == 200
    rev_entries = _list_of(rev_ledger.json())
    assert rev_entries, "no reversal ledger entries found"
    assert all(e.get("kind") == "pt_reversal" for e in rev_entries)
    assert all(int(e.get("qty") or 0) < 0 for e in rev_entries)

    original_ledger = requests.get(
        f"{API}/stockledger/entries?doc_number={doc_number}",
        headers=h,
        timeout=30,
    )
    assert original_ledger.status_code == 200
    original_entries = _list_of(original_ledger.json())
    assert original_entries, (
        "original inward entries disappeared after reversal (append-only breach)"
    )
