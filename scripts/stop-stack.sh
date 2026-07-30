#!/usr/bin/env bash
# Stop a workspace's running dev stack — the `dev.sh` supervisor and the two
# servers it starts (Django runserver, Vite).
#
#   ./scripts/stop-stack.sh            stop this checkout's stack
#   ./scripts/stop-stack.sh <dir>      stop the stack belonging to <dir>
#   ./scripts/stop-stack.sh --stale    stop every KDPS stack whose workspace
#                                      directory no longer exists
#
# WHY THIS EXISTS. Archiving a Conductor workspace destroys its Postgres
# container and volume, but it never stopped the servers talking to them. They
# outlive the workspace: a Django API answering on a Conductor-allocated port,
# against a database that has been deleted, from a worktree that has been
# deleted. Nothing ever reaps them, and Conductor reuses port blocks — so a new
# workspace handed that block finds its ports taken and cannot start. Ten such
# stacks were found alive on this Mac, one of them more than a day old.
#
# Processes are matched by WORKING DIRECTORY, not by port. A port says "someone
# is on 55070"; a working directory says "this process belongs to that
# workspace". Only the second is safe to act on, because killing a server that
# happens to sit on a port another project also wanted is exactly the mistake
# `dev.sh` refuses to make. The command pattern narrows it further, so an editor
# or an agent session sitting in the same directory is never a candidate.
set -euo pipefail

say()  { printf '\033[1;34m==>\033[0m %s\n' "$*"; }
warn() { printf '\033[1;33m warn\033[0m %s\n' "$*" >&2; }

# The processes `dev.sh` puts on a workspace's ports, and nothing else.
#
# ANCHORED, not substring-matched, and this is the whole point of the pattern. A
# bare `scripts/dev\.sh` also matches `zsh -c '... ./scripts/dev.sh ...'` — any
# shell, agent or terminal whose command line merely *mentions* the script. That
# is not a dev stack, and killing it was the first thing this script did when it
# was written that way. Requiring the script to be the interpreter's first
# argument excludes `-c` invocations, because `-c` is not a path.
STACK_CMD_RE='^[^ ]*(ba|z)?sh +[^ -][^ ]*/scripts/dev\.sh( |$)'
STACK_CMD_RE="$STACK_CMD_RE"'|^[^ ]+ +manage\.py +runserver( |$)'
STACK_CMD_RE="$STACK_CMD_RE"'|^[^ ]*uv +run +[^ ]*python[^ ]* +manage\.py +runserver( |$)'
STACK_CMD_RE="$STACK_CMD_RE"'|^[^ ]*node +[^ -][^ ]*/vite( |$)'

# Never signal the caller or anything it descends from. The anchored pattern
# should already make this impossible, but "should" is not a guarantee worth
# betting an editor — or the archive hook running this very script — on.
_protected() {
  local p=$$ chain=" $$ " guard=0
  while [ "$p" -gt 1 ] && [ "$guard" -lt 64 ]; do
    p="$(ps -o ppid= -p "$p" 2>/dev/null | tr -d ' ')"
    [ -n "$p" ] || break
    chain="$chain$p "
    guard=$((guard + 1))
  done
  printf '%s' "$chain"
}
PROTECTED="$(_protected)"

# Every process's cwd, as "<pid> <path>" lines. One lsof call: asking per-process
# is a fork per PID and this runs on the archive path, where Conductor is waiting.
_cwds() {
  lsof -d cwd -Fpn 2>/dev/null | awk '
    /^p/ { pid = substr($0, 2); next }
    /^n/ { if (pid != "") print pid, substr($0, 2) }
  '
}

# PIDs of stack processes whose cwd is $1 or below it. A worktree's servers run
# from app/backend and app/frontend, so the match has to be by prefix.
_stack_pids_under() {
  local root="$1"
  _cwds | while read -r pid path; do
    case "$path" in
      "$root"|"$root"/*) ;;
      *) continue ;;
    esac
    case "$PROTECTED" in *" $pid "*) continue ;; esac
    ps -o command= -p "$pid" 2>/dev/null | grep -Eq "$STACK_CMD_RE" || continue
    printf '%s\n' "$pid"
  done
}

# Roots of stack processes whose workspace directory has been deleted. The cwd of
# a deleted directory still reads back as its old path, which is what makes an
# archived workspace's leftovers findable at all.
_stale_roots() {
  _cwds | while read -r pid path; do
    [ -d "$path" ] && continue
    case "$PROTECTED" in *" $pid "*) continue ;; esac
    ps -o command= -p "$pid" 2>/dev/null | grep -Eq "$STACK_CMD_RE" || continue
    # app/backend and app/frontend are two levels below the workspace root.
    printf '%s\n' "${path%/app/*}"
  done | sort -u
}

# TERM first: dev.sh traps it and stops its children in order. KILL only for what
# ignores it, and only after a grace period — a Vite mid-write deserves the
# chance to finish.
stop_under() {
  local root="$1" pids
  pids="$(_stack_pids_under "$root" | tr '\n' ' ' | xargs || true)"
  if [ -z "$pids" ]; then
    say "No dev stack running in $root"
    return 0
  fi
  say "Stopping the dev stack in $root (PIDs: $pids)"
  kill $pids 2>/dev/null || true
  for _ in $(seq 1 10); do
    pids="$(_stack_pids_under "$root" | tr '\n' ' ' | xargs || true)"
    [ -n "$pids" ] || { say "Stopped."; return 0; }
    sleep 1
  done
  warn "Still up after 10s — forcing: $pids"
  kill -9 $pids 2>/dev/null || true
}

if [ "${1:-}" = "--stale" ]; then
  roots="$(_stale_roots)"
  if [ -z "$roots" ]; then
    say "No stacks left over from deleted workspaces."
    exit 0
  fi
  say "Dev stacks whose workspace directory is gone:"
  printf '  %s\n' $roots
  for root in $roots; do stop_under "$root"; done
  exit 0
fi

if [ "${1:-}" = "-h" ] || [ "${1:-}" = "--help" ]; then
  sed -n '2,10p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'
  exit 0
fi

stop_under "${1:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"
