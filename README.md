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
npm run dev       # Postgres + Django API + React PWA. Ctrl-C stops it.
```

One command, from a cold checkout: starts this workspace's Docker Postgres,
installs dependencies, migrates, seeds demo data, and runs both servers.
Idempotent — re-run it any time. It prints the URLs it chose; open the PWA one and
sign in with a login from `memory/test_credentials.md` (e.g. `owner` / `Owner@123`).

**Building the environment and starting the app are two different jobs.**
`npm run dev:setup` is the slow one and runs once — in Conductor it is the setup
hook, fired when the workspace is created: Postgres container, dependencies,
schema, seed data.
`npm run dev` is the fast one and runs constantly — it checks the database is up
and the schema current (a rebase adds migrations, a reboot stops the container),
then starts the two servers.
The two are safe to overlap: both take a per-workspace provisioning lock, so
pressing Run while setup is still going makes Run *wait* rather than collide with
it. It used to collide, and Docker's answer to two `compose up` calls on one
project is `Conflict. The container name ... is already in use`.

**The ports are per workspace.** Every Conductor workspace gets its own database
and its own three ports, so `:3000` / `:8001` are only the fallback outside
Conductor — see "One database per workspace" below, and run `npm run dev:where` to
see this workspace's.

```bash
npm run dev:where   # this workspace's compose project, ports and database URL
npm run dev:setup   # provision DB + deps + seed, start no servers
npm run dev:reset   # destroy this workspace's database and rebuild it (~11s), then exit
npm run dev:down    # stop this workspace's Postgres (its data is kept)
npm run dev:stop    # stop this workspace's servers (Postgres stays up)
./scripts/dev.sh --api    # API only          --web   PWA only
./scripts/dev.sh --reset  # rebuild the database AND run the stack
./scripts/dev.sh --seed   # re-seed demo data on the way up
```

**Leftovers from deleted workspaces.** Archiving a workspace now stops its
servers before deleting its database. If you have older ones still running — a
Django API on a recycled port, talking to a database that no longer exists, which
is enough to stop a *new* workspace from starting — clear them all at once:

```bash
./scripts/stop-stack.sh --stale   # stop every stack whose workspace directory is gone
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

### One database per workspace

**Every Conductor workspace runs its own system.** Its own Postgres container, its
own volume, its own database, and its own three host ports - so two workspaces can
run the stack, the seeds and the live-API suites at the same time and neither can
migrate, seed or drop the other's data. Nothing is shared.

`scripts/workspace-env.sh` is the single place that decides which stack you are.
Conductor gives each workspace a block of ten ports; the script spends three of
them and names the Compose project after the stable worktree directory. Retitling
a Conductor workspace therefore cannot orphan a database project:

| | |
|---|---|
| Compose project | `kdps-<worktree>` (volume `kdps-<worktree>_kdps_pgdata`) |
| React PWA | `CONDUCTOR_PORT` |
| Django API | `CONDUCTOR_PORT + 1` |
| Postgres | `CONDUCTOR_PORT + 2` |

Outside Conductor - a plain clone, the root checkout, CI - there is no allocation
to honour, so it falls back to the historic fixed `3000` / `8001` / `55432` and
behaves exactly as it always has.

```bash
npm run dev:where   # which project, which ports, which database — this workspace
```

**The database lives exactly as long as the workspace does.** Creating a workspace
provisions it (`setup` in `.conductor/settings.toml`); archiving the workspace runs
`docker compose -p kdps-<worktree> down -v`, which destroys the container *and*
the volume. Archive is the delete.

`app/backend/.env` carries this workspace's `DATABASE_URL`, and `scripts/dev.sh`
rewrites that one key on every run. It has to: Conductor copies the root
checkout's `.env` into each new workspace, so a fresh workspace is born holding
another workspace's port. For the same reason `config/settings.py` loads the file
with `override=True` - the worktree's `.env` beats anything already in the
environment, because an inherited `DATABASE_URL` is a silent wrong-database bug.
Do not put a `DATABASE_URL` in `[environment_variables]` in
`.conductor/settings.toml`: TOML values are static, so one written there pins every
workspace to a single database, which is the arrangement this replaced.

