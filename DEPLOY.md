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

## What a re-seed does and does not overwrite

`seed_foundation` runs on every deploy and is safe to re-run by hand.
It upserts roles, masters and demo users, so a fresh row appears and an existing one is brought back in line with the seed.

Two things a live operator owns are deliberately left alone:

- **A user's password.** Set only when the account is first created, so an operator-changed password survives every redeploy.
- **A role's access grid** (`Role.section_access` — what the Setup → Access screen edits, applied by two administrators with an audit row behind it).
  The seed is **additive only** here: it grants a section the role does not have a cell for yet, and it never changes a cell the role already has.
  So an approved access change survives a redeploy, and a section added in a later release still reaches roles seeded before it existed.
  If the ratified access sheet itself changes, that arrives as a migration carrying the new cells — never as a silent re-seed of everything.

Everything else on a role **is** overwritten back to the seed, including its name, description, landing page and sidebar nav groups.
If you retune one of those on a live server, expect the next deploy to put it back.

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

## Mail (each person's Google Workspace inbox, in the top bar)

Mail stays **switched off** until these four variables exist.
The Mail button does not appear in the top bar at all without them, so a half-configured server shows nothing rather than a button that fails.

| Variable | What it is |
|---|---|
| `GOOGLE_OAUTH_CLIENT_ID` | From the Google Cloud console, below. |
| `GOOGLE_OAUTH_CLIENT_SECRET` | Same place. |
| `GOOGLE_OAUTH_REDIRECT_URI` | `https://<api-host>/api/mail/callback` - must match the console **exactly**, including the scheme and any trailing path. |
| `KDPS_MAIL_TOKEN_KEY` | Encrypts stored Google refresh tokens. Generate with `openssl rand -base64 32`. |

Two optional ones.
`MAIL_FRONTEND_URL` is where the browser is sent back after consent (defaults to `/`).

`GOOGLE_WORKSPACE_DOMAIN` (e.g. `kdps.in`) is optional but **should be set on any real deployment**.
Setting it does two things: it narrows Google's account picker to the KDPS domain, and - the part that matters - it makes the server *refuse* any mailbox outside that domain when the consent comes back.
Leave it unset and a personal Gmail can be attached, which is a private inbox sitting in the company's database.



### Registering the OAuth client - the one setting that costs money if you get it wrong

In the Google Cloud console, create an OAuth client for the KDPS Workspace project and set **User type = Internal**.

This is not a preference.
Reading mail needs a *restricted* scope, and a **public** app asking for one must pass a Google-approved CASA Tier 2 security audit, repeated **every twelve months** at a quoted $500 to $75,000 a year.
Google exempts **internal** apps - those usable only by people in your own Workspace organisation - from that assessment entirely.

An External registration behaves identically all the way through testing and then hits that wall at go-live.
If somebody ever sees a Google "unverified app" warning, the client was registered wrong.

Scope requested: `gmail.modify` (read, plus mark-as-read and send).
Deliberately **not** `mail.google.com`, which would also permit deleting a mailbox.

### What this does and does not do

Mail is a **cache, not a book of record**. It writes no ledger and no document; the mailbox lives at Google and these tables can be dropped and refilled at any time.
Each person connects their own account and sees only their own inbox - the only KDPS read that scopes by *person* rather than by store.

Sync runs **when somebody opens the app**, not on a timer (there is no worker or Redis here yet).
The practical consequence: the unread badge is as fresh as the last time that person had KDPS open, so a mail arriving overnight is counted in the morning rather than at 3am.
When a scheduler exists, `python manage.py sync_mail` is already the whole job and can go on a cron beside `check_alerts`.

## Not done yet (before real use)

- Cloud CI (`.github/workflows/ci.yml`) gates only **pytest + the frontend build**; `ruff` / `mypy` strict / `import-linter` run only in pre-commit + local `npm run ci` (not in the cloud), so this alpha carries ~54 `ruff` findings + un-run `mypy` strict. Green cloud CI ≠ green `npm run ci`.
- Production hardening: refresh tokens still in `localStorage`; review HTTPS /
  secure-cookie posture; rotate the demo passwords.
- The money slices and GST CA-rulings are still pending — this alpha is for
  click-through feedback, not live transactions.
