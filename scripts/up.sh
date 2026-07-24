#!/usr/bin/env bash
# KDPS local stack in ONE command — the whole thing, from a cold checkout.
#
#   ./scripts/up.sh          start everything, then open http://localhost:3000
#   ./scripts/up.sh --down   stop and remove the Docker containers (DB data kept)
#   ./scripts/up.sh --reset  wipe the local database, then start fresh
#
# Architecture (as decided): backend + PostgreSQL run in Docker, the React PWA
# runs on the host. docker-compose.yml already migrates + seeds the demo data on
# boot, so there is nothing else to set up. Idempotent — safe to re-run.
#
# Nothing here touches Render. That is a separate thing: merge into
# `client-testing` and Render auto-deploys the client alpha.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
FRONTEND="$ROOT/app/frontend"
COMPOSE=(docker compose -f "$ROOT/docker-compose.yml")

say() { printf '\033[1;34m==>\033[0m %s\n' "$*"; }
die() { printf '\033[1;31mfail\033[0m %s\n' "$*" >&2; exit 1; }

case "${1:-}" in
  --down)  "${COMPOSE[@]}" down;    say "Stopped. Database volume kept — use --reset to wipe it."; exit 0 ;;
  --reset) "${COMPOSE[@]}" down -v; say "Local database wiped." ;;
  "")      ;;
  *)       die "unknown flag: $1 (use --down or --reset)" ;;
esac

# --- preflight ---------------------------------------------------------------
command -v docker >/dev/null || die "Docker not found — install/start Docker Desktop."
docker info >/dev/null 2>&1  || die "Docker is not running — start Docker Desktop."
command -v yarn   >/dev/null || die "yarn not found (the PWA uses it) — install: npm i -g yarn"

# --- 1. backend + database in Docker -----------------------------------------
# --build so the API image always reflects the code you currently have checked
# out. The compose `api` command runs migrate + seed_foundation on start.
say "Backend + Postgres (Docker) — building & starting"
"${COMPOSE[@]}" up -d --build db api

printf '    waiting for the API on http://localhost:8001 '
for _ in $(seq 1 90); do
  if curl -sf http://localhost:8001/api/health >/dev/null 2>&1; then printf ' ok\n'; ready=1; break; fi
  printf '.'; sleep 2
done
[ "${ready:-}" = 1 ] || die "API did not come up. Check its logs: docker compose logs api"

# --- 2. frontend on the host -------------------------------------------------
# Install the SAME way CI does (yarn, frozen lockfile) so nothing rewrites
# yarn.lock. Always install — a stale node_modules after a branch switch fails
# silently; yarn is a fast no-op when already satisfied.
say "PWA dependencies (yarn)"
(cd "$FRONTEND" && yarn install --frozen-lockfile --silent)

# --- 3. run the PWA ----------------------------------------------------------
# VITE_LOCAL_DEV=1 disables the old Emergent HTTPS-proxy HMR port so hot reload
# works on a plain-http localhost. Ctrl-C stops the PWA; the Docker backend + DB
# keep running (stop them with: ./scripts/up.sh --down).
say "PWA → http://localhost:3000   (login: owner / Owner@123 — see memory/test_credentials.md)"
say "Backend + DB stay up after Ctrl-C. Stop them with: ./scripts/up.sh --down"
cd "$FRONTEND" && VITE_LOCAL_DEV=1 exec yarn dev
