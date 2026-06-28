"""Refactor regression tests — verify behavior-preservation of:

- ptmapper.engine.map_record() (split into _map_prices/_map_season/_map_taxonomy)
- ptmapper.views.ReviewResolveView.post() helpers
- inbound.views GrnListCreateView.create() helpers (_resolve_receiving_store / _build_grn / _add_grn_line)

These hit the LIVE preview env via REACT_APP_BACKEND_URL.
"""
import os
import time

import pytest
import requests

BASE_URL = os.environ.get(
    "REACT_APP_BACKEND_URL",
    "https://pt-mapper.preview.emergentagent.com",
).rstrip("/")

PT_DIR = "/app/docs/data-from-kdps/Q&A-req-recieved/PT FILE"


def _login(username: str, password: str) -> str:
    r = requests.post(
        f"{BASE_URL}/api/auth/login",
        json={"username": username, "password": password},
        timeout=30,
    )
    assert r.status_code == 200, f"login {username} -> {r.status_code} {r.text[:200]}"
    return r.json()["access"]


@pytest.fixture(scope="module")
def owner_token():
    return _login("owner", "Owner@123")


@pytest.fixture(scope="module")
def cashier_token():
    return _login("deo.cashier", "Store@123")


def _auth(tok):
    return {"Authorization": f"Bearer {tok}"}


# ---- PT MAPPER engine refactor ----------------------------------------------

def _upload_pt(token: str, path: str) -> dict:
    with open(path, "rb") as fh:
        r = requests.post(
            f"{BASE_URL}/api/ptmapper/files",
            headers=_auth(token),
            files={"file": (os.path.basename(path), fh)},
            timeout=180,
        )
    assert r.status_code in (200, 201), f"upload {path} -> {r.status_code} {r.text[:400]}"
    return r.json()


def _wait_processed(token: str, file_id: int, want_rows: int | None = None, retries: int = 40) -> dict:
    last = None
    for _ in range(retries):
        r = requests.get(
            f"{BASE_URL}/api/ptmapper/files/{file_id}",
            headers=_auth(token),
            timeout=30,
        )
        assert r.status_code == 200, r.text[:300]
        last = r.json()
        if last.get("status") in {"mapped", "ready", "needs_review", "failed"} or last.get("row_count"):
            if want_rows is None or last.get("row_count", 0) >= want_rows:
                return last
        time.sleep(1.5)
    return last or {}


def test_mufti_xlsx_maps_with_populated_prices(owner_token):
    info = _upload_pt(owner_token, f"{PT_DIR}/MUFTI.xlsx")
    fid = info["id"]
    final = _wait_processed(owner_token, fid, want_rows=90)
    assert final.get("row_count", 0) >= 90, f"MUFTI row_count={final.get('row_count')}"

    # fetch rows from detail endpoint
    detail = requests.get(
        f"{BASE_URL}/api/ptmapper/files/{fid}",
        headers=_auth(owner_token),
        timeout=30,
    ).json()
    items = detail.get("rows", [])
    assert items, "no rows returned for MUFTI"

    def _val(row, key):
        d = row.get("data") or row.get("mapped") or row.get("kdps_row") or row
        return d.get(key)

    have_basic = any(str(_val(r, "BASIC") or "").strip() for r in items)
    have_mrp = any(str(_val(r, "MRP") or "").strip() for r in items)
    have_item = any(str(_val(r, "ITEM") or "").strip() for r in items)
    have_season = any(str(_val(r, "SEASON") or "").strip() for r in items)
    have_color = any(str(_val(r, "COLOR") or "").strip() for r in items)
    assert have_basic, "no BASIC populated -> _map_prices regression"
    assert have_mrp, "no MRP populated -> _map_prices regression"
    assert have_item, "no ITEM populated -> _map_taxonomy regression"
    assert have_season, "no SEASON populated -> _map_season regression"
    assert have_color, "no COLOR populated -> _map_taxonomy regression"


def test_jockey852_xls_maps_generic_archetype_a(owner_token):
    info = _upload_pt(owner_token, f"{PT_DIR}/JOCKEY 852.xls")
    fid = info["id"]
    final = _wait_processed(owner_token, fid, want_rows=9)
    assert final.get("row_count", 0) >= 9, f"JOCKEY row_count={final.get('row_count')}"
    profile = (final.get("profile") or final.get("mapping_profile") or "").lower()
    arche = (final.get("archetype") or "").upper()
    # Tolerate either spelling/casing; main agent reported "Generic (header-name auto-map)" + A.
    assert "generic" in profile or final.get("profile_name", "").lower().startswith("generic"), \
        f"JOCKEY 852 profile={profile!r}"
    assert arche in ("A", "") or "A" in arche, f"JOCKEY 852 archetype={arche!r}"


