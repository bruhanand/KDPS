# KDPS Operating System

A deterministic retail ERP for KDPS Lifestyle Pvt Ltd. Monorepo:

- `app/backend` — Django kernel (`core`), Python 3.12 via `uv`.
- `app/frontend` — React + TypeScript PWA shell (Vite).

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

All green = the build is sound. This is the acceptance gate for every slice.
