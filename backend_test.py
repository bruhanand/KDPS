"""KDPS Outbound module — API test suite.

Tests the following at http://localhost:8001:
- Auth (owner login)
- Transfer lifecycle (create draft, list, detail, dispatch failure on insufficient stock)
- RTV lifecycle (create draft, submit fails on insufficient stock)
- Adjustment lifecycle (create draft)
- Write-off lifecycle (create draft)
- V-flip lifecycle (create draft)
- Error handling (401, 400 on empty/invalid body, same source/dest)
- Books health (trial balance = 0)

Note: The POST create endpoints use a WriteSerializer that does not include
the created object's `id` or `docstatus` in the 201 response. This test
resolves the new id by listing and taking the most-recent record (list is
ordered by descending id in DRF's default).
"""

from __future__ import annotations

import json
import sys
from typing import Any

import requests

BASE_URL = "http://localhost:8001"
API = f"{BASE_URL}/api"


class Result:
    def __init__(self) -> None:
        self.passed: list[str] = []
        self.failed: list[tuple[str, str]] = []

    def ok(self, name: str) -> None:
        print(f"  PASS  {name}")
        self.passed.append(name)

    def fail(self, name: str, detail: str) -> None:
        print(f"  FAIL  {name} :: {detail}")
        self.failed.append((name, detail))

    def summary(self) -> None:
        print()
        print("=" * 70)
        print(f"PASSED: {len(self.passed)}")
        print(f"FAILED: {len(self.failed)}")
        if self.failed:
            print("\nFailures:")
            for n, d in self.failed:
                print(f"  - {n}: {d}")
        print("=" * 70)


R = Result()


def hdr(msg: str) -> None:
    print(f"\n== {msg} ==")


def dump(resp: requests.Response, limit: int = 500) -> str:
    try:
        return json.dumps(resp.json())[:limit]
    except Exception:
        return resp.text[:limit]


def get_token(username: str, password: str) -> str:
    r = requests.post(
        f"{API}/auth/login",
        json={"username": username, "password": password},
        timeout=10,
    )
    r.raise_for_status()
    return r.json()["access"]


def latest_id(base_path: str, headers: dict, matcher=None) -> int | None:
    """List and return the most-recent record id, optionally matching a filter."""
    r = requests.get(f"{API}/{base_path}", headers=headers, timeout=10)
    if r.status_code != 200:
        return None
    data = r.json()
    items = data.get("results", data) if isinstance(data, dict) else data
    if not isinstance(items, list) or not items:
        return None
    if matcher:
        for item in items:
            if matcher(item):
                return item.get("id")
    # otherwise pick max id
    ids = [i.get("id") for i in items if i.get("id") is not None]
    return max(ids) if ids else None


