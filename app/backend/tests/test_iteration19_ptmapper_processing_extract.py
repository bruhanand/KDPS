"""Iteration 19 — live-API regression for the ptmapper.processing module extraction.

Refactor summary: process_file() + helpers moved from ptmapper.views into a new
ptmapper.processing module; ptmapper.learning now does a top-level import from
processing (was a lazy in-function import). This test hits the running preview
backend to prove the extraction did not break the mapping pipeline that reaches
process_file() through the HTTP layer.

Gated on KDPS_TEST_ALLOW_REMOTE=1 per project convention (live-API modules skip
in the default DB suite; enabled in this iteration's run).
"""
from __future__ import annotations

import io
import os

import pytest
import requests

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "https://kdps-delivery-check.preview.emergentagent.com").rstrip("/")

pytestmark = pytest.mark.skipif(
    os.environ.get("KDPS_TEST_ALLOW_REMOTE") != "1",
    reason="Live-API test — set KDPS_TEST_ALLOW_REMOTE=1",
)


def _login(username: str, password: str) -> str:
    r = requests.post(
        f"{BASE_URL}/api/auth/login",
        json={"username": username, "password": password},
        timeout=15,
    )
    assert r.status_code == 200, f"login {username} failed: {r.status_code} {r.text[:200]}"
    tok = r.json().get("access")
    assert tok, f"login {username} missing 'access' JWT: {r.json()}"
    return tok


@pytest.fixture(scope="module")
def owner_token() -> str:
    return _login("owner", "Owner@123")


@pytest.fixture(scope="module")
def wh_token() -> str:
    return _login("wh.patna", "Wh@123")


def _headers(tok: str) -> dict:
    return {"Authorization": f"Bearer {tok}"}


# ---------------------------------------------------------------- 1) Import health
def test_files_list_returns_200_no_import_error(owner_token: str) -> None:
    """The single strongest signal the ptmapper.views + learning + processing import
    graph is clean — a circular import would have crashed DRF's URL resolver at first
    hit, yielding a 500 with ImportError in the response body."""
    r = requests.get(f"{BASE_URL}/api/ptmapper/files", headers=_headers(owner_token), timeout=15)
    assert r.status_code == 200, r.text[:500]
    body = r.json()
    # Accept either a plain list or a paginated envelope — both are known shapes.
    if isinstance(body, dict):
        assert "results" in body, body
        assert isinstance(body["results"], list)
    else:
        assert isinstance(body, list), type(body)


# ---------------------------------------------------------------- 2) Upload → process_file()
_SAMPLE_CSV = (
    b"BARCODE,QTY,MRP,P RATE,COLOR,SIZE\n"
    b"B0001,3,999,600,Blue,M\n"
    b"B0002,2,1499,900,Red,L\n"
    b"B0003,1,799,500,,S\n"
)


@pytest.fixture(scope="module")
def uploaded_file_id(wh_token: str) -> int:
    """Upload a brand CSV via the warehouse role → exercises process_file() end-to-end."""
    files = {"file": ("iter19_sample.csv", io.BytesIO(_SAMPLE_CSV), "text/csv")}
    # Fetch a real Master-Sheet brand — upload validation rejects unknown brands.
    br = requests.get(
        f"{BASE_URL}/api/ptmapper/controlled?dimension=brand",
        headers=_headers(wh_token),
        timeout=15,
    )
    assert br.status_code == 200, br.text[:300]
    brands = br.json().get("values") or []
    assert brands, "no Master-Sheet brands available for test"
    data = {"brand": brands[0], "invoice_date": "2026-01-15"}
    r = requests.post(
        f"{BASE_URL}/api/ptmapper/files",
        headers=_headers(wh_token),
        files=files,
        data=data,
        timeout=30,
    )
    assert r.status_code in (200, 201), f"upload failed: {r.status_code} {r.text[:500]}"
    body = r.json()
    assert "id" in body, body
    assert body.get("row_count", 0) > 0, f"row_count not > 0 after process_file: {body}"
    assert body.get("status") in ("READY", "NEEDS_REVIEW", "ready", "needs_review"), f"unexpected status: {body.get('status')} — {body}"
    return int(body["id"])


def test_upload_produces_mapped_rows(uploaded_file_id: int, wh_token: str) -> None:
    """Sanity: the uploaded PtFile has rows and a valid post-process_file status."""
    r = requests.get(
        f"{BASE_URL}/api/ptmapper/files/{uploaded_file_id}",
        headers=_headers(wh_token),
        timeout=15,
    )
    assert r.status_code == 200, r.text[:400]
    body = r.json()
    assert body["row_count"] >= 3, body
    assert body["status"] in ("READY", "NEEDS_REVIEW", "ready", "needs_review"), body["status"]


