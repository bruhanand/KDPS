# Deploying KDPS to Render (alpha / demo)

The repo ships a Render Blueprint (`render.yaml`) that provisions the whole
stack: **PostgreSQL 16**, the **Django API**, and the **React PWA**. This is an
alpha/demo setup — not hardened for production money handling yet.

## What you get

| Service | Type | URL (if names are free) |
|---|---|---|
| `kdps-db` | PostgreSQL 16 | internal |
| `kdps-erp-api` | Django API (uvicorn) | `https://kdps-erp-api.onrender.com` |
| `kdps-erp-web` | React static site | `https://kdps-erp-web.onrender.com` |

## Steps

1. **Create a Render account** at https://render.com and connect your GitHub
   (`bruhanand/KDPS`). Grant access to the repo.
2. **New → Blueprint.** Pick the `KDPS` repo and the `main` branch. Render reads
   `render.yaml` and shows the 3 resources. Click **Apply**.
3. Render generates `DJANGO_SECRET_KEY`, provisions Postgres, wires
   `DATABASE_URL`, runs migrations, and seeds demo data automatically.
4. **First-deploy URL check (the one manual bit).** After the services exist,
   open each and confirm the hostname. If they are **not** exactly
   `kdps-erp-api` / `kdps-erp-web` (because someone already took that subdomain),
   fix these and redeploy:
   - On `kdps-erp-web` → Environment → set `REACT_APP_BACKEND_URL` to the real
     API URL, then **Clear build cache & deploy** (it's inlined at build time).
   - On `kdps-erp-api` → Environment → set `CORS_ALLOWED_ORIGINS` and
     `CSRF_TRUSTED_ORIGINS` to the real web URL, then save (auto-redeploys).
5. **Open the web URL and log in** with a seeded account.

## Seeded logins (demo — change before production)

| Username | Password | Role |
|---|---|---|
| `owner` | `Owner@123` | Owner / Director |
| `admin` | `Admin@123` | IT Admin |
| `accounts1` | `Acct@123` | Accountant (Patna) |
| `wh.patna` | `Wh@123` | Warehouse |
| `deo.manager` | `Store@123` | Store Manager (Deoghar) |

## Things to know (free tier)

- **Free Postgres is deleted after 30 days.** For anything beyond a short demo,
  upgrade `kdps-db` to a paid plan to keep data.
- **Free web services sleep when idle** — the first request after idle takes
  ~50s to wake. Upgrade the API instance to avoid cold starts.
- Region is set to **Singapore** (closest Render region to India). True
  in-India data residency would need DigitalOcean Bangalore / AWS Mumbai / Fly
  Mumbai instead.

## Not done yet (before real use)

- 54 `ruff` lint findings + `mypy` strict not run in CI on this export.
- Production hardening: refresh tokens still in `localStorage`; review HTTPS /
  secure-cookie posture; rotate the demo passwords.
- The money slices and GST CA-rulings are still pending — this alpha is for
  click-through feedback, not live transactions.