Schema drift is now only ever your own, from an earlier branch of this same
worktree. Two things still catch it:

```bash
cd app/backend && uv run python manage.py check_db_drift
```

names any table and column where the database and the migration graph disagree -
it runs as part of `npm run ci`, so drift stops the gate instead of a slice.
And the live-API suites ask the server which migrations it carries; if that
disagrees with your working tree, they **skip** and say so rather than testing a
server you are not editing.

The cure is the same as ever, and it is yours to run, never a test's:

```bash
npm run dev:reset   # destroy THIS workspace's database and rebuild it (~11s)
npm run dev         # migrate, seed, and start the stack from *this* working tree
npm run dev:down    # stop this workspace's Postgres, keep its data
```

`dev:reset` now destroys only your own workspace's data - no need to check whether
anyone else is mid-run. Nothing in the test suite will ever do it for you.

**There is no API container.** The only local API is the one `scripts/dev.sh`
starts from the working tree you are editing. A containerised one used to answer
on `:8001`; it silently outlived the code it was built from and served pre-#85
code against a migrated schema for weeks. It was retired in #93 - if something
answers on this workspace's API port that you did not start, that is the bug.

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
npm run dev:setup       # this workspace's Postgres + deps + migrate + seed
```

Use this rather than a bare `docker compose up -d db`. Without `-p` Compose names
the project after the *directory* and publishes the fixed fallback port, which is
how two workspaces used to collide; `dev.sh` sources `scripts/workspace-env.sh`
first and passes the right project name and port. It also writes this workspace's
`DATABASE_URL` into `app/backend/.env`, which is what Django reads — exporting the
variable by hand no longer overrides that file (see above).

**B · Local Postgres (e.g. Homebrew)**

```bash
createdb kdps_dev
# default DATABASE_URL = postgres://localhost:5432/kdps_dev — no export needed
```

## 3 · Run the gate

```bash
npm run ci        # ruff · mypy (strict) · migration check · schema-drift check · import-linter · pytest · API-client drift · tsc
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

## 4 · Regenerate the API client

The PWA does not describe the API by hand.
`drf-spectacular` turns Django into an OpenAPI document and `openapi-typescript` turns that into `app/frontend/src/lib/api-schema.ts`, which is what makes `tsc` fail when a screen and the API stop agreeing (ADR-0001 / ADR-0002).

```bash
npm run api:client        # rewrite app/frontend/src/lib/api-schema.ts
npm run ci:api-client     # fail if the committed file is stale (runs inside npm run ci)
```

**Change a serializer, a view or a URL, and run `npm run api:client` in the same commit.**
That file is generated, never hand-edited.
It needs no database and no running server: the generator reads the URL conf and the serializers, never a row, so it works on a cold checkout.

Both cloud CI and the local gate refuse a difference.
That gate is the point: without it the file drifted about a thousand lines behind the backend, screens hand-wrote the shapes they expected, and the safety net was gone while everything still looked green (#192).

It is not yet a *complete* net, and the command says so on every run.
`drf-spectacular` cannot work out what a plain `APIView` answers, so 133 of the 224 published operations describe only that they exist - screens still hand-write those shapes, and nothing can check them (#303).

**Two gates, one shape.** The cloud CI (`.github/workflows/ci.yml`) covers what the local gate covers: ruff (format + check), `mypy .`, import-linter, `makemigrations --check`, the schema-drift check, the kernel suites, the API regression suites sharded eight ways on real Postgres, the API-client drift check, and the frontend build + vitest.
The one thing it cannot reproduce is *your* database: its Postgres is built fresh from the migration graph every run, so `check_db_drift` there is trivially green and only the local run answers whether your own workspace has drifted.
Deploy steps + seeded logins: `DEPLOY.md`.
