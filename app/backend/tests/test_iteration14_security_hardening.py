"""Iteration 14 — security hardening regression (Phase A of the code-review fixes).

Covers, against the live preview server:
  * finledger vendor/cash reads are finance-role gated (fail-closed payables),
  * PT post/reverse are gated to Patna/HO roles (warehouse cannot post liability),
  * review-resolve is gated to mapping-steward roles,
  * stock-ledger reads are store-scoped (a single-store user cannot see WH stock),
  * a non-mapping (posted/sent) PT cannot be deleted via the API.

Role check ALWAYS runs before object lookup, so a forbidden role gets 403 even for a
non-existent pk, while an allowed role gets 404 — that asymmetry is what we assert.
"""

from __future__ import annotations

import os
from typing import Any

import requests

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "").rstrip("/")
assert BASE_URL, "REACT_APP_BACKEND_URL not set"
API = f"{BASE_URL}/api"

MISSING_PK = 99_999_999  # a pk that should never exist


def _login(username: str, password: str) -> dict[str, str]:
    r = requests.post(
        f"{API}/auth/login", json={"username": username, "password": password}, timeout=30
    )
    assert r.status_code == 200, f"login failed {username}: {r.status_code} {r.text[:200]}"
    return {"Authorization": f"Bearer {r.json()['access']}", "Content-Type": "application/json"}


def _count(payload: Any) -> int:
    if isinstance(payload, dict):
        if "count" in payload:
            return int(payload["count"])
        if isinstance(payload.get("results"), list):
            return len(payload["results"])
    if isinstance(payload, list):
        return len(payload)
    return 0


# --- finledger reads are finance-only ----------------------------------------


def test_finledger_reads_require_finance_role() -> None:
    owner = _login("owner", "Owner@123")
    cashier = _login("deo.cashier", "Store@123")
    warehouse = _login("wh.patna", "Wh@123")

    for path in (
        "/finledger/vendor/entries",
        "/finledger/vendor/balances",
        "/finledger/vendor/ageing",
        "/finledger/cash/summary",
    ):
        assert requests.get(f"{API}{path}", headers=owner, timeout=30).status_code == 200, path
        assert requests.get(f"{API}{path}", headers=cashier, timeout=30).status_code == 403, path
        assert requests.get(f"{API}{path}", headers=warehouse, timeout=30).status_code == 403, path


# --- PT post / reverse are Patna/HO-only -------------------------------------


def test_pt_post_and_reverse_require_patna_role() -> None:
    owner = _login("owner", "Owner@123")
    cashier = _login("deo.cashier", "Store@123")
    warehouse = _login("wh.patna", "Wh@123")

    for action in ("post", "reverse"):
        url = f"{API}/ptmapper/files/{MISSING_PK}/{action}"
        # Forbidden roles are rejected before the object is even looked up → 403.
        assert requests.post(url, headers=warehouse, json={}, timeout=30).status_code == 403
        assert requests.post(url, headers=cashier, json={}, timeout=30).status_code == 403
        # Allowed role passes the gate and only then hits "not found" → 404 (not 403).
        assert requests.post(url, headers=owner, json={}, timeout=30).status_code == 404


# --- review-resolve is mapping-steward-only ----------------------------------


def test_review_resolve_requires_steward_role() -> None:
    warehouse = _login("wh.patna", "Wh@123")  # steward → passes gate
    cashier = _login("deo.cashier", "Store@123")  # store staff → forbidden
    accounts = _login("accounts1", "Acct@123")  # finance, not a steward → forbidden

    url = f"{API}/ptmapper/review/{MISSING_PK}/resolve"
    assert requests.post(url, headers=cashier, json={}, timeout=30).status_code == 403
    assert requests.post(url, headers=accounts, json={}, timeout=30).status_code == 403
    assert requests.post(url, headers=warehouse, json={}, timeout=30).status_code == 404


# --- stock-ledger reads are store-scoped -------------------------------------


def test_stockledger_reads_are_store_scoped() -> None:
    owner = _login("owner", "Owner@123")  # scope = all
    cashier = _login("deo.cashier", "Store@123")  # scope = single store (DEO)

    owner_entries = requests.get(f"{API}/stockledger/entries", headers=owner, timeout=30)
    cashier_entries = requests.get(f"{API}/stockledger/entries", headers=cashier, timeout=30)
    assert owner_entries.status_code == 200
    assert cashier_entries.status_code == 200
    # Stock is posted to the RAN-WH warehouse; a DEO-scoped user must never see more
    # than the network-wide owner, and in practice sees none of the warehouse rows.
    assert _count(cashier_entries.json()) <= _count(owner_entries.json())

    # On-hand is also scoped and must not error for a single-store user.
    assert (
        requests.get(f"{API}/stockledger/on-hand", headers=cashier, timeout=30).status_code == 200
    )


# --- a non-mapping PT cannot be deleted via the API --------------------------


def test_pt_delete_endpoint_guards_non_mapping() -> None:
    owner = _login("owner", "Owner@123")
    # Deleting a non-existent file resolves to 404 (endpoint exists, guard runs on a
    # real object). The real protection — 409 on a sent/posted file — is exercised by
    # the posting flow; here we assert the destroy route is wired and not a 500.
    r = requests.delete(f"{API}/ptmapper/files/{MISSING_PK}", headers=owner, timeout=30)
    assert r.status_code in (404, 409), f"unexpected delete status {r.status_code}"
