# Sprint 1 Close-out Report — Outbound Module

**Date**: 6 July 2026  
**Status**: COMPLETE — pending tester sign-off

---

## 1. Final Role Matrix

| Action | `owner` | `it_admin` | `ho_ops` | `accounts` | `store_manager` | `warehouse` | `store_staff` (cashier) |
|--------|---------|------------|----------|------------|-----------------|-------------|------------------------|
| **List / Detail** (all doc types) | ✅ | ✅ | ✅ | ✅ | ✅ (own store) | ✅ (own store) | ✅ (own store, **READ-ONLY**) |
| **Create / Submit** — Transfer | ✅ | ✅ | ✅ | ✅ | ✅ (own store) | ✅ (own store) | ❌ |
| **Dispatch / Receive** — Transfer | ✅ | ✅ | ✅ | ✅ | ✅ (own store) | ✅ (own store) | ❌ |
| **Create / Submit** — RTV | ✅ | ✅ | ✅ | ✅ | ✅ (own store) | ✅ (own store) | ❌ |
| **Create / Submit** — Adjustment | ✅ | ✅ | ✅ | ✅ | ✅ (own store) | ✅ (own store) | ❌ |
| **Create / Submit** — Write-off | ✅ | ✅ | ✅ | ✅ | ❌ | ❌ | ❌ |
| **Create / Submit** — V-Flip | ✅ | ✅ | ✅ | ✅ | ❌ | ❌ | ❌ |

**Backend enforcement**: `IsOutboundReader`, `IsOutboundWriter`, `IsOutboundAdmin` permission classes in `outbound/permissions.py`.  
**Frontend enforcement**: `canOutboundWrite()` / `canOutboundAdmin()` helpers in `lib/outbound-rbac.ts` — hide Create/Submit buttons and forms for unauthorized roles.

---

## 2. Permission Diff Summary

### Backend (`outbound/permissions.py` — NEW file)
- `OUTBOUND_WRITE_ROLES = {owner, it_admin, ho_ops, accounts, store_manager, warehouse}`
- `OUTBOUND_ADMIN_ROLES = {owner, it_admin, ho_ops, accounts}`
- Three DRF permission classes: `IsOutboundReader`, `IsOutboundWriter`, `IsOutboundAdmin`

### Backend (`outbound/views.py` — MODIFIED)
- All list/detail views: `permission_classes = [IsOutboundReader]`
- Create/submit/dispatch/receive views (Transfer, RTV, Adjustment): `permission_classes = [IsOutboundWriter]`
- V-flip and Write-off create/submit views: `permission_classes = [IsOutboundAdmin]`

### Frontend (`lib/outbound-rbac.ts` — NEW file)
- `canOutboundWrite(roleCode)` — mirrors backend writer check
- `canOutboundAdmin(roleCode)` — mirrors backend admin check

### Frontend (Outbound pages — MODIFIED)
- All 5 Outbound page components (Transfers, RTV, Adjustments, Write-offs, V-Flip) conditionally render Create buttons and Submit actions based on role.

---

## 3. Polluted RTV Cleanup Confirmation

The unauthorized RTV (doc id 16) was cancelled and its ledger effects reversed:
- `docstatus` set to `CANCELLED`
- Stock ledger reversal entries posted (negative of original)
- GL reversal voucher posted (balanced)
- `VendorLedgerEntry` reversed

### Post-cleanup `/api/finledger/health` payload:
```json
{
    "balanced": true,
    "trial_balance_paise": 0,
    "trial_balance_rupees": "0.00",
    "reconciliation": {
        "reconciled": true,
        "vendor": {
            "reconciled": true,
            "subledger_paise": 6788000,
            "gl_control_paise": 6788000,
            "drift_paise": 0
        },
        "cash": {
            "reconciled": true,
            "subledger_paise": 0,
            "gl_control_paise": 0,
            "drift_paise": 0
        }
    },
    "assets_paise": 11588000,
    "liabilities_paise": 11588000,
    "leg_count": 22,
    "voucher_count": 11
}
```
**Ledger health: ✅ balanced, ✅ reconciled, 0 drift everywhere.**

---

## 4. Regression Test Counts

| Suite | Before RBAC | After RBAC + V-flip regression | Status |
|-------|-------------|-------------------------------|--------|
| Full backend pytest | 387 passed, 1 skipped | **390 passed, 1 skipped** | ✅ 0 failures |
| Outbound-specific | 20 tests | **23 tests** | ✅ 0 failures |
| Frontend (iteration_21) | 14/14 features | 14/14 features | ✅ |
| Bug fix (iteration_22) | 8/8 | 8/8 | ✅ |

