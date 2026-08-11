# Live QA

Prove the built thing works by using it, in a real browser, the way a store user would.
A green unit suite and a broken screen coexist happily: the button calls nothing, the table renders empty, the money renders as `285000` instead of `₹2,85,000`.
This catches exactly that.

**Live QA is Playwright.** Specs live in `app/frontend/e2e/`, are committed with the change they QA, and run against this workspace's own stack:

```
npm run e2e                              every spec
npm run e2e e2e/<slug>.spec.ts           one spec
npm run e2e -- --headed                  watch it happen
npm run e2e:report                       the last run's HTML report, traces included
npm run e2e:install                      the Chromium binary, once per machine
```

The runner starts nothing. `npm run dev` owns the stack; `npm run e2e` refuses with a plain message if the PWA or the API is not answering, because a harness that quietly boots its own server is a harness that can QA a stale one.

## Why a spec and not a driven browser

Hand-driving a browser cost a fresh session of clicking every time and proved nothing once the screen changed.
A spec is the same work written down once: it **reruns** as the next issue's free regression test, it **cannot pass by accident** (the guards fail it on any undeclared console error or 4xx), it is **cheap in context** (screenshots and traces attach to the report, not the transcript), and **dialogs stop mattering** (Playwright auto-dismisses `alert`/`confirm`).
The one thing a spec cannot do is *look* at the screen and judge it - that is the visual pass below, and it stays.

## Preconditions: is the thing under test the thing you built?

Skip this and you will debug a ghost - a stale container has served months-old code against a migrated schema before.

1. **Which stack is mine, and is it up?** `npm run dev:where` prints this workspace's ports and database - it owns them, and another workspace running its own stack is not your problem, so never wait on one. Ports free: start it with `npm run dev`. Something you did not start holding *your* ports: stop and report - never kill another session's stack.
2. **Does the server carry this branch's code?** Compare the `migrations` digest from `/api/health` against this working tree; if they differ, restart and trust nothing until they match.
3. **Does the database match the migrations?** `manage.py check_db_drift`; drift can now only be your own, from an earlier branch of this worktree - `npm run dev:reset` rebuilds and reseeds this workspace's database alone.
4. **Is the data there?** Specs assume the seed commands have run; an empty screen is usually missing seed, not a bug - confirm before filing one.

State all four results in one line before running anything.

## The toolkit

Import `test` and `expect` from `./kdps`, never from `@playwright/test` - the extended `test` carries the guards, and a spec that bypasses them can pass over a console full of React errors.

| | What it does |
|---|---|
| `loginAs(page, role)` | Real form login as a seeded user. A context starts with no cookies, so a fresh session per role is structural, not a step to remember. |
| `ROLES` | The seeded logins, keyed by role. Mirrors `memory/test_credentials.md`. |
| `expectMoney(locator)` | Indian format (`₹2,85,000`) or fail. Raw paise has no grouping, so it cannot slip through. |
| `expectCall(page, /url/, fn)` | Runs the action and asserts it actually called the API. A button wired to nothing looks identical to a working one in a screenshot. |
| `receiptsPrinted(page)` | What the receipt iframe was asked to print. The print dialog is intercepted for you. |
| `evidence(page, name)` | Screenshot attached to the report, not pasted into a transcript. |
| `guard.allowResponse(/url/, why)` | Declare an expected failure. A 403 in a scope-negative flow is the flow working - say so, with a reason. |
| `guard.allowConsole(/pattern/, why)` | Same, for an expected console line. |

Everything undeclared fails the test: console errors, unhandled rejections, React key and prop-type warnings, and any response of 400 or worse.

Two things the guards forgive on their own, and it is worth knowing why.
Chrome mirrors every failed request into the console as `Failed to load resource` with no URL attached, so that class is dropped there and owned by the network guard, which can name the endpoint - otherwise one expected 403 would have to be declared twice, once without being able to say which 403 you meant.
And loading any page while signed out fires the session probe (`/api/auth/me` 401, then `/api/auth/refresh` 400); every spec starts signed out, so that is the app working.
It is forgiven **only until a login succeeds** - the same 401 after someone has signed in means the session was dropped, and stays a failure.

**`window.print()` is intercepted, not called.** Chrome's print preview is browser UI - no click Playwright sends reaches it, and the run hangs.
The Billing screen prints through a hidden `<iframe title="Receipt">`, and the toolkit replaces that frame's `print` before the page loads, leaving `receiptsPrinted(page)` as the evidence that the receipt was built and what it said.
Product code is untouched.
To QA the printer-is-off path, make the interception throw: the bill must still save, with a banner and a working Reprint.

## The flows

One spec file per issue, at `app/frontend/e2e/<issue-slug>.spec.ts`.
One test per acceptance criterion, named in the user's words, plus three regardless:

- **The owning role**, logged in as that user. `superadmin` bypasses the RBAC matrix and proves nothing about what a store user sees.
- **One scope-negative flow**: a user who should not see this data logs in and does not see it. Read scope has failed open in this codebase before.
- **One reload** on the changed screen, to catch state that only exists in memory.

Go through the UI - real buttons, real forms, never straight to the API.
Prefer `getByTestId`, then `getByRole`; a CSS class is a selector that breaks on a restyle.
Never `waitForTimeout` - assert on the thing you are actually waiting for, or the spec is flaky by construction, and there are no retries here on purpose.

## The visual pass

The guards prove the machinery. They do not prove the screen looks right, so once per issue - after the specs are green - open the report and **read two or three screenshots** and judge them:

- Money in Indian format wherever money appears; SKU at style x size x colour wherever the screen deals in stock.
- Empty, loading and error states say something, not a blank rectangle.
- Alignment, truncation, overflow. The standard is pixel perfection, and "not related to my issue" leaves nothing visibly broken: fix it or file it.

Two or three, not twenty. A screenshot read into a transcript is the most expensive thing this phase can do to its context, and the tenth one tells you nothing the third did not.

## Verdict

Report per test: pass, or fail with what it clicked, what it expected, what happened, and the console or network line that proves it.
Reference the trace path from the report; never paste a trace or a network dump.
Any fail: fix, re-run the spec.

A real defect outside the issue's scope gets filed as a new issue with **no label**, in the user's words, and noted in the PR under "Not covered" - unlabelled is the untriaged state, so it lands in the triage queue rather than looking ready to build.

Commit the spec with the change. That is the whole point: the next issue that touches this screen inherits the QA instead of repeating it.
