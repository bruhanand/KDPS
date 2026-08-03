#!/usr/bin/env bash
# Per-workspace identity for the local dev stack. SOURCE this file, don't run it.
#
#   . "$ROOT/scripts/workspace-env.sh"
#
# A Conductor workspace is already a separate git worktree on a separate branch.
# This file is what also makes it a separate *running system*: its own Docker
# Compose project, so its own Postgres container and its own data volume, on its
# own host ports. Two workspaces can run `npm run dev` at the same time and
# neither can see - or migrate, or seed, or drop - the other's database.
#
# Conductor hands each workspace a block of ten host ports starting at
# CONDUCTOR_PORT. We spend three of the ten:
#
#   CONDUCTOR_PORT + 0   React PWA (Vite)
#   CONDUCTOR_PORT + 1   Django API
#   CONDUCTOR_PORT + 2   Postgres
#
# Outside Conductor - the plain root checkout, a bare `git clone`, CI - there is
# no allocation to honour, so we fall back to the historic fixed ports
# 3000/8001/55432. A normal checkout therefore behaves exactly as it always has.
#
# Everything that needs to know "which stack am I?" reads it from here and only
# from here: scripts/dev.sh, docker-compose.yml (via $KDPS_PG_PORT), and the
# setup/archive hooks in .conductor/settings.toml. Deriving it twice is how the
# archive hook would end up deleting the wrong workspace's database.

# Deliberately no `set -e` - callers own their own shell options, and this file
# is sourced into them.

_kdps_slug() {
  # Compose project names must match [a-z0-9][a-z0-9_-]*. Worktree directory
  # names can carry a slash or a capital, so normalise rather than trust.
  printf '%s' "$1" \
    | tr '[:upper:]' '[:lower:]' \
    | sed -e 's/[^a-z0-9_-]/-/g' -e 's/^[^a-z0-9]*//' -e 's/[^a-z0-9]*$//'
}

# The worktree directory, unlike a Conductor workspace display name, does not
# change when someone retitles a workspace. Compose persists its project name in
# container and volume names, so deriving it from a display name leaves an old
# project holding the same allocated port after a rename. Use the checkout's
# stable directory identity everywhere that names local resources.
#
# `git rev-parse --show-toplevel` and not $0/$BASH_SOURCE: this file is sourced,
# and Conductor runs scripts under zsh, where BASH_SOURCE does not exist.
KDPS_SLUG="$(_kdps_slug "$(basename "$(git rev-parse --show-toplevel 2>/dev/null || pwd)")")"
[ -n "$KDPS_SLUG" ] || KDPS_SLUG=default

KDPS_PROJECT="kdps-$KDPS_SLUG"

if [ -n "${CONDUCTOR_PORT:-}" ]; then
  KDPS_WEB_PORT=$(( CONDUCTOR_PORT ))
  KDPS_API_PORT=$(( CONDUCTOR_PORT + 1 ))
  KDPS_PG_PORT=$(( CONDUCTOR_PORT + 2 ))
else
  KDPS_WEB_PORT=3000
  KDPS_API_PORT=8001
  KDPS_PG_PORT=55432
fi

# The database name and credentials are identical in every workspace. Isolation
# comes from the container, not from the name - so a connection string in a stack
# trace differs in exactly one place, the port, and that is the thing you want to
# read off it.
KDPS_DATABASE_URL="postgres://kdps:kdps@localhost:$KDPS_PG_PORT/kdps_dev"
KDPS_BACKEND_URL="http://localhost:$KDPS_API_PORT"

export KDPS_SLUG KDPS_PROJECT
export KDPS_WEB_PORT KDPS_API_PORT KDPS_PG_PORT
export KDPS_DATABASE_URL KDPS_BACKEND_URL
