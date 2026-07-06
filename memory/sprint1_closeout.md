# Sprint 1 Close-out Report — Outbound Module

**Date**: 6 July 2026  
**Status**: COMPLETE — pending tester re-run

---

## 1. Final Role Matrix

| Action | `owner` | `it_admin` | `ho_ops` | `accounts` | `store_manager` | `warehouse` | `store_staff` (cashier) |
|--------|---------|------------|----------|------------|-----------------|-------------|------------------------|
| **List / Detail** (all doc types) | ✅ | ✅ | ✅ | ✅ | ✅ (own store) | ✅ (own store) | ✅ (own store, **READ-ONLY**) |
| **Create / Submit** — Transfer | ✅ | ✅ | ✅ | ✅ | ✅ (own store) | ✅ (own store) | ❌ |
| **Dispatch** — Transfer | ✅ | ✅ | ✅ | ✅ | ✅ (source store) | ✅ (source store) | ❌ |
| **Receive** — Transfer | ✅ | ✅ | ✅ | ✅ | ✅ (dest store) | ✅ (dest store) | ❌ |
| **Create / Submit** — RTV | ✅ | ✅ | ✅ | ✅ | ✅ (own store) | ✅ (own store) | ❌ |
| **Create / Submit** — Adjustment | ✅ | ✅ | ✅ | ✅ | ✅ (own store) | ✅ (own store) | ❌ |
| **Create / Submit** — Write-off | ✅ | ✅ | ✅ | ✅ | ❌ | ❌ | ❌ |
| **Create / Submit** — V-Flip | ✅ | ✅ | ✅ | ✅ | ❌ | ❌ | ❌ |

**Three enforcement layers:**
1. **Role gate** — `IsOutboundWriter` / `IsOutboundAdmin` DRF permission classes (role-based)
2. **Store-scope gate** — `enforce_store_scope(user, store_id)` shared helper (scope-based, 403 if out-of-scope)
3. **Frontend gate** — `canOutboundWrite()` / `canOutboundAdmin()` in `outbound-rbac.ts` (UI visibility)

---

## 2. Diff Summary — Files Touched

### Finding 1 Fix: Store-scope enforcement

| File | Change |
|------|--------|
| `outbound/permissions.py` | Added `enforce_store_scope(user, store_id)` — single shared helper using existing `visible_store_ids()`. Raises `PermissionDenied` (403) when store is outside user's scope. |
| `outbound/views.py` | Added `enforce_store_scope()` call in every write path: Transfer (create: source_store, dispatch: source_store, receive: destination_store), RTV (create + submit), Adjustment (create + submit), WriteOff (create + submit), VFlip (create + submit). Total: 10 enforcement points, all via the same helper. |
| `tests/test_outbound_store_scope.py` | **NEW**: 10 API-level tests via DRF APIClient — SM blocked outside scope, SM allowed in scope, admin unrestricted, transfer receive scope on destination store. |

### Finding 2 Fix: V-flip brand display

| File | Change |
|------|--------|
| `outbound/posting.py` | Line ~453: Changed `f"V {line.brand}" if line.brand else "V KDPS"` → falls back to `vflip.original_brand.name` when `line.brand` is empty. |
| `outbound/management/commands/fix_rtv28_vflip_brand.py` | **NEW**: One-shot command to cancel RTV 28 + backfill "V KDPS" → "V Louis Philippe" in StockOnHand (direct update) and SLE (append-only compensating entries). Idempotent. |
| `tests/test_outbound_sprint1.py` | Added `test_vflip_empty_line_brand_uses_original_brand` — verifies that when `line.brand=""` the V-prefix uses `original_brand.name`, not "KDPS". |

---

## 3. Polluted RTV id=28 Cancellation

| Attribute | Value |
|-----------|-------|
| Doc number | `26-27/BANKA/RTV/1` |
| Store | BANKA (out of deo.manager's scope) |
| Brand | Blackberrys (owned) |
| unit_cost_paise | 0 (no GL impact) |
| SLE impact | 1 unit stock out of BB-TROU-GRY-34 |
| GL impact | None (cost was 0) |
| VLE impact | None |

**Cleanup actions:**
- Appended reversing SLE entry (+1 BB-TROU-GRY-34 at BANKA)
- Updated StockOnHand: BANKA BB-TROU-GRY-34 restored from 14 → 15 units
- Set docstatus to CANCELLED

### Post-cleanup `/api/finledger/health`:
```json
{
    "balanced": true,
    "trial_balance_paise": 0,
    "reconciliation": {
        "reconciled": true,
        "vendor": { "drift_paise": 0 },
        "cash": { "drift_paise": 0 }
    }
}
```
**✅ balanced, ✅ reconciled, 0 drift everywhere.**

---

## 4. V-Flip Brand Display Fix

| Before | After |
|--------|-------|
| `StockOnHand.brand = "V KDPS"` | `StockOnHand.brand = "V Louis Philippe"` |
| SLE vflip_in brand = "V KDPS" | Compensating entries: -1 "V KDPS" + +1 "V Louis Philippe" |

**Root cause**: `line.brand` was empty string (frontend doesn't always populate it), and the code fell back to `"V KDPS"` instead of `vflip.original_brand.name`.

**Fix**: Changed fallback from `"V KDPS"` to `vflip.original_brand.name` in `post_vflip()`.

**Current on-hand display:**
```
LP-POLO-BLK-L         brand=Louis Philippe            qty=4
LP-SLIM-WHT-38        brand=V Louis Philippe          qty=13
```

---

## 5. Regression Test Counts

| | Before | After | Delta |
|--|--------|-------|-------|
| Total pytest | 390 passed, 1 skipped | **401 passed, 1 skipped** | +11 |
| Outbound posting | 23 | **24** | +1 (empty brand fallback) |
| Store-scope API | 0 | **10** | +10 (new file) |
| Failures | 0 | **0** | — |

---

## 6. Env Change (from prior fix)

| File | Before | After |
|------|--------|-------|
| `frontend/.env` | `REACT_APP_BACKEND_URL=https://bookstore-erp-1.preview.emergentagent.com` | `REACT_APP_BACKEND_URL=` (empty → same-origin) |
| `frontend/src/lib/api.ts` | Hard throw on missing BASE | Graceful fallback to `""` (same-origin) |

---

## 7. Deferred Items from Sprint 1

| Item | Deferred to | Reason |
|------|-------------|--------|
| Settlement claim tracking (V-flip, RTV credit notes) | Sprint 8 (Payments) | Requires payment module |
| EOSS pricing rules | Sprint 2 (Offers) | Requires offer engine |
| Multi-tier approval workflows | Sprint 5 (Controls) | Requires exception/controls framework |
| Non-branded PT AI/OCR wiring | Future (P2) | Gemini integration present but not active |
| V-flip past-return-window dashboard alert | Enhancement (backlog) | Needs cron/scheduler |
