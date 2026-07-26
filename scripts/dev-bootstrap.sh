#!/usr/bin/env bash
# KDPS dev bootstrap for the Emergent container.
# Idempotent: safe to re-run. Brings up Postgres, deps, DB, migrations, seed.
#
# The dependency step is `uv sync` against `pyproject.toml`, not a hand-listed
# `pip install` into the container's own `/root/.venv`. Two reasons, both learned
# the hard way (26 Jul 2026 review):
#   * that venv is Python 3.11, and the backend uses PEP 695 generics
#     (`def text_filter[QS: QuerySet](...)`) — so it died at import with a
#     SyntaxError in `core/textsearch.py`;
#   * the hand-written package list drifts from `pyproject.toml` the moment
#     anyone adds a dependency.
# So the env is built where `pyproject.toml` says, at the version it says, and
# supervisor's fixed `/root/.venv/bin/uvicorn` command is pointed at it by a
# one-line shim. `/root/.venv` keeps its own tooling; nothing else moves.
set -euo pipefail

BACKEND=/app/app/backend
VENV=/opt/kdpsvenv          # the app's environment, built by uv from pyproject
SERVED=/root/.venv          # what supervisor runs; only its `uvicorn` is shimmed

echo "==> 1. PostgreSQL 15"
if ! command -v pg_lsclusters >/dev/null 2>&1; then
  apt-get update && DEBIAN_FRONTEND=noninteractive apt-get install -y postgresql postgresql-contrib
fi
# Start via supervisor if configured, else directly.
if [ -f /etc/supervisor/conf.d/postgresql.conf ]; then
  supervisorctl reread >/dev/null 2>&1 || true
  supervisorctl update >/dev/null 2>&1 || true
  supervisorctl start postgresql >/dev/null 2>&1 || true
fi
pg_ctlcluster 15 main start 2>/dev/null || true
sleep 2

echo "==> 2. Role + database (kdps / kdps_dev)"
sudo -u postgres psql -tc "SELECT 1 FROM pg_roles WHERE rolname='kdps'" | grep -q 1 \
  || sudo -u postgres psql -c "CREATE ROLE kdps LOGIN SUPERUSER PASSWORD 'kdps';"
sudo -u postgres psql -tc "SELECT 1 FROM pg_database WHERE datname='kdps_dev'" | grep -q 1 \
  || sudo -u postgres createdb -O kdps kdps_dev

echo "==> 3. Backend deps (uv sync → $VENV, Python 3.12)"
command -v uv >/dev/null 2>&1 || { echo "uv is required (https://docs.astral.sh/uv/)"; exit 1; }
cd "$BACKEND"
UV_PROJECT_ENVIRONMENT="$VENV" uv sync --python 3.12

echo "==> 4. Point supervisor's uvicorn at it"
# Supervisor's command is a read-only file, so the executable it names becomes a
# shim. Kept idempotent: re-running only rewrites the shim.
if [ ! -e "$SERVED/bin/uvicorn.real" ] && [ -f "$SERVED/bin/uvicorn" ] \
   && ! head -2 "$SERVED/bin/uvicorn" | grep -q "$VENV"; then
  cp "$SERVED/bin/uvicorn" "$SERVED/bin/uvicorn.real"
fi
printf '#!/bin/bash\nexec %s/bin/uvicorn "$@"\n' "$VENV" > "$SERVED/bin/uvicorn"
chmod +x "$SERVED/bin/uvicorn"

echo "==> 5. Migrate + seed"
"$VENV/bin/python" manage.py migrate --noinput
"$VENV/bin/python" manage.py seed_foundation
"$VENV/bin/python" manage.py seed_ptmapper || true

echo "==> 6. Restart backend"
supervisorctl restart backend >/dev/null 2>&1 || true
sleep 5
curl -s -m 8 -o /dev/null -w "login -> %{http_code}\n" -X POST http://localhost:8001/api/auth/login \
  -H "Content-Type: application/json" -d '{"username":"owner","password":"Owner@123"}'
echo "==> done."
