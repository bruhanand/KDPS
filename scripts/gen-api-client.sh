#!/usr/bin/env bash
# Regenerate the PWA's typed API client from the backend's own OpenAPI schema.
#
#   ./scripts/gen-api-client.sh            rewrite app/frontend/src/lib/api-schema.ts
#   ./scripts/gen-api-client.sh --check    fail if the committed file is stale
#
# WHY THIS EXISTS. ADR-0001/0002 pin a two-step toolchain - `drf-spectacular`
# turns Django into an OpenAPI document, `openapi-typescript` turns that document
# into `app/frontend/src/lib/api-schema.ts` - and ADR-0005 makes "the generated
# client is not stale" part of the gate. The toolchain was pinned; the command
# never was. It lived in whoever's shell history, so endpoints landed without a
# regeneration and the file drifted about a thousand lines behind the backend
# (#192). Screens hand-wrote the shapes they expected instead, which works right
# up until the backend changes one and nothing says so.
#
# The whole point of generating the file was that `tsc` would fail when a screen
# and the API stopped agreeing. A stale file cannot do that: it agrees with a
# backend that no longer exists.
#
# NO DATABASE IS TOUCHED. `manage.py spectacular` reads the URL conf and the
# serializers, never a row, so this runs on a checkout with nothing booted -
# which is what lets the CI drift job skip the Postgres service and finish in
# under a minute. DATABASE_URL is still read at import (settings.py), so a
# placeholder is supplied when the caller has none; it is never connected to.
#
# DETERMINISM is the contract that makes `--check` meaningful. Same schema in,
# byte-identical TypeScript out - so a diff here always means the backend moved,
# never that the generator wandered. Two things protect it: the generator is the
# version yarn.lock pins (run from app/frontend/node_modules, never `npx`, which
# would happily fetch a newer one), and nothing environment-dependent reaches the
# schema - the only DEBUG-gated routes in config/urls.py are the plain-Django
# health view and the admin, and neither is a DRF view, so neither appears.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BACKEND="${REPO_ROOT}/app/backend"
FRONTEND="${REPO_ROOT}/app/frontend"
CLIENT="${FRONTEND}/src/lib/api-schema.ts"
GENERATOR="${FRONTEND}/node_modules/.bin/openapi-typescript"

say()  { printf '\033[1;34m==>\033[0m %s\n' "$*"; }
fail() { printf '\033[1;31merror\033[0m %s\n' "$*" >&2; exit 1; }

CHECK=0
case "${1:-}" in
  --check) CHECK=1 ;;
  "")      ;;
  *)       fail "unknown argument '$1' (expected --check or nothing)" ;;
esac

command -v uv >/dev/null 2>&1 || fail "uv is not installed — see README.md"
[ -x "${GENERATOR}" ] || fail "openapi-typescript is missing — run: npm --prefix app/frontend install"

WORK="$(mktemp -d)"
trap 'rm -rf "${WORK}"' EXIT

# Never connected to; settings.py only requires the variable to exist.
export DATABASE_URL="${DATABASE_URL:-postgres://schema:schema@127.0.0.1:1/schema-generation-only}"

say "Describing the backend (drf-spectacular)…"
# The generator is chatty about serializers it cannot introspect (~530 lines of
# "unable to guess serializer" for plain APIViews). That is a real weakness in
# the API's self-description and is tracked separately; it is not this script's
# business to fail on it, so the log is kept out of the way unless it is asked
# for or the command actually dies.
if ! (cd "${BACKEND}" && uv run python manage.py spectacular --file "${WORK}/schema.yaml") \
     >"${WORK}/spectacular.log" 2>&1; then
  cat "${WORK}/spectacular.log" >&2
  fail "the backend could not describe itself"
fi

say "Generating TypeScript (openapi-typescript)…"
"${GENERATOR}" "${WORK}/schema.yaml" --output "${WORK}/api-schema.ts" >/dev/null

if [ "${CHECK}" -eq 1 ]; then
  if diff -u "${CLIENT}" "${WORK}/api-schema.ts" >"${WORK}/drift.diff"; then
    say "The generated API client is in sync with the backend."
    exit 0
  fi
  # Show the drift rather than only naming it: on a red gate the reviewer's next
  # question is always "drifted how", and the answer should not need a re-run.
  cat "${WORK}/drift.diff" >&2
  cat >&2 <<'MSG'

error The generated API client is stale.

  app/frontend/src/lib/api-schema.ts no longer matches what the backend
  describes. It is generated, never hand-edited — regenerate and commit it
  alongside the backend change that moved it:

      npm run api:client

MSG
  exit 1
fi

cp "${WORK}/api-schema.ts" "${CLIENT}"
say "Wrote ${CLIENT#"${REPO_ROOT}"/}"
