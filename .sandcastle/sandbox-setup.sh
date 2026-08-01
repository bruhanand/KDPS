#!/usr/bin/env bash
# Bring a Sandcastle container to the point where the pipeline's agents can
# build, run touched tests, and QA in a browser.
#
# Runs as the sandbox's `onSandboxReady` hook, once per sandbox, against the
# freshly-created worktree (which is main plus nothing). Everything here is
# idempotent, so re-running it is safe.
#
# Note the full acceptance gate (`npm run ci`) is deliberately NEVER run
# during the build — the pipeline's ci-check phase runs `npm run ci:fast`
# after QA, and the host re-runs it on merged main before anything counts as
# landed. The dependencies below exist so the builder can run the tests it
# touched, so ci-check can run the fast gate, and so the QA phase can boot
# the API + frontend and drive them in headless Chromium.
#
#   1. Postgres is up      — the kernel's append-only/FSM guarantees are DB
#                            triggers, so pytest on anything else is theatre.
#   2. Backend deps synced — pytest + mypy come from app/backend's dev group.
#   3. Frontend deps synced — tsc + vitest live in app/frontend, via yarn.
#   4. Playwright MCP registered — the QA agent's browser tools.
#
# Fails loudly. A sandbox that can't verify its own work is worse than no sandbox.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
say() { printf '\033[1;34m[sandbox-setup]\033[0m %s\n' "$*"; }

# --- 0. Pre-trust the workspace for the Claude Code CLI -----------------------
# The repo ships a tracked .claude/settings.local.json with permissions.allow
# entries. On its FIRST invocation in a fresh sandbox the CLI treats the
# untrusted workspace leniently (prints "Ignoring N permissions.allow entries"
# and proceeds), but it records the project as untrusted in ~/.claude.json — so
# the SECOND invocation in the same sandbox (the reviewer, sharing the
# implementer's sandbox) hits a *fatal* trust gate and exits 1 before producing
# any output. Sandcastle already runs the agent with --dangerously-skip-permissions,
# so the allow-list is dead weight here; we just need the workspace marked
# trusted so every phase runs. The CLI merges (not clobbers) ~/.claude.json, so
# seeding the flag before the first run survives into later phases.
say "Trusting workspace for the Claude Code CLI"
CJSON="$HOME/.claude.json"
if [ -f "$CJSON" ]; then
  jq '.projects["/home/agent/workspace"].hasTrustDialogAccepted = true' "$CJSON" > "$CJSON.tmp" \
    && mv "$CJSON.tmp" "$CJSON"
else
  printf '{"projects":{"/home/agent/workspace":{"hasTrustDialogAccepted":true}}}' > "$CJSON"
fi

# --- 0b. Playwright MCP for the browser-QA phase ------------------------------
# User-scoped (written to ~/.claude.json) so no per-project approval gate gets
# in the way. Pointed at Debian's chromium from the image; --no-sandbox because
# Chromium's own sandbox cannot start in this rootless container, which is fine
# — the whole container is the sandbox.
say "Registering Playwright MCP (headless Chromium)"
claude mcp remove --scope user playwright >/dev/null 2>&1 || true
claude mcp add --scope user playwright -- playwright-mcp \
  --browser chromium --executable-path /usr/bin/chromium \
  --headless --no-sandbox

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

# --- 4. Code graph (graphify) -------------------------------------------------
# The slicer and the reviewers spend most of their time answering "where does
# this live and what touches it". On the #229 run the slicer ran 104 shell
# commands — nearly all of them greps — to find one function. A graph answers
# that in one call.
#
# `graphify update` is AST-only: deterministic, no LLM, no API key, ~10s over
# app/. It is pointed at app/ and not the repo root deliberately — the root
# would pull in the whole docs corpus, and markdown needs semantic (LLM)
# extraction, which does not belong in an unattended shell script. The corpus
# stays the slicer's job to read; the graph is for code.
#
# Built from inside app/ deliberately: graphify writes graphify-out/ relative to
# the working directory as well as the target, so building from the repo root
# leaves a second, half-populated graphify-out/ there that shadows the real one.
# From app/, the graph is at app/graphify-out/ and graphify's own default path
# resolves — which is why the prompts tell agents to `cd app` first.
say "Building the code graph (graphify)"
# The image ships graphify; this is the fallback for a stale image (the running
# one predated `uv tool install pre-commit` by weeks). Idempotent either way.
command -v graphify >/dev/null 2>&1 || uv tool install graphifyy
cd "$ROOT/app"
graphify update .

say "Ready — pipeline agents can build, test and QA from $ROOT"
