"""Iteration 16 — Live API verification of F1 (unified GL + subledger reconciliation).

Runs against the deployed preview host (REACT_APP_BACKEND_URL) — NOT the local
django TestCase database. All assertions target the /api/finledger endpoints
described in the review request:

    - JWT login (owner / accounts / warehouse)
    - GET /api/finledger/health → balanced + reconciliation block
    - POST /api/finledger/vendor/bill + /vendor/payment → still reconciled
    - POST /api/finledger/cash/movement (in + out) → still reconciled
    - RBAC: warehouse role → 403; finance roles → 200 / 201
    - Reversal: 1st → 201, 2nd → 409 (AlreadyReversedError), health still tied
"""

from __future__ import annotations

import os
import time
import uuid

import pytest
import requests

BASE_URL = "https://kdps-delivery-check.preview.emergentagent.com"

CREDS = {
    "owner": ("owner", "Owner@123"),
    "accounts": ("accounts1", "Acct@123"),
    "warehouse": ("wh.patna", "Wh@123"),
}


def _login(username: str, password: str) -> str:
    r = requests.post(
        f"{BASE_URL}/api/auth/login",
        json={"username": username, "password": password},
        timeout=30,
    )
    assert r.status_code == 200, f"login {username} → {r.status_code} {r.text[:200]}"
    body = r.json()
    tok = body.get("access") or body.get("token") or body.get("access_token")
    assert tok, f"no access token in login response: {body}"
    return tok


@pytest.fixture(scope="module")
def owner_token() -> str:
    return _login(*CREDS["owner"])


@pytest.fixture(scope="module")
def accounts_token() -> str:
    return _login(*CREDS["accounts"])


@pytest.fixture(scope="module")
def warehouse_token() -> str:
    return _login(*CREDS["warehouse"])


def _hdr(tok: str) -> dict:
    return {"Authorization": f"Bearer {tok}", "Content-Type": "application/json"}


def _health(tok: str) -> dict:
    r = requests.get(f"{BASE_URL}/api/finledger/health", headers=_hdr(tok), timeout=30)
    assert r.status_code == 200, f"health → {r.status_code} {r.text[:200]}"
    return r.json()


def _assert_reconciled(h: dict) -> None:
    assert "reconciliation" in h, f"missing reconciliation block: keys={list(h)}"
    rec = h["reconciliation"]
    assert h.get("balanced") is True, f"not balanced: trial_balance_paise={h.get('trial_balance_paise')}"
    assert h["trial_balance_paise"] == 0, f"trial_balance_paise={h['trial_balance_paise']}"
    for side in ("vendor", "cash"):
        assert side in rec, f"reconciliation missing {side} block"
        for k in ("reconciled", "subledger_paise", "gl_control_paise", "drift_paise"):
            assert k in rec[side], f"reconciliation.{side} missing {k}"
        assert rec[side]["drift_paise"] == 0, f"{side} drift={rec[side]['drift_paise']}"
        assert rec[side]["reconciled"] is True, f"{side} not reconciled: {rec[side]}"
        assert rec[side]["subledger_paise"] == rec[side]["gl_control_paise"], (
            f"{side} subledger {rec[side]['subledger_paise']} != gl_control "
            f"{rec[side]['gl_control_paise']}"
        )
    assert rec["reconciled"] is True, f"reconciliation.reconciled false: {rec}"


# --- Basic health + auth --------------------------------------------------


def test_health_requires_auth() -> None:
    r = requests.get(f"{BASE_URL}/api/finledger/health", timeout=30)
    assert r.status_code in (401, 403), f"unauth health → {r.status_code}"


def test_health_baseline_reconciled(owner_token: str) -> None:
    h = _health(owner_token)
    _assert_reconciled(h)


def test_health_accounts_role_allowed(accounts_token: str) -> None:
    h = _health(accounts_token)
    _assert_reconciled(h)


def test_health_warehouse_role_forbidden(warehouse_token: str) -> None:
    r = requests.get(f"{BASE_URL}/api/finledger/health", headers=_hdr(warehouse_token), timeout=30)
    assert r.status_code == 403, f"expected 403 for warehouse, got {r.status_code} {r.text[:120]}"


# --- F1 double-entry integrity via live vendor bill + payment --------------


