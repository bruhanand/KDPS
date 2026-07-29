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
   `DATABASE_URL`, runs `collectstatic` + migrations, and seeds both
   **foundation data** (`seed_foundation` — roles, masters, demo users) and
   **PT-mapper master data** (`seed_ptmapper` — brands/colours/sizes/taxonomy
   lookups) automatically.
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

Created by `seed_foundation` (full list also in `memory/test_credentials.md`).
`admin` is the Django superuser (also reaches `/admin`).

| Username | Password | Role | Scope |
|---|---|---|---|
| `admin` | `Admin@123` | it_admin | all |
| `owner` | `Owner@123` | owner | all |
| `ops1` | `Ops@123` | ho_ops | all |
| `accounts1` | `Acct@123` | accounts | all |
| `wh.patna` | `Wh@123` | warehouse | all |
| `steward` | `Steward@123` | data_steward | all |
| `deo.manager` | `Store@123` | store_manager | store (DEO) |
| `deo.cashier` | `Store@123` | store_staff | store (DEO) |

## Things to know (free tier)

- **Free Postgres is deleted after 30 days.** For anything beyond a short demo,
  upgrade `kdps-db` to a paid plan to keep data.
- **Free web services sleep when idle** — the first request after idle takes
  ~50s to wake. Upgrade the API instance to avoid cold starts.
- Region is set to **Singapore** (closest Render region to India). True
  in-India data residency would need DigitalOcean Bangalore / AWS Mumbai / Fly
  Mumbai instead.

## PT-mapper self-improvement (daily learning loop)

The `render.yaml` includes a **`kdps-ptmap-learn` cron** that runs once a day:

```
python manage.py ptmap_mine            # correction log → staged learning proposals
python manage.py ptmap_learning_report # corrections-per-file KPI + rule precision
```

`ptmap_mine` only *proposes* (Rule 8) — it groups the human corrections on files
that reached Patna (SENT) and stages a `LookupProposal` when a mapping is
well-supported (≥3 corrections across ≥2 files for a brand rule, or ≥2 agreeing
brands for a global one). A **steward** (e.g. the seeded `steward` login) then
approves each proposal in the app (**PT Mapper → Proposals**); only approval writes
a live `Lookup`. Both commands are idempotent and read-mostly, safe to re-run.

> **Free tier:** Render cron jobs need a paid plan. If you keep the stack on free,
> the cron is skipped — run the two commands by hand from the API service **Shell**
> tab (or locally against the same `DATABASE_URL`) whenever you want to fold the
> week's corrections back in. Nothing else depends on the cron.

## Alerts (in-transit aging + return-window 30/15/7)

The `render.yaml` includes a **`kdps-alerts-check` cron** that runs once a day:

```
python manage.py check_alerts   # in-transit aging + return-window checks → alerts table
```

Both thresholds (aging days; the 30/15/7 return-window days) are `AlertPolicy`
rows, retunable in the admin without a release (Rule 12). The command is
idempotent — safe to re-run the same day, or catch up after a missed one — so
on the **free tier**, run it by hand from the API service **Shell** tab (or
locally against the same `DATABASE_URL`) whenever you want alerts current.

## Not done yet (before real use)

- Cloud CI (`.github/workflows/ci.yml`) gates only **pytest + the frontend build**; `ruff` / `mypy` strict / `import-linter` run only in pre-commit + local `npm run ci` (not in the cloud), so this alpha carries ~54 `ruff` findings + un-run `mypy` strict. Green cloud CI ≠ green `npm run ci`.
- Production hardening: refresh tokens still in `localStorage`; review HTTPS /
  secure-cookie posture; rotate the demo passwords.
- The money slices and GST CA-rulings are still pending — this alpha is for
  click-through feedback, not live transactions.