# ---------------------------------------------------------------- 3) Rerun → _snapshot_manual + _reapply_manual
def test_rerun_preserves_manual_edit(uploaded_file_id: int, wh_token: str) -> None:
    """Hand-edit a cell on row 1, then hit /rerun (default preserve_manual=True) and
    confirm the manual value survives — this is exactly _snapshot_manual +
    _reapply_manual + _recompute_derived in the extracted module."""
    # Read the current rows to find row 1's id and pick a controlled column
    r = requests.get(
        f"{BASE_URL}/api/ptmapper/files/{uploaded_file_id}",
        headers=_headers(wh_token),
        timeout=15,
    )
    assert r.status_code == 200, r.text[:400]
    rows = r.json().get("rows") or []
    assert rows, "no rows returned on file detail — cannot test manual preservation"
    first_row = rows[0]
    row_id = first_row["id"]
    # Hand-edit COLOR on this row
    # Fetch a real Master-Sheet color so the rows-update validator accepts it
    cr = requests.get(
        f"{BASE_URL}/api/ptmapper/controlled?dimension=color",
        headers=_headers(wh_token),
        timeout=15,
    )
    assert cr.status_code == 200, cr.text[:300]
    colors = cr.json().get("values") or []
    # Pick a color that ISN'T the current row's mapped color, so we prove it was preserved
    current_color = str(first_row.get("data", {}).get("COLOR") or "").upper()
    manual_color = next((c for c in colors if c.upper() != current_color), colors[0])
    patch_body = {"rows": [{"id": row_id, "data": {"COLOR": manual_color}}]}
    rp = requests.patch(
        f"{BASE_URL}/api/ptmapper/files/{uploaded_file_id}/rows",
        headers={**_headers(wh_token), "Content-Type": "application/json"},
        json=patch_body,
        timeout=15,
    )
    # rows update may be PATCH or POST; accept either 200/202 (or 405 → skip if endpoint differs)
    if rp.status_code == 405:
        rp = requests.post(
            f"{BASE_URL}/api/ptmapper/files/{uploaded_file_id}/rows",
            headers={**_headers(wh_token), "Content-Type": "application/json"},
            json=patch_body,
            timeout=15,
        )
    assert rp.status_code in (200, 201, 202), f"rows update failed: {rp.status_code} {rp.text[:400]}"

    # Now trigger rerun
    rr = requests.post(
        f"{BASE_URL}/api/ptmapper/files/{uploaded_file_id}/rerun",
        headers=_headers(wh_token),
        timeout=30,
    )
    assert rr.status_code in (200, 201), f"rerun failed: {rr.status_code} {rr.text[:400]}"

    # Fetch rows again and confirm the manual cell survived
    r2 = requests.get(
        f"{BASE_URL}/api/ptmapper/files/{uploaded_file_id}",
        headers=_headers(wh_token),
        timeout=15,
    )
    assert r2.status_code == 200, r2.text[:400]
    rows2 = r2.json().get("rows") or []
    match = next((row for row in rows2 if row["id"] == row_id), None)
    # Match by id may fail after rerun if row ids are regenerated — fall back to line_no
    if match is None:
        line_no = first_row.get("line_no")
        match = next((row for row in rows2 if row.get("line_no") == line_no), None)
    assert match is not None, "row disappeared after rerun"
    assert match["data"].get("COLOR") == manual_color, (
        f"manual cell NOT preserved after rerun — _reapply_manual regression. "
        f"expected COLOR={manual_color!r}, got row={match}"
    )
    # Provenance must be 'manual' after re-apply
    prov = (match.get("provenance") or {}).get("COLOR")
    assert prov == "manual", f"provenance should be 'manual' after _reapply_manual, got {prov!r}"


# ---------------------------------------------------------------- 4) Review resolve → learning.approve → repropagate → process_file
def test_review_resolve_no_import_error(owner_token: str) -> None:
    """Hit GET /review — the endpoint importing learning.py transitively imports
    ptmapper.processing at module-load time. A circular / broken import would 500 here.
    We don't require an open item to exist; a 200 with any shape confirms the graph."""
    r = requests.get(f"{BASE_URL}/api/ptmapper/review", headers=_headers(owner_token), timeout=15)
    assert r.status_code == 200, f"review list failed: {r.status_code} {r.text[:400]}"


# ---------------------------------------------------------------- 5) from-GRN endpoint reachable
def test_from_grn_endpoint_reachable(owner_token: str) -> None:
    """POST /files/from-grn/<id> for a bogus id — a 404/400/403 is acceptable (the
    resource is absent or the role/scope blocks it). A 500 with ImportError would be
    the regression. This proves PtFileFromGrnView (which calls process_file inside)
    still loads its module."""
    r = requests.post(
        f"{BASE_URL}/api/ptmapper/files/from-grn/999999",
        headers=_headers(owner_token),
        timeout=15,
    )
    assert r.status_code != 500, f"from-grn endpoint 500'd — suspected ImportError: {r.text[:600]}"
    assert r.status_code in (400, 403, 404, 405, 409), f"unexpected status {r.status_code}: {r.text[:400]}"


# ---------------------------------------------------------------- 6) Cleanup
def test_cleanup_uploaded_file(uploaded_file_id: int, wh_token: str, owner_token: str) -> None:
    """Best-effort delete of the test file; skip silently if DELETE isn't allowed."""
    for tok in (wh_token, owner_token):
        r = requests.delete(
            f"{BASE_URL}/api/ptmapper/files/{uploaded_file_id}",
            headers=_headers(tok),
            timeout=15,
        )
        if r.status_code in (200, 202, 204):
            return
    pytest.skip("DELETE not permitted for this role — file left behind (id-tracked in report)")
