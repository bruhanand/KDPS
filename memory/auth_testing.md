# KDPS — Authentication Testing Guide

## Auth Architecture
- **Backend**: Django REST Framework + `djangorestframework-simplejwt`
- **Custom class**: `accounts.authentication.CookieOrHeaderJWTAuthentication`
  - Tries `Authorization: Bearer <token>` header first
  - Falls back to `access_token` HttpOnly cookie
- **Session auth**: DRF SessionAuthentication also enabled (for browsable API)

## How to Authenticate

### 1. Login (get tokens)
```bash
curl -X POST http://localhost:8001/api/auth/login \
  -H 'Content-Type: application/json' \
  -d '{"username": "owner", "password": "Owner@123"}'
```
Response:
```json
{
  "access": "eyJ...",
  "refresh": "eyJ...",
  "user": { "id": 2, "username": "owner", "role": {...}, ... }
}
```
Also sets `Set-Cookie: access_token=...; HttpOnly` and `Set-Cookie: refresh_token=...; HttpOnly`.

### 2. Use Bearer Token (header auth)
```bash
curl -H 'Authorization: Bearer <access_token>' http://localhost:8001/api/auth/me
```

### 3. Use Cookie Auth (browser/session)
With a `requests.Session()` or browser, the cookies are sent automatically after login.

### 4. Refresh Token
```bash
curl -X POST http://localhost:8001/api/auth/refresh \
  -H 'Content-Type: application/json' \
  -d '{"refresh": "<refresh_token>"}'
```
Or, if cookies are set, just POST with empty body — the `refresh_token` cookie is read.

### 5. Logout
```bash
curl -X POST http://localhost:8001/api/auth/logout \
  -H 'Authorization: Bearer <access_token>' \
  -H 'Content-Type: application/json' \
  -d '{"refresh": "<refresh_token>"}'
```
Clears auth cookies and blacklists the refresh token.

## Environment Variables
- `JWT_COOKIE_SECURE=0` — Required for local HTTP testing (cookies won't be sent over HTTP if Secure=True)
- `DJANGO_SECRET_KEY` — Used for JWT signing
- `DJANGO_DEBUG=1` — Enables broad CORS for localhost origins

## CORS
- When `DEBUG=True`: Allows `http://localhost:*` and `https://*.emergentagent.com` origins
- `CORS_ALLOW_CREDENTIALS = True` — Cookies/Authorization headers are sent

## Key Endpoints
| Endpoint | Method | Auth | Description |
|----------|--------|------|-------------|
| `/api/auth/login` | POST | None | Login, returns JWT tokens |
| `/api/auth/me` | GET | Required | Current user profile |
| `/api/auth/refresh` | POST | None | Refresh access token |
| `/api/auth/logout` | POST | Required | Logout, blacklist refresh token |
| `/api/auth/admin/roles` | GET/POST | Admin only | Role management |
| `/api/auth/admin/users` | GET/POST | Admin only | User management |
| `/api/schema/` | GET | None | OpenAPI 3.0 schema (YAML) |
| `/api/docs/` | GET | None | Swagger UI |
| `/api/health` | GET | None | Health check |

## Role-Based Access
- **IT Admin / Owner**: Full access to all endpoints including admin routes
- **HO Operations / Warehouse**: Access to documents, inbound, PT mapping
- **Accounts / Finance**: Access to financial ledgers, payments, books health
- **Store Manager / Cashier**: Store-scoped access only (see assigned stores)
- **Data Steward**: Master data management

## Testing Tips
1. Use demo credentials from `test_credentials.md`
2. For bearer auth testing: extract `access` from login response, use in `Authorization: Bearer <token>`
3. For cookie auth testing: use `requests.Session()` — cookies are auto-managed
4. Set `JWT_COOKIE_SECURE=0` when testing over HTTP (not HTTPS)
5. RBAC admin endpoints (`/api/auth/admin/*`) require `owner` or `admin` role
