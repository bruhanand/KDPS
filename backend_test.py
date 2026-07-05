"""
KDPS Operating System - Backend API Test Suite
Tests against local backend at http://localhost:8001
"""
import requests
import sys
import json

BASE = "http://localhost:8001"
API = f"{BASE}/api"

results = []


def record(name, ok, detail=""):
    status = "PASS" if ok else "FAIL"
    results.append((name, ok, detail))
    print(f"[{status}] {name}: {detail}")


def try_login(username, password):
    r = requests.post(f"{API}/auth/login", json={"username": username, "password": password}, timeout=15)
    return r


def main():
    # 1. Health
    try:
        r = requests.get(f"{API}/health", timeout=10)
        record("GET /api/health", r.status_code == 200 and r.json().get("status") == "ok",
               f"code={r.status_code} body={r.text[:120]}")
    except Exception as e:
        record("GET /api/health", False, str(e))

    # 2. Schema
    try:
        r = requests.get(f"{API}/schema/", timeout=15)
        ct = r.headers.get("content-type", "")
        ok = r.status_code == 200 and ("yaml" in ct.lower() or "openapi" in r.text[:200].lower())
        record("GET /api/schema/", ok, f"code={r.status_code} ct={ct} preview={r.text[:80]!r}")
    except Exception as e:
        record("GET /api/schema/", False, str(e))

    # 3. Auth - valid login
    owner_access = None
    owner_refresh = None
    owner_user = None
    try:
        r = try_login("owner", "Owner@123")
        if r.status_code == 200:
            data = r.json()
            owner_access = data.get("access")
            owner_refresh = data.get("refresh")
            owner_user = data.get("user")
            ok = bool(owner_access and owner_refresh and owner_user)
            record("POST /api/auth/login (owner)", ok,
                   f"code=200 has_access={bool(owner_access)} has_refresh={bool(owner_refresh)} has_user={bool(owner_user)}")
        else:
            record("POST /api/auth/login (owner)", False, f"code={r.status_code} body={r.text[:200]}")
    except Exception as e:
        record("POST /api/auth/login (owner)", False, str(e))

    # 4. Auth - invalid login
    try:
        r = try_login("owner", "WrongPassword123!")
        record("POST /api/auth/login (invalid)", r.status_code == 401,
               f"code={r.status_code} body={r.text[:120]}")
    except Exception as e:
        record("POST /api/auth/login (invalid)", False, str(e))

    # 5. /auth/me with token
    if owner_access:
        try:
            r = requests.get(f"{API}/auth/me", headers={"Authorization": f"Bearer {owner_access}"}, timeout=10)
            ok = r.status_code == 200 and isinstance(r.json(), dict) and r.json().get("username") == "owner"
            record("GET /api/auth/me (with token)", ok, f"code={r.status_code} body={r.text[:200]}")
        except Exception as e:
            record("GET /api/auth/me (with token)", False, str(e))
    else:
        record("GET /api/auth/me (with token)", False, "no token from owner login")

    # 6. /auth/me without token
    try:
        # Use fresh session to avoid cookie fallback
        s = requests.Session()
        r = s.get(f"{API}/auth/me", timeout=10)
        record("GET /api/auth/me (no token)", r.status_code == 401,
               f"code={r.status_code} body={r.text[:120]}")
    except Exception as e:
        record("GET /api/auth/me (no token)", False, str(e))

    # 7. Refresh token
    if owner_refresh:
        try:
            r = requests.post(f"{API}/auth/refresh", json={"refresh": owner_refresh}, timeout=10)
            data = r.json() if r.status_code == 200 else {}
            ok = r.status_code == 200 and bool(data.get("access"))
            record("POST /api/auth/refresh", ok, f"code={r.status_code} has_access={bool(data.get('access'))}")
        except Exception as e:
            record("POST /api/auth/refresh", False, str(e))
    else:
        record("POST /api/auth/refresh", False, "no refresh token")

    # 8. Logout
    if owner_access:
        try:
            r = requests.post(f"{API}/auth/logout",
                              headers={"Authorization": f"Bearer {owner_access}"},
                              json={"refresh": owner_refresh} if owner_refresh else {},
                              timeout=10)
            record("POST /api/auth/logout", r.status_code in (200, 204, 205),
                   f"code={r.status_code} body={r.text[:120]}")
        except Exception as e:
            record("POST /api/auth/logout", False, str(e))
    else:
        record("POST /api/auth/logout", False, "no token")

    # Get fresh owner token (post-logout might be blacklisted)
    r = try_login("owner", "Owner@123")
    owner_access = r.json().get("access") if r.status_code == 200 else None

    # 9. RBAC - Owner accessing admin roles
    if owner_access:
        try:
            r = requests.get(f"{API}/auth/admin/roles",
                             headers={"Authorization": f"Bearer {owner_access}"}, timeout=10)
            record("RBAC: Owner GET /api/auth/admin/roles", r.status_code == 200,
                   f"code={r.status_code} body_len={len(r.text)}")
        except Exception as e:
            record("RBAC: Owner GET /api/auth/admin/roles", False, str(e))

    # 10. RBAC - Store cashier forbidden
    try:
        r = try_login("deo.cashier", "Store@123")
        if r.status_code == 200:
            cashier_access = r.json().get("access")
            r2 = requests.get(f"{API}/auth/admin/roles",
                              headers={"Authorization": f"Bearer {cashier_access}"}, timeout=10)
            record("RBAC: Cashier GET /api/auth/admin/roles (should 403)", r2.status_code == 403,
                   f"code={r2.status_code} body={r2.text[:150]}")
        else:
            record("RBAC: Cashier login", False, f"login code={r.status_code} body={r.text[:150]}")
    except Exception as e:
        record("RBAC: Cashier RBAC test", False, str(e))

    # 11. RBAC - Store manager can login and access store data
    try:
        r = try_login("deo.manager", "Store@123")
        if r.status_code == 200:
            mgr_access = r.json().get("access")
            # Try a store-scoped endpoint - stores listing
            r2 = requests.get(f"{API}/masters/stores",
                              headers={"Authorization": f"Bearer {mgr_access}"}, timeout=10)
            record("RBAC: Manager GET /api/masters/stores", r2.status_code == 200,
                   f"code={r2.status_code}")
        else:
            record("RBAC: Manager login", False, f"code={r.status_code} body={r.text[:150]}")
    except Exception as e:
        record("RBAC: Manager test", False, str(e))

    # 12. Master data - stores
    if owner_access:
        h = {"Authorization": f"Bearer {owner_access}"}
        try:
            r = requests.get(f"{API}/masters/stores", headers=h, timeout=15)
            data = r.json() if r.status_code == 200 else {}
            items = data.get("results") if isinstance(data, dict) and "results" in data else data
            count = len(items) if isinstance(items, list) else 0
            record("GET /api/masters/stores", r.status_code == 200 and count >= 6,
                   f"code={r.status_code} count={count}")
        except Exception as e:
            record("GET /api/masters/stores", False, str(e))

        # 13. Master data - brands
        try:
            r = requests.get(f"{API}/masters/brands?page_size=100", headers=h, timeout=15)
            data = r.json() if r.status_code == 200 else {}
            items = data.get("results") if isinstance(data, dict) and "results" in data else data
            total = data.get("count") if isinstance(data, dict) else None
            count = total if total is not None else (len(items) if isinstance(items, list) else 0)
            record("GET /api/masters/brands", r.status_code == 200 and count >= 10,
                   f"code={r.status_code} count={count}")
        except Exception as e:
            record("GET /api/masters/brands", False, str(e))

        # 14. Master data - seasons
        try:
            r = requests.get(f"{API}/masters/seasons", headers=h, timeout=15)
            data = r.json() if r.status_code == 200 else {}
            items = data.get("results") if isinstance(data, dict) and "results" in data else data
            count = len(items) if isinstance(items, list) else 0
            record("GET /api/masters/seasons", r.status_code == 200 and count >= 1,
                   f"code={r.status_code} count={count}")
        except Exception as e:
            record("GET /api/masters/seasons", False, str(e))

    # 15. Finledger health as accounts1
    try:
        r = try_login("accounts1", "Acct@123")
        if r.status_code == 200:
            acc_access = r.json().get("access")
            r2 = requests.get(f"{API}/finledger/health",
                              headers={"Authorization": f"Bearer {acc_access}"}, timeout=20)
            if r2.status_code == 200:
                d = r2.json()
                balanced = d.get("balanced")
                tb = d.get("trial_balance_paise")
                recon = d.get("reconciliation", {})
                reconciled = recon.get("reconciled") if isinstance(recon, dict) else None
                ok = (balanced is True) and (tb == 0) and (reconciled is True)
                record("GET /api/finledger/health", ok,
                       f"code=200 balanced={balanced} trial_balance_paise={tb} reconciled={reconciled}")
            else:
                record("GET /api/finledger/health", False, f"code={r2.status_code} body={r2.text[:250]}")
        else:
            record("accounts1 login", False, f"code={r.status_code} body={r.text[:150]}")
    except Exception as e:
        record("GET /api/finledger/health", False, str(e))

    # 16. Vendor Ledger entries + balances (owner)
    if owner_access:
        h = {"Authorization": f"Bearer {owner_access}"}
        try:
            r = requests.get(f"{API}/finledger/vendor/entries", headers=h, timeout=15)
            data = r.json() if r.status_code == 200 else {}
            has_pagination = isinstance(data, dict) and ("results" in data or "count" in data)
            record("GET /api/finledger/vendor/entries", r.status_code == 200 and has_pagination,
                   f"code={r.status_code} pagination={has_pagination} keys={list(data.keys())[:6] if isinstance(data, dict) else type(data).__name__}")
        except Exception as e:
            record("GET /api/finledger/vendor/entries", False, str(e))

        try:
            r = requests.get(f"{API}/finledger/vendor/balances", headers=h, timeout=15)
            record("GET /api/finledger/vendor/balances", r.status_code == 200,
                   f"code={r.status_code} preview={r.text[:200]}")
        except Exception as e:
            record("GET /api/finledger/vendor/balances", False, str(e))

    # 17. Error handling - 404
    try:
        r = requests.get(f"{API}/nonexistent", timeout=10)
        record("GET /api/nonexistent (404)", r.status_code == 404, f"code={r.status_code}")
    except Exception as e:
        record("GET /api/nonexistent (404)", False, str(e))

    # 18. Empty login body
    try:
        r = requests.post(f"{API}/auth/login", json={}, timeout=10)
        record("POST /api/auth/login (empty body)", r.status_code in (400, 401),
               f"code={r.status_code} body={r.text[:150]}")
    except Exception as e:
        record("POST /api/auth/login (empty body)", False, str(e))

    # Summary
    print("\n" + "=" * 70)
    passed = sum(1 for _, ok, _ in results if ok)
    failed = sum(1 for _, ok, _ in results if not ok)
    print(f"TOTAL: {len(results)}  PASSED: {passed}  FAILED: {failed}")
    print("=" * 70)
    if failed:
        print("\nFailed tests:")
        for n, ok, d in results:
            if not ok:
                print(f"  - {n}: {d}")
    sys.exit(0 if failed == 0 else 1)


if __name__ == "__main__":
    main()
