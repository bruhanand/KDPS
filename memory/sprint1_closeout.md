# KDPS Sprint 1 — Close-out Report

## 1. Seed Command

**Command**: `python manage.py seed_outbound_demo`  
**Location**: `/app/app/backend/outbound/management/commands/seed_outbound_demo.py`  
**Idempotent**: Yes (checks sentinel PtFile filename before running)

### How to run
```bash
cd /app/app/backend
python manage.py seed_outbound_demo
```

The command:
1. Creates VoucherSeries for all outbound doc types (STO, RTV, ADJ, WRO, VFL) at all stores
2. Creates 3 Bookings → 3 GRNs → 3 PtFiles → posts via `post_pt_inward()` (the real inbound pipeline)
3. All stock, GL, vendor bills, and SKU identity flow through the same code path a real user would use

## 2. Seeded Stores / SKUs / Quantities

| Store | SKU Code | Brand | Ownership | Qty | Cost/pc | Total Value |
|-------|----------|-------|-----------|-----|---------|-------------|
| DEO (Jharkhand) | PE-FRM-WHT-40 | Peter England | **owned** | 15 | ₹850 | ₹12,750 |
| DEO (Jharkhand) | PE-CHK-BLU-42 | Peter England | **owned** | 15 | ₹780 | ₹11,700 |
| BANKA (Bihar) | BB-BLAZ-NVY-40 | Blackberrys | **owned** | 15 | ₹2,400 | ₹36,000 |
| BANKA (Bihar) | BB-TROU-GRY-34 | Blackberrys | **owned** | 15 | ₹1,100 | ₹16,500 |
| DEO (Jharkhand) | LP-POLO-BLK-L | Louis Philippe | **brand_owned (SOR)** | 15 | ₹1,400 | ₹21,000 |
| DEO (Jharkhand) | LP-SLIM-WHT-38 | Louis Philippe | **brand_owned (SOR)** | 15 | ₹1,800 | ₹27,000 |

**Total seeded**: 90 units, ₹1,24,950

## 3. GL Leg Snapshots — Owned vs Brand-Owned RTV

### Owned RTV (26-27/DEO/RTV/2) — Peter England
```
VENDOR_PAYABLE       DR  Rs    3,260.00   ← reduces what we owe the vendor
INVENTORY            CR  Rs    3,260.00   ← reduces our stock value
Balance: 0 (✓ balanced)
```

### Brand-Owned (SOR) RTV (26-27/DEO/RTV/3) — Louis Philippe
```
NO GL ENTRIES
(correct: SOR stock is off-book; brand owns the value, only stock movement recorded)
```

## 4. Post-Seed Verification

### `/api/stockledger/on-hand` (after 2 owned RTVs + 1 SOR RTV)
```
Total units: 77 | Value: Rs 1,15,290.00
  BANKA  BB-TROU-GRY-34       Blackberrys          qty= 15  Rs 16,500
  BANKA  BB-BLAZ-NVY-40       Blackberrys          qty= 15  Rs 36,000
  DEO    LP-SLIM-WHT-38       Louis Philippe       qty= 13  Rs 23,400
  DEO    LP-POLO-BLK-L        Louis Philippe       qty= 13  Rs 18,200
  DEO    PE-CHK-BLU-42        Peter England        qty= 11  Rs 10,140
  DEO    PE-FRM-WHT-40        Peter England        qty= 10  Rs 11,050
```

### `/api/finledger/health`
```
balanced: True
trial_balance: Rs 0.00
legs: 8, vouchers: 4
assets: Rs 1,21,690  (INVENTORY: 73,690 + SOR_STOCK: 48,000)
liabilities: Rs 1,21,690  (VENDOR_PAYABLE: -73,690 + SOR_CONTRA: -48,000)
```

## 5. Test Suite
- **Before**: 231 passed, 63 skipped, 0 failures
- **After**: 231 passed, 63 skipped, 0 failures (no regression)

## 6. Fixture Code Changes
- No changes to existing test fixtures
- Backend tests continue to seed their own stock in isolation via `conftest.py`
