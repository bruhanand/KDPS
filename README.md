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
export DATABASE_URL=postgres://kdps:kdps@localhost:5433/kdps_dev
```

**B · Local Postgres (e.g. Homebrew)**

```bash
createdb kdps_dev
# default DATABASE_URL = postgres://localhost:5432/kdps_dev — no export needed
```

## 3 · Run the gate

```bash
npm run ci        # ruff · mypy (strict) · migration check · import-linter · pytest · tsc
```

All green = the build is sound. `npm run ci` is the **local acceptance gate for every slice**.

**Two gates, not one.** The cloud CI (`.github/workflows/ci.yml`) runs only **pytest** (kernel anti-cheat + API regression, on real Postgres) **+ the frontend build** — *not* ruff / mypy strict / import-linter (those run in pre-commit and local `npm run ci`). So a green cloud run is **not** a green `npm run ci`: the deployed **Render alpha** currently carries ~54 ruff findings + un-gated mypy strict. Deploy steps + seeded logins: `DEPLOY.md`.
