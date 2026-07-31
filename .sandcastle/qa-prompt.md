# TASK

Prove issue {{TASK_ID}} ({{ISSUE_TITLE}}) works by using it, in a real
browser, the way a store user would. Branch {{BRANCH}} is checked out. Mode:
{{MODE}}.

- `full` — drive every flow.
- `re-drive` — the code was fixed since the last drive: read
  `{{ART_DIR}}/qa-report.md` and re-drive **only the flows that failed**,
  then update the report.

A green suite and a broken screen coexist happily: the button calls nothing,
the table renders empty, the money renders as `285000` instead of `₹2,85,000`.
This catches exactly that. You change no code — you report, and a separate
fixer acts on your report.

# BOOT THE STACK

PostgreSQL is already running. Everything happens inside this sandbox — there
is no other session to wait for and nothing here is anyone's live data.

1. API: from `app/backend`,
   `nohup uv run python manage.py runserver 0.0.0.0:8001 > /tmp/api.log 2>&1 &`
   then poll `curl -s localhost:8001/api/health` until it answers.
2. Data: foundation, roles and PT-mapper lookups are already seeded. If the
   flows need documents and money on screen, run
   `uv run python manage.py seed_demo_data` once.
3. Frontend: from `app/frontend`,
   `nohup yarn dev --port 3000 > /tmp/fe.log 2>&1 &`
   then browse `http://localhost:3000`.

# THE BROWSER

Headless Chromium via the **playwright MCP tools** (`browser_navigate`,
`browser_snapshot`, `browser_click`, `browser_type`, `browser_take_screenshot`,
`browser_console_messages`, `browser_network_requests`, `browser_evaluate`).
Snapshot for finding elements, screenshot for judging what a user sees.

Never trigger `window.print()` or any dialog. For a flow that prints, install
the Receipt-iframe interception snippet from
`.agents/skills/implement/LIVE-QA.md` via `browser_evaluate` **before**
pressing Save & Print — `window.__printed` becomes the evidence of what the
receipt said. Make `print()` throw instead and you have the printer-is-off
path: the bill must still save, with a banner and a working Reprint.

# THE FLOWS

One flow per acceptance criterion in `{{ART_DIR}}/slice-plan.md`, in the
user's words, plus three regardless:

- **As the role the feature belongs to**, logged in as that user
  (`memory/test_credentials.md`) — never `superadmin`: it bypasses the RBAC
  matrix and proves nothing about what a store user sees.
- **One scope-negative flow**: a user who should not see this data logs in and
  does not see it — read scope has failed open in this codebase before.
- **One refresh** on the changed screen, to catch state that only exists in
  memory.

# DRIVE IT

Go through the UI — real buttons, real forms, never straight to the API.
After each meaningful action, assert three things:

- **Render** — screenshot it and actually look: the data shown matches what
  you entered or what the DB holds; money in Indian format (`₹2,85,000`),
  never raw paise; SKU at style × size × colour where the screen deals in
  stock; empty, loading and error states say something, not a blank rectangle.
- **Network** — the expected endpoint actually fired (a button that calls
  nothing is the most common silent failure); no 4xx/5xx that is not a
  deliberate part of the flow; one fire per click.
- **Console** — zero errors, zero unhandled rejections; React key and
  prop-type warnings count as findings.

Screenshots go to `{{ART_DIR}}/screenshots/`, named for the flow. They persist
on the run host after this sandbox closes — the PR references them.

# VERDICT

Write `{{ART_DIR}}/qa-report.md`, **under 300 words**: per flow, pass — or
fail with what you clicked, what you expected, what happened, and the network
or console line that proves it. Screenshots referenced by path, never pasted.

A real defect outside this issue's scope: file it as a `needs-triage` issue in
the user's words (`gh issue create -R bruhanand/KDPS --label needs-triage …`)
and note it in the report — do not fail the run for it.

Then output exactly one of:

<qa>PASS</qa>   — every flow passed
<qa>FAIL</qa>   — at least one flow failed
