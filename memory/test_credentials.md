# KDPS Test Credentials & Seed Data

## Login Accounts

| Username | Password | Role | Scope |
|----------|----------|------|-------|
| `admin` | `Admin@123` | Superuser | All stores |
| `owner` | `Owner@123` | Owner | All stores |
| `sm_de0` | `Sm@12345` | Store Manager | DEO (Deoghar) |
| `cashier_de0` | `Cash@123` | Store Staff | DEO (Deoghar) |
| `ho_ops` | `Ops@12345` | HO Ops | All stores |

`admin` is the Django superuser (also reaches `/admin`).

## Demo Stock Seed

Run: `python manage.py seed_outbound_demo` (idempotent, safe to re-run).

### Seeded SKUs (post-seed, before any outbound operations)

| Store | SKU Code | Brand | Ownership | Qty | Cost/pc (paise) | Item |
|-------|----------|-------|-----------|-----|-----------------|------|
| DEO | PE-FRM-WHT-40 | Peter England | owned | 15 | 85000 | Formal Shirt |
| DEO | PE-CHK-BLU-42 | Peter England | owned | 15 | 78000 | Check Casual Shirt |
| BANKA | BB-BLAZ-NVY-40 | Blackberrys | owned | 15 | 240000 | Slim Blazer |
| BANKA | BB-TROU-GRY-34 | Blackberrys | owned | 15 | 110000 | Formal Trouser |
| DEO | LP-POLO-BLK-L | Louis Philippe | brand_owned (SOR) | 15 | 140000 | Classic Polo |
| DEO | LP-SLIM-WHT-38 | Louis Philippe | brand_owned (SOR) | 15 | 180000 | Slim Fit Shirt |

### Stores for Cross-State Testing

| Store | Code | State | GSTIN |
|-------|------|-------|-------|
| Deoghar | DEO | Jharkhand | 20AAACK1234M1Z3 |
| Banka | BANKA | Bihar | 10AAACK1234M1Z5 |
| Bokaro | BKR | Jharkhand | 20AAACK1234M1Z3 |

DEO ↔ BANKA = cross-state (different GSTINs). DEO ↔ BKR = same state.

### Vendor/Brand IDs

| Brand | ID | Ownership | Vendor |
|-------|----|-----------|--------|
| Peter England | 4 | owned | Aditya Birla Fashion (abfrl, ID=1) |
| Blackberrys | 6 | owned | Blackberrys Menswear (blackberrys, ID=4) |
| Louis Philippe | 1 | brand_owned | Aditya Birla Fashion (abfrl, ID=1) |
| Van Heusen | 2 | brand_owned | Aditya Birla Fashion (abfrl, ID=1) |
| Allen Solly | 3 | brand_owned | Aditya Birla Fashion (abfrl, ID=1) |
| U.S. Polo Assn. | 8 | brand_owned | Arvind Fashions (arvind, ID=2) |

### VoucherSeries (Outbound)
All stores have series for doc types: STO, RTV, ADJ, WRO, VFL (created by seed command).
