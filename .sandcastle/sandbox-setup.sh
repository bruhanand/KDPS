#!/usr/bin/env bash
# Bring a Sandcastle container to the point where `npm run ci` can actually run.
#
# Runs as the sandbox's `onSandboxReady` hook, once per sandbox, against the
# freshly-created worktree (which is main plus nothing). Everything here is
# idempotent, so re-running it is safe.
#
# Three things have to be true before the acceptance gate means anything:
#   1. Postgres is up      — the kernel's append-only/FSM guarantees are DB
#                            triggers, so pytest on anything else is theatre.
#   2. Backend deps synced — ruff, mypy, import-linter and pytest all come from
#                            app/backend's dev group via uv.
#   3. Frontend deps synced — tsc + vitest live in app/frontend, via yarn.
#
# Fails loudly. A sandbox that can't verify its own work is worse than no sandbox.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
say() { printf '\033[1;34m[sandbox-setup]\033[0m %s\n' "$*"; }

# --- 1. Postgres -------------------------------------------------------------
# The cluster was created by the Dockerfile at $PGDATA, owned by `agent`, with a
# /tmp socket dir and trust auth. Start it if this container hasn't already.
say "Starting PostgreSQL"
if pg_ctl --pgdata="$PGDATA" status >/dev/null 2>&1; then
  say "  already running"
else
  pg_ctl --pgdata="$PGDATA" --log=/tmp/postgres.log -w start
fi
psql -h /tmp -U kdps -d kdps_dev -c 'select 1' >/dev/null

# --- 2. Backend --------------------------------------------------------------
# uv resolves into app/backend/.venv. That lives inside the worktree, so it is
# per-branch and never shared with the host checkout.
say "Syncing backend dependencies (uv)"
cd "$ROOT/app/backend"
uv sync

say "Applying migrations"
uv run python manage.py migrate --noinput

# Demo masters, roles and PT-mapper lookups. pytest builds its own test database
# from migrations and ignores this one, so seeding is purely so the agent can
# boot the API and look at real data if it needs to.
say "Seeding foundation + PT mapper"
uv run python manage.py seed_foundation
uv run python manage.py seed_ptmapper

# --- 3. Frontend -------------------------------------------------------------
# yarn, not npm: app/frontend has a yarn.lock and cloud CI runs
# `yarn install --frozen-lockfile`. Using npm here would write a competing
# package-lock.json and drift off the lockfile CI enforces.
say "Syncing frontend dependencies (yarn)"
cd "$ROOT/app/frontend"
yarn install --frozen-lockfile

say "Ready — 'npm run ci' will run from $ROOT"
