# KDPS Operating System

A deterministic retail ERP for KDPS Lifestyle Pvt Ltd. Monorepo:

- `app/backend` — Django: kernel `core` + 9 domain apps (masters, accounts, files, vendors, inbound, ptmapper, stockledger, finledger, aiagents), Python 3.12 via `uv`.
- `app/frontend` — React + TypeScript PWA (Vite): ~12 wired screens + stubs.

**Status (2 Jul 2026):** the foundation + first business layer are built, merged to `main`, and auto-deploy to a **Render alpha** — see `DEPLOY.md`. Build history + current state: `memory/PRD.md`; domain/kernel contracts: `CONTEXT.md`.

The design corpus lives in `docs/my-understanding/system-design/`. The build
process is `docs/my-understanding/system-design/build-operating-manual.html`.

## Prerequisites

- Node 22, Python 3.12, [uv](https://docs.astral.sh/uv/), and **either** Docker
  **or** a local PostgreSQL 16.

## 0 · Just run it

```bash
npm run dev       # Postgres + Django API (:8001) + React PWA (:3000). Ctrl-C stops it.
```

One command, from a cold checkout: starts the Docker Postgres, installs
dependencies, migrates, seeds demo data, and runs both servers. Idempotent —
re-run it any time. Open **http://localhost:3000** and sign in with a login from
`memory/test_credentials.md` (e.g. `owner` / `Owner@123`).

```bash
npm run dev:setup   # provision DB + deps + seed, start no servers
npm run dev:reset   # destroy the local database and rebuild it from scratch (~11s), then exit
./scripts/dev.sh --api    # API only          --web   PWA only
./scripts/dev.sh --reset  # rebuild the database AND run the stack
```

**No secrets needed.** `scripts/dev.sh` generates `app/backend/.env` on first run.
Nothing from Render is required, and Render's values would actively break local dev
(remote DB, `.onrender.com` hosts, `JWT_COOKIE_SECURE=1` — which silently drops the
login cookie over plain http). The one real secret, `EMERGENT_LLM_KEY` (the Gemini
invoice reader), is inert here: `aiagents` is not in `INSTALLED_APPS`.

**Local database only.** The script refuses a non-localhost `DATABASE_URL`. It runs
`migrate`, seeds, and its sibling gate creates and *drops* databases — none of which
should ever be one typo away from the alpha's books. Use the Render dashboard for
that (`DEPLOY.md`).

### The shared database

**Every checkout on this machine uses the same Postgres.** The Docker volume in
`docker-compose.yml` is named, not per-worktree, so a second workspace - another
branch, another agent, another Conductor worktree - migrates and seeds the very
same `kdps_dev`. Whichever branch ran `migrate` last is the schema everybody has.

That is fine most of the time and occasionally poisonous. Switching to a branch
whose migrations are a subset of what the database already carries leaves columns
in place that the branch knows nothing about, and a `migrate` on a branch that has
since dropped a migration leaves a history row pointing at a file that no longer
exists. Both used to surface as an unexplained 500 at insert time (issue #93).

Two things now catch it:

```bash
cd app/backend && uv run python manage.py check_db_drift
```

names any table and column where the database and the migration graph disagree -
it runs as part of `npm run ci`, so drift stops the gate instead of a slice.
And the live-API suites ask the server on `:8001` which migrations it carries; if
that disagrees with your working tree, they **skip** and say so rather than
testing a server you are not editing.

The cure is always the same, and it is yours to run, never a test's:

```bash
npm run dev:reset   # destroy the local database and rebuild it from scratch (~11s)
npm run dev         # migrate, seed, and start the stack from *this* working tree
```

It destroys the data every workspace on the machine shares, so check that nobody
else is mid-run first. Nothing in the test suite will ever do it for you.

**There is no API container.** The only local API is the one `scripts/dev.sh`
starts from the working tree you are editing. A containerised one used to answer
on `:8001`; it silently outlived the code it was built from and served pre-#85
code against a migrated schema for weeks. It was retired in #93 - if something
answers on `:8001` that you did not start, that is the bug.

Sections 1–3 below are the manual equivalent, and what the gate needs.

## 1 · Install dependencies

```bash
npm run setup     # uv sync (backend) + npm install (frontend)
```

## 2 · Get a database

`npm run ci` runs the tests against **real PostgreSQL** — SQLite is rejected on
purpose (the kernel's append-only / isolation invariants are vacuous on SQLite).
Pick one path:

**A · Docker — reproducible on a clean machine (recommended)**

```bash
docker compose up -d db
export DATABASE_URL=postgres://kdps:kdps@localhost:55432/kdps_dev
```

**B · Local Postgres (e.g. Homebrew)**

```bash
createdb kdps_dev
# default DATABASE_URL = postgres://localhost:5432/kdps_dev — no export needed
```

## 3 · Run the gate

```bash
npm run ci        # ruff · mypy (strict) · migration check · schema-drift check · import-linter · pytest · tsc
```

The **schema-drift check** compares the database against the migration graph and
fails naming the offending table and column - see "The shared database" above.
`makemigrations --check`, right beside it, answers the different question of
*models vs migrations*, and stays green while the database is drifted; that gap is
why the two run together.

The ~57 **live-API suites** in `app/backend/tests` drive a real server over HTTP.
They skip unless one answers at `REACT_APP_BACKEND_URL` - so `npm run ci` on its
own is green with those 57 not run at all. To run them, start the stack from this
checkout (`npm run dev`, or `./scripts/dev.sh --api`) and run the gate beside it.

All green = the build is sound. `npm run ci` is the **local acceptance gate for every slice**.

**Two gates, not one.** The cloud CI (`.github/workflows/ci.yml`) runs only **pytest** (kernel anti-cheat + API regression, on real Postgres) **+ the frontend build** — *not* ruff / mypy strict / import-linter (those run in pre-commit and local `npm run ci`). So a green cloud run is **not** a green `npm run ci`: the deployed **Render alpha** currently carries ~54 ruff findings + un-gated mypy strict. Deploy steps + seeded logins: `DEPLOY.md`.
