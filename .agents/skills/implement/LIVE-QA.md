# Live QA

Prove the built thing works by using it, in a real browser, the way a store user would.
A green suite and a broken screen coexist happily: the button calls nothing, the table renders empty, the money renders as `285000` instead of `₹2,85,000`.
This catches exactly that.

Use whichever browser tooling the session has (see "Browser use" in `CLAUDE.md`), loading the tools you need in one ToolSearch call.
It drives the user's own Chrome: always a new tab, never a tab from another session; and never trigger an alert or confirm dialog - it blocks everything until dismissed by hand.

## Preconditions: is the thing under test the thing you built?

Skip this and you will debug a ghost - a stale container has served months-old code against a migrated schema before.

1. **Is a stack already up?** Check who holds `:8001`/`:3000`. Free: start it with `./scripts/dev.sh`. Held by another session: wait and say so. A stray container from an old checkout: stop and report - never kill another session's stack.
2. **Does the server carry this branch's code?** Compare the `migrations` digest from `/api/health` against this working tree; if they differ, restart and trust nothing the browser shows until they match.
3. **Does the database match the migrations?** `manage.py check_db_drift`; drift means another branch's schema - `./scripts/dev.sh --reset` rebuilds and reseeds.
4. **Is the data there?** Screens assume the seed commands have run; an empty screen is usually missing seed, not a bug - confirm before filing one.

State all four results in one line before touching the browser.

## The flows

One flow per acceptance criterion, in the user's words, plus three regardless:

- The role the feature belongs to, logged in as that user (`memory/test_credentials.md`) - `superadmin` bypasses the RBAC matrix and proves nothing about what a store user sees. Log out or use a fresh profile first.
- One scope-negative flow: a user who should not see this data logs in and does not see it - read scope has failed open in this codebase before.
- One refresh on the changed screen, to catch state that only exists in memory.

## Drive it

Go through the UI - real buttons, real forms, never straight to the API.
Read the page structure first and act on the elements it gives: structure for finding, screenshot for judging.
After each meaningful action, assert three things:

- **Render** - screenshot it and actually look: the data shown matches what you entered or what the DB holds; money in Indian format (`₹2,85,000`), never raw paise; SKU at style x size x colour where the screen deals in stock; empty, loading and error states say something, not a blank rectangle; alignment, truncation, overflow - the standard is pixel perfection, and "not related to my issue" leaves nothing visibly broken: fix it or file it.
- **Network** - the expected endpoint actually fired (a button that calls nothing is the most common silent failure); no 4xx/5xx that is not a deliberate part of the flow; one fire per click, no request storm on render.
- **Console** - zero errors, zero unhandled rejections; React key and prop-type warnings count as findings.

Screenshot the end state of each flow to the scratchpad, named for the flow, and note the paths for the PR body.
Carry conclusions forward, never snapshots, network dumps or console logs.

## Verdict

Report per flow: pass, or fail with what you clicked, what you expected, what happened, and the network or console line that proves it.
Any fail: fix, re-run the gate, drive the flow again.
A real defect outside the issue's scope gets filed as a `needs-triage` issue, in the user's words, and noted in the PR under "Not covered".
Leave the stack running only if you started it and nobody is queued behind you - and say which, so the next session knows.