### New tests added (this session):
1. `test_vflip_brand_displays_v_prefix` — V-flip sets StockOnHand.brand = "V {brand}", net_qty unchanged, SLE carries V-prefix
2. `test_vflip_ownership_is_kdps_owned` — GL has Dr INVENTORY (KDPS-owned), not SOR_STOCK
3. `test_rtv_blocked_for_vflipped_stock` — seasonal RTV on V-flipped SKU raises `OutboundPostingError`

---

## 5. Environment Change

### Issue
`REACT_APP_BACKEND_URL` was hardcoded to a stale pod URL (`bookstore-erp-1.preview.emergentagent.com`), causing CORS failures when the platform issued a different preview URL.

### Fix — same-origin approach
The platform's Kubernetes ingress routes `/api/*` → backend and `/*` → frontend behind the **same** hostname. The frontend no longer needs an absolute backend URL.

| File | Before | After |
|------|--------|-------|
| `frontend/.env` | `REACT_APP_BACKEND_URL=https://bookstore-erp-1.preview.emergentagent.com` | `REACT_APP_BACKEND_URL=` (empty) |
| `frontend/src/lib/api.ts` | `const BASE = import.meta.env.REACT_APP_BACKEND_URL as string;`<br>`if (!BASE) throw new Error(...)` | `const BASE = (import.meta.env.REACT_APP_BACKEND_URL as string) \|\| "";` |

**Behavior**: When `REACT_APP_BACKEND_URL` is empty, axios baseURL is `/api` (same-origin). Set it explicitly only for cross-origin dev (e.g., local FE → remote API). Works on any pod/preview URL without hardcoding.

---

## 6. V-Flip Reporting Verification

### Verification checklist

| # | Check | Result | Detail |
|---|-------|--------|--------|
| 1a | Stock on-hand shows "V {brand}" after flip | ✅ | `StockOnHand.brand` updated to "V {brand}" on the positive-qty inward in `_write_stock_entry` (line 104 refresh). Confirmed by test `test_vflip_brand_displays_v_prefix`. |
| 1b | Stock ledger entries carry "V {brand}" | ✅ | `vflip_in` SLE rows store `brand="V SORBrand"`. `vflip_out` rows keep the original brand for audit trail. |
| 1c | Brand-scoped filters work correctly | ✅ | `/api/stockledger/on-hand?brand=Louis Philippe` returns un-flipped stock only. `?brand=V Louis Philippe` returns flipped stock. No data vanishes. |
| 2a | Ownership flag is KDPS-owned in GL | ✅ | GL posts `Dr INVENTORY / Cr SUSPENSE` (KDPS-owned). SOR pair reversed. Confirmed by test `test_vflip_ownership_is_kdps_owned`. |
| 2b | Seasonal RTV blocked for V-flipped stock | ✅ **PATCHED** | **Gap found**: `post_rtv` only checked `Brand.ownership` (master), not actual stock state. **Fix**: Added check in `post_rtv` — if any line's `StockOnHand.brand` starts with "V ", raises `OutboundPostingError("Cannot RTV V-flipped stock")`. Confirmed by test `test_rtv_blocked_for_vflipped_stock`. |

### Patch applied
**File**: `outbound/posting.py` — `post_rtv()`, after stock check, before `rtv.post()`:
```python
# Block RTVs on V-flipped stock: ownership has transferred to KDPS,
# so returning it to the brand is no longer valid.
vflipped_skus = list(
    StockOnHand.objects.filter(
        store_id=rtv.store_id,
        sku_code__in=[l.sku_code for l in lines],
        brand__startswith="V ",
    ).values_list("sku_code", flat=True)
)
if vflipped_skus:
    raise OutboundPostingError(
        f"Cannot RTV V-flipped stock (ownership transferred to KDPS): "
        f"{', '.join(vflipped_skus)}"
    )
```

---

## 7. Deferred Items from Sprint 1

| Item | Deferred to | Reason |
|------|-------------|--------|
| Settlement claim tracking (V-flip, RTV credit notes) | Sprint 8 (Payments) | Requires payment module |
| EOSS pricing rules | Sprint 2 (Offers) | Requires offer engine |
| Multi-tier approval workflows | Sprint 5 (Controls) | Requires exception/controls framework |
| Non-branded PT AI/OCR wiring | Future (P2) | Gemini integration present but not active |
| V-flip past-return-window dashboard alert | Enhancement (backlog) | Needs cron/scheduler |

---

## 8. Files Modified This Session

| File | Change |
|------|--------|
| `frontend/.env` | `REACT_APP_BACKEND_URL` set to empty (same-origin) |
| `frontend/src/lib/api.ts` | Graceful fallback to same-origin when env var empty |
| `backend/outbound/posting.py` | V-flip guard added to `post_rtv()` |
| `backend/tests/test_outbound_sprint1.py` | 3 regression tests added (V-flip brand display, ownership, RTV block) |
