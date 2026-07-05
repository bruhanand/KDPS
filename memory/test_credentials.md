# KDPS — Test Credentials

Foundation demo logins (seeded by `python manage.py seed_foundation`).

## Demo Users

| Username | Password | Role | Scope | Description |
|----------|----------|------|-------|-------------|
| `admin` | `Admin@123` | IT Admin | All (network-wide) | Full system access, user management |
| `owner` | `Owner@123` | Owner / Director | All (network-wide) | Dashboards, approvals, sign-offs |
| `ops1` | `Ops@123` | HO Operations | All (network-wide) | Head office operations |
| `accounts1` | `Acct@123` | Accounts / Finance | All (network-wide) | Financial ledgers, payments, books health |
| `wh.patna` | `Wh@123` | Warehouse | All (network-wide) | Warehouse operations, PT mapping |
| `steward` | `Steward@123` | Data Steward | All (network-wide) | Master data management |
| `deo.manager` | `Store@123` | Store Manager | Store (DEO) | Store-scoped operations, Deoghar store |
| `deo.cashier` | `Store@123` | Store Cashier | Store (DEO) | Store-scoped cashier, Deoghar store |

## Auth Method
- **JWT (Bearer token)**: POST `/api/auth/login` with `{"username": "...", "password": "..."}` → returns `{access, refresh, user}`
- **Cookie auth**: Login also sets HttpOnly `access_token` and `refresh_token` cookies
- Frontend stores tokens in localStorage (`kdps_access`, `kdps_refresh`)

## API URL Convention
- **No trailing slashes**: `/api/masters/stores` (NOT `/api/masters/stores/`)
- Trailing slash requests return 404

## Stores in Seed
- DEO (Deoghar) — Jharkhand, GSTIN 20...
- BKR (Bokaro) — Jharkhand
- HZB (Hazaribagh) — Jharkhand
- DUM (Dumka) — Jharkhand
- BANKA — Bihar, GSTIN 10...
- RAN-WH (Ranchi Central Warehouse) — Jharkhand
- ZZTESTC50DC9 — Test store, Bihar
- ZZTESTEC0F63 — Test store, Bihar