@pytest.fixture(scope="module")
def vendor_id(owner_token: str) -> int:
    r = requests.get(f"{BASE_URL}/api/vendors", headers=_hdr(owner_token), timeout=30)
    assert r.status_code == 200, f"vendors list → {r.status_code} {r.text[:200]}"
    body = r.json()
    results = body.get("results") if isinstance(body, dict) else body
    assert results, f"no vendors in list: {body}"
    return results[0]["id"]


def test_vendor_bill_and_payment_keep_books_tied(owner_token: str, vendor_id: int) -> None:
    before = _health(owner_token)
    _assert_reconciled(before)
    ven0 = before["reconciliation"]["vendor"]["subledger_paise"]
    cash0 = before["reconciliation"]["cash"]["subledger_paise"]

    tag = uuid.uuid4().hex[:8]

    r = requests.post(
        f"{BASE_URL}/api/finledger/vendor/bill",
        headers=_hdr(owner_token),
        json={"vendor_id": vendor_id, "amount": "1000.00", "description": f"iter16-bill-{tag}"},
        timeout=30,
    )
    assert r.status_code == 201, f"vendor/bill → {r.status_code} {r.text[:300]}"

    mid = _health(owner_token)
    _assert_reconciled(mid)
    assert mid["reconciliation"]["vendor"]["subledger_paise"] == ven0 + 100000, (
        f"vendor payable delta wrong: {ven0} -> {mid['reconciliation']['vendor']['subledger_paise']}"
    )
    assert mid["reconciliation"]["cash"]["subledger_paise"] == cash0, (
        "cash should be unchanged after a vendor bill"
    )

    r = requests.post(
        f"{BASE_URL}/api/finledger/vendor/payment",
        headers=_hdr(owner_token),
        json={"vendor_id": vendor_id, "amount": "400.00", "description": f"iter16-pay-{tag}"},
        timeout=30,
    )
    assert r.status_code == 201, f"vendor/payment → {r.status_code} {r.text[:300]}"

    after = _health(owner_token)
    _assert_reconciled(after)
    # Payment reduces payable by 40000 paise AND reduces cash by 40000 paise
    assert after["reconciliation"]["vendor"]["subledger_paise"] == ven0 + 100000 - 40000, (
        f"vendor payable after payment wrong: {after['reconciliation']['vendor']['subledger_paise']}"
    )
    assert after["reconciliation"]["cash"]["subledger_paise"] == cash0 - 40000, (
        f"cash after payment wrong: {after['reconciliation']['cash']['subledger_paise']}"
    )


# --- Cash movement in + out ------------------------------------------------


def test_cash_movement_in_out_keeps_reconciled(owner_token: str) -> None:
    before = _health(owner_token)
    _assert_reconciled(before)
    cash0 = before["reconciliation"]["cash"]["subledger_paise"]

    r = requests.post(
        f"{BASE_URL}/api/finledger/cash/movement",
        headers=_hdr(owner_token),
        json={"direction": "in", "amount": "500.00", "description": "iter16-float"},
        timeout=30,
    )
    assert r.status_code == 201, f"cash/movement in → {r.status_code} {r.text[:200]}"
    mid = _health(owner_token)
    _assert_reconciled(mid)
    assert mid["reconciliation"]["cash"]["subledger_paise"] == cash0 + 50000

    r = requests.post(
        f"{BASE_URL}/api/finledger/cash/movement",
        headers=_hdr(owner_token),
        json={"direction": "out", "amount": "200.00", "description": "iter16-spend"},
        timeout=30,
    )
    assert r.status_code == 201, f"cash/movement out → {r.status_code} {r.text[:200]}"
    after = _health(owner_token)
    _assert_reconciled(after)
    assert after["reconciliation"]["cash"]["subledger_paise"] == cash0 + 50000 - 20000


# --- RBAC on the posting endpoints -----------------------------------------


def test_rbac_warehouse_cannot_post_vendor_bill(warehouse_token: str, vendor_id: int) -> None:
    r = requests.post(
        f"{BASE_URL}/api/finledger/vendor/bill",
        headers=_hdr(warehouse_token),
        json={"vendor_id": vendor_id, "amount": "1.00", "description": "nope"},
        timeout=30,
    )
    assert r.status_code == 403, f"warehouse bill got {r.status_code} {r.text[:120]}"


