#!/usr/bin/env bash
# Live QA - drive this workspace's running stack in a real browser.
#
#   ./scripts/e2e.sh                     run every spec headless
#   ./scripts/e2e.sh e2e/smoke.spec.ts   run one spec
#   ./scripts/e2e.sh --headed            watch it happen
#   ./scripts/e2e.sh --ui                the Playwright inspector
#   ./scripts/e2e.sh --report            open the last run's HTML report
#   ./scripts/e2e.sh --install           install the Chromium Playwright drives
#
# WHICH STACK IS THIS? The one this workspace owns. Every Conductor workspace has
# its own Postgres, API and PWA on its own ports (scripts/workspace-env.sh), so
# this exports KDPS_WEB_PORT before calling Playwright rather than letting a
# hard-coded 3000 QA whichever workspace happens to be listening. Set PW_BASE_URL
# to point somewhere else on purpose.
#
# IT STARTS NOTHING. `npm run dev` owns the stack's lifecycle; this only drives
# it. A harness that silently boots a server is a harness that can QA a stale
# one, so we check and refuse instead.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
FRONTEND="$ROOT/app/frontend"

# shellcheck source=scripts/workspace-env.sh
. "$ROOT/scripts/workspace-env.sh"

BASE_URL="${PW_BASE_URL:-http://localhost:$KDPS_WEB_PORT}"
PLAYWRIGHT="$FRONTEND/node_modules/.bin/playwright"

if [ ! -x "$PLAYWRIGHT" ]; then
  echo "Playwright is not installed. Run: npm --prefix app/frontend install" >&2
  exit 1
fi

case "${1:-}" in
  --install)
    # The browser binary, not the npm package. Once per machine, ~150MB.
    exec "$PLAYWRIGHT" install chromium
    ;;
  --report)
    exec "$PLAYWRIGHT" show-report "$FRONTEND/e2e-results/report"
    ;;
esac

if ! curl -fsS -o /dev/null --max-time 5 "$BASE_URL"; then
  echo "Nothing is serving $BASE_URL." >&2
  echo "Start this workspace's stack first:  npm run dev   (ports: npm run dev:where)" >&2
  exit 1
fi

if ! curl -fsS -o /dev/null --max-time 5 "$KDPS_BACKEND_URL/api/health"; then
  echo "The PWA is up but the API at $KDPS_BACKEND_URL is not answering." >&2
  echo "Every spec would fail at login. Start the API:  npm run dev" >&2
  exit 1
fi

export KDPS_WEB_PORT PW_BASE_URL="$BASE_URL"
cd "$FRONTEND"
exec "$PLAYWRIGHT" test "$@"