def main() -> int:
    hdr("Auth: login as owner")
    try:
        access = get_token("owner", "Owner@123")
        R.ok("POST /api/auth/login -> 200 with access token")
    except Exception as e:
        R.fail("POST /api/auth/login", f"{e}")
        R.summary()
        return 1

    H = {"Authorization": f"Bearer {access}", "Content-Type": "application/json"}

    # 1. Transfer lifecycle
    hdr("1. Transfer lifecycle")
    transfer_body: dict[str, Any] = {
        "source_store": 1,
        "destination_store": 2,
        "transfer_type": "inter_store",
        "reason": "slow_mover",
        "transport_mode": "public_bus",
        "transport_ref": "BUS-TESTAGENT",
        "dispatcher_name": "Ravi Kumar",
        "lines": [
            {
                "sku_code": "TEST-SKU-001",
                "design": "Test Shirt",
                "color": "Blue",
                "size": "M",
                "brand": "TestBrand",
                "qty_dispatched": 5,
                "unit_cost_paise": 10000,
            }
        ],
    }

    r = requests.post(f"{API}/outbound/transfers", json=transfer_body, headers=H, timeout=15)
    if r.status_code == 201:
        R.ok(f"POST /api/outbound/transfers -> 201 (draft created)")
    else:
        R.fail("POST /api/outbound/transfers create",
               f"status={r.status_code}, body={dump(r)}")

    # Resolve id via list
    transfer_id = latest_id(
        "outbound/transfers", H,
        matcher=lambda t: t.get("transport_ref") == "BUS-TESTAGENT",
    )

    # List
    r = requests.get(f"{API}/outbound/transfers", headers=H, timeout=10)
    if r.status_code == 200:
        data = r.json()
        items = data.get("results", data) if isinstance(data, dict) else data
        if isinstance(items, list) and len(items) >= 1:
            first = items[0]
            R.ok(
                f"GET /api/outbound/transfers -> 200, count={len(items)}, "
                f"first: id={first.get('id')} docstatus={first.get('docstatus')}"
            )
            # Verify docstatus=0 DRAFT on newly created record
            match = next((t for t in items if t.get("transport_ref") == "BUS-TESTAGENT"), None)
            if match and match.get("docstatus") == 0:
                R.ok("Created transfer has docstatus=0 (DRAFT)")
            else:
                R.fail("Created transfer docstatus check",
                       f"match={match}")
        else:
            R.fail("GET /api/outbound/transfers list", f"empty; body={dump(r)}")
    else:
        R.fail("GET /api/outbound/transfers list", f"status={r.status_code}")

    # Detail
    if transfer_id is not None:
        r = requests.get(f"{API}/outbound/transfers/{transfer_id}", headers=H, timeout=10)
        if r.status_code == 200:
            body = r.json()
            lines = body.get("lines", [])
            if isinstance(lines, list) and len(lines) >= 1:
                R.ok(
                    f"GET /api/outbound/transfers/{transfer_id} -> 200 "
                    f"with {len(lines)} line(s), docstatus={body.get('docstatus')}"
                )
            else:
                R.fail(
                    f"GET /api/outbound/transfers/{transfer_id}",
                    f"missing lines; body={dump(r)}",
                )
        else:
            R.fail(
                f"GET /api/outbound/transfers/{transfer_id}",
                f"status={r.status_code}",
            )

        # Dispatch should 400 with insufficient stock
        r = requests.post(
            f"{API}/outbound/transfers/{transfer_id}/dispatch",
            headers=H,
            timeout=15,
        )
        if r.status_code == 400:
            body_txt = dump(r).lower()
            if "insufficient" in body_txt or "stock" in body_txt:
                R.ok(f"POST dispatch -> 400 with stock error (body={dump(r, 200)})")
            else:
                R.fail("POST dispatch expected insufficient-stock",
                       f"400 but wrong message: {dump(r)}")
        else:
            R.fail("POST dispatch expected 400",
                   f"status={r.status_code}, body={dump(r)}")
    else:
        R.fail("Resolve created transfer id", "could not find id via list")

    # 2. RTV lifecycle
    hdr("2. RTV lifecycle")
    rtv_body = {
        "store": 1, "vendor": 1, "brand": 1, "return_type": "defective",
        "lines": [{"sku_code": "TEST-RTV-001", "qty": 1, "unit_cost_paise": 5000}],
        "notes": "sdet-created-rtv",
    }
    r = requests.post(f"{API}/outbound/rtvs", json=rtv_body, headers=H, timeout=15)
    if r.status_code == 201:
        R.ok("POST /api/outbound/rtvs -> 201 (draft created)")
    else:
        R.fail("POST /api/outbound/rtvs create",
               f"status={r.status_code}, body={dump(r)}")

    rtv_id = latest_id("outbound/rtvs", H,
                       matcher=lambda t: t.get("notes") == "sdet-created-rtv")
    if rtv_id is not None:
        r = requests.post(f"{API}/outbound/rtvs/{rtv_id}/submit", headers=H, timeout=15)
        if r.status_code == 400 and "stock" in dump(r).lower():
            R.ok(f"POST /api/outbound/rtvs/{rtv_id}/submit -> 400 stock error "
                 f"(body={dump(r,200)})")
        else:
            R.fail("POST rtvs/submit expected 400 stock",
                   f"status={r.status_code}, body={dump(r)}")
    else:
        R.fail("Resolve created RTV id", "could not find via list")

    # 3. Adjustment lifecycle
    hdr("3. Adjustment lifecycle")
    adj_body = {
        "store": 1, "reason": "shrinkage",
        "notes": "sdet-created-adj",
        "lines": [{
            "sku_code": "TEST-ADJ-001", "book_qty": 10, "counted_qty": 8,
            "adj_qty": -2, "unit_cost_paise": 5000,
        }],
    }
    r = requests.post(f"{API}/outbound/adjustments", json=adj_body, headers=H, timeout=15)
    if r.status_code == 201:
        R.ok("POST /api/outbound/adjustments -> 201 (draft created)")
    else:
        R.fail("POST /api/outbound/adjustments create",
               f"status={r.status_code}, body={dump(r)}")

    # 4. Write-off
    hdr("4. Write-off lifecycle")
    wo_body = {
        "store": 1, "reason": "Dead stock", "approved_by": 1,
        "lines": [{"sku_code": "TEST-WO-001", "qty": 1, "unit_cost_paise": 5000}],
    }
    r = requests.post(f"{API}/outbound/writeoffs", json=wo_body, headers=H, timeout=15)
    if r.status_code == 201:
        R.ok("POST /api/outbound/writeoffs -> 201 (draft created)")
    else:
        R.fail("POST /api/outbound/writeoffs create",
               f"status={r.status_code}, body={dump(r)}")

    # 5. V-flip
    hdr("5. V-flip lifecycle")
    vf_body = {
        "store": 1, "original_brand": 1, "season": "SS26", "authorized_by": 1,
        "lines": [{
            "sku_code": "TEST-VF-001", "brand": "TestBrand",
            "qty": 1, "unit_cost_paise": 5000,
        }],
    }
    r = requests.post(f"{API}/outbound/vflips", json=vf_body, headers=H, timeout=15)
    if r.status_code == 201:
        R.ok("POST /api/outbound/vflips -> 201 (draft created)")
    else:
        R.fail("POST /api/outbound/vflips create",
               f"status={r.status_code}, body={dump(r)}")

    # 6. Error handling
    hdr("6. Error handling")
    r = requests.get(f"{API}/outbound/transfers", timeout=10)
    if r.status_code == 401:
        R.ok("GET /api/outbound/transfers without auth -> 401")
    else:
        R.fail("GET without auth expected 401", f"status={r.status_code}")

    r = requests.post(f"{API}/outbound/transfers", json={}, headers=H, timeout=10)
    if r.status_code == 400:
        R.ok("POST /api/outbound/transfers with empty body -> 400")
    else:
        R.fail("POST empty body expected 400",
               f"status={r.status_code}, body={dump(r)}")

    bad = dict(transfer_body, destination_store=1)
    r = requests.post(f"{API}/outbound/transfers", json=bad, headers=H, timeout=10)
    if r.status_code == 400:
        R.ok(f"POST with same source and destination -> 400 (body={dump(r,200)})")
    else:
        R.fail("POST same source/dest expected 400",
               f"status={r.status_code}, body={dump(r)}")

    # Bad id → 404
    r = requests.get(f"{API}/outbound/transfers/99999", headers=H, timeout=10)
    if r.status_code == 404:
        R.ok("GET /api/outbound/transfers/99999 -> 404")
    else:
        R.fail("GET non-existent transfer expected 404",
               f"status={r.status_code}")

    # 7. Books health
    hdr("7. Books health (trial balance = 0)")
    r = requests.get(f"{API}/finledger/health", headers=H, timeout=10)
    if r.status_code == 200:
        body = r.json()
        balanced = body.get("balanced")
        tb = body.get("trial_balance_paise")
        if balanced is True and tb == 0:
            R.ok(f"GET /api/finledger/health -> balanced=true, trial_balance_paise=0")
        else:
            R.fail("Books health",
                   f"balanced={balanced}, tb={tb}, body={dump(r)}")
    else:
        R.fail("GET /api/finledger/health",
               f"status={r.status_code}, body={dump(r)}")

    R.summary()
    return 0 if not R.failed else 1


if __name__ == "__main__":
    sys.exit(main())