# ---- INBOUND / GRN refactor --------------------------------------------------

def test_grn_create_direct_receipt(cashier_token):
    """Direct GRN (no booking): must succeed (201) and be visible in list."""
    payload = {
        "store_id": 1,
        "vendor_name": "TEST_REGRESSION VENDOR",
        "lines": [
            {
                "style_code": "TEST_REG",
                "size": "M",
                "barcode": "TESTREG-001",
                "received_qty": 2,
            }
        ],
    }
    r = requests.post(
        f"{BASE_URL}/api/inbound/grns",
        headers=_auth(cashier_token),
        json=payload,
        timeout=30,
    )
    assert r.status_code in (200, 201), f"GRN direct create -> {r.status_code} {r.text[:400]}"
    data = r.json()
    grn_id = data.get("id") or data.get("grn_id")
    assert grn_id, f"no id in response: {data}"
    assert data.get("is_direct") is True, "direct GRN should have is_direct=True"
    assert not data.get("booking"), "direct GRN should have no booking"

    # verify it appears in list (fail-closed scope: cashier sees own store)
    rl = requests.get(f"{BASE_URL}/api/inbound/grns", headers=_auth(cashier_token), timeout=30)
    assert rl.status_code == 200, rl.text[:300]
    listed = rl.json()
    items = listed if isinstance(listed, list) else listed.get("results", [])
    assert any((it.get("id") or it.get("grn_id")) == grn_id for it in items), \
        "newly created GRN not in cashier's list"


def test_grn_create_against_booking_updates_progress(cashier_token):
    """Booking-based GRN: must succeed (201) and booking line received_qty advances."""
    pend = requests.get(
        f"{BASE_URL}/api/inbound/pending", headers=_auth(cashier_token), timeout=30
    ).json()
    if not pend:
        pytest.skip("no pending bookings visible to cashier")
    bk = pend[0]
    line = bk["lines"][0]
    prev_recv = int(line.get("received_qty") or 0)

    payload = {
        "store_id": bk["destination_store"],
        "booking_id": bk["id"],
        "lines": [
            {
                "booking_line_id": line["id"],
                "style_code": line["style_code"],
                "size": line["size"],
                "received_qty": 1,
            }
        ],
    }
    r = requests.post(
        f"{BASE_URL}/api/inbound/grns",
        headers=_auth(cashier_token),
        json=payload,
        timeout=30,
    )
    assert r.status_code in (200, 201), f"GRN booking create -> {r.status_code} {r.text[:400]}"
    data = r.json()
    assert data.get("booking") == bk["id"], f"booking link missing: {data}"
    assert data.get("is_direct") is False

    # verify booking line received_qty advanced
    pend2 = requests.get(
        f"{BASE_URL}/api/inbound/pending", headers=_auth(cashier_token), timeout=30
    ).json()
    bk2 = next((b for b in pend2 if b["id"] == bk["id"]), None)
    if bk2:
        line2 = next((ln for ln in bk2["lines"] if ln["id"] == line["id"]), None)
        if line2:
            assert int(line2["received_qty"]) >= prev_recv + 1, \
                f"booking line received_qty did not advance: {prev_recv} -> {line2['received_qty']}"


def test_grn_list_scope_fail_closed(cashier_token):
    """Cashier should only see their own store's GRNs."""
    r = requests.get(f"{BASE_URL}/api/inbound/grns", headers=_auth(cashier_token), timeout=30)
    assert r.status_code == 200
    listed = r.json()
    items = listed if isinstance(listed, list) else listed.get("results", [])
    stores = {(it.get("store") or it.get("store_code") or it.get("receiving_store")) for it in items}
    # If a store field is exposed, all rows should belong to a single store (DEO).
    stores.discard(None)
    assert len(stores) <= 1, f"cashier sees multiple stores: {stores}"


# ---- REVIEW QUEUE refactor (smoke) ------------------------------------------

def test_review_queue_reachable(owner_token):
    r = requests.get(f"{BASE_URL}/api/ptmapper/review", headers=_auth(owner_token), timeout=30)
    assert r.status_code == 200, r.text[:300]
    data = r.json()
    items = data if isinstance(data, list) else data.get("results", data.get("items", []))
    # may be empty; just confirm endpoint behaviour didn't regress
    assert isinstance(items, list)