def test_rbac_warehouse_cannot_post_cash_movement(warehouse_token: str) -> None:
    r = requests.post(
        f"{BASE_URL}/api/finledger/cash/movement",
        headers=_hdr(warehouse_token),
        json={"direction": "in", "amount": "1.00", "description": "nope"},
        timeout=30,
    )
    assert r.status_code == 403, f"warehouse cash got {r.status_code} {r.text[:120]}"


def test_rbac_accounts_role_can_post_cash_movement(accounts_token: str) -> None:
    r = requests.post(
        f"{BASE_URL}/api/finledger/cash/movement",
        headers=_hdr(accounts_token),
        json={"direction": "in", "amount": "10.00", "description": "iter16-acct-check"},
        timeout=30,
    )
    assert r.status_code == 201, f"accounts cash got {r.status_code} {r.text[:120]}"
    # net back out so we don't drift the demo cash upward permanently
    r2 = requests.post(
        f"{BASE_URL}/api/finledger/cash/movement",
        headers=_hdr(accounts_token),
        json={"direction": "out", "amount": "10.00", "description": "iter16-acct-check-back"},
        timeout=30,
    )
    assert r2.status_code == 201


# --- Reversal integrity ----------------------------------------------------


def test_vendor_reverse_double_reverse_is_409(owner_token: str, vendor_id: int) -> None:
    tag = uuid.uuid4().hex[:8]
    r = requests.post(
        f"{BASE_URL}/api/finledger/vendor/bill",
        headers=_hdr(owner_token),
        json={"vendor_id": vendor_id, "amount": "111.00", "description": f"iter16-revtest-{tag}"},
        timeout=30,
    )
    assert r.status_code == 201, f"post bill for reversal → {r.status_code} {r.text[:200]}"
    entry_pk = r.json().get("id")
    assert entry_pk, f"no id in bill response: {r.json()}"

    # health must still tie right after posting
    _assert_reconciled(_health(owner_token))

    # 1st reverse → 201
    r1 = requests.post(
        f"{BASE_URL}/api/finledger/vendor/entries/{entry_pk}/reverse",
        headers=_hdr(owner_token),
        timeout=30,
    )
    assert r1.status_code == 201, f"1st vendor reverse → {r1.status_code} {r1.text[:200]}"
    _assert_reconciled(_health(owner_token))

    # 2nd reverse → 409
    r2 = requests.post(
        f"{BASE_URL}/api/finledger/vendor/entries/{entry_pk}/reverse",
        headers=_hdr(owner_token),
        timeout=30,
    )
    assert r2.status_code == 409, f"2nd vendor reverse → {r2.status_code} {r2.text[:200]}"


def test_cash_reverse_double_reverse_is_409(owner_token: str) -> None:
    r = requests.post(
        f"{BASE_URL}/api/finledger/cash/movement",
        headers=_hdr(owner_token),
        json={"direction": "in", "amount": "77.00", "description": "iter16-cash-revtest"},
        timeout=30,
    )
    assert r.status_code == 201, f"post cash for reversal → {r.status_code} {r.text[:200]}"
    entry_pk = r.json().get("id")
    assert entry_pk, f"no id in cash response: {r.json()}"

    _assert_reconciled(_health(owner_token))

    r1 = requests.post(
        f"{BASE_URL}/api/finledger/cash/entries/{entry_pk}/reverse",
        headers=_hdr(owner_token),
        timeout=30,
    )
    assert r1.status_code == 201, f"1st cash reverse → {r1.status_code} {r1.text[:200]}"
    _assert_reconciled(_health(owner_token))

    r2 = requests.post(
        f"{BASE_URL}/api/finledger/cash/entries/{entry_pk}/reverse",
        headers=_hdr(owner_token),
        timeout=30,
    )
    assert r2.status_code == 409, f"2nd cash reverse → {r2.status_code} {r2.text[:200]}"


def test_vendor_reverse_404_for_unknown_pk(owner_token: str) -> None:
    r = requests.post(
        f"{BASE_URL}/api/finledger/vendor/entries/9999999/reverse",
        headers=_hdr(owner_token),
        timeout=30,
    )
    assert r.status_code == 404, f"unknown pk → {r.status_code}"


def test_final_health_still_tied(owner_token: str) -> None:
    # After all the above churn the books must still tie.
    time.sleep(0.2)
    _assert_reconciled(_health(owner_token))
