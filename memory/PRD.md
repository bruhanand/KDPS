# KDPS Operating System — PRD / Build Memory

## Problem statement
KDPS Lifestyle Pvt Ltd is a multi-brand apparel retailer operating stores across
**Bihar & Jharkhand** (one PAN / one legal entity / two state GSTINs). We are building a
**deterministic retail ERP** ("KDPS Operating System"): documents write append-only
ledgers, Tally remains the statutory book, AI is suggest-only at the edges. The repo's
`docs/` folder holds the full plan (constitution `CONTEXT.md`, 12 rules, 7 ADRs, a
191-page application map across 14 modules).

## Stack
Django + DRF + PostgreSQL backend (`/app/backend`, served by uvicorn via a shim,
`.venv`→`/opt/kdpsvenv` py3.12), React + TypeScript + Vite frontend (`/app/frontend`).
`bash scripts/dev-bootstrap.sh` rebuilds the whole dev environment (Postgres install +
role/db, `uv sync`, migrate, seeds) whenever the pod is reprovisioned — `/usr` and
Postgres binaries do not survive that, only `/app` does. Both `backend/.env`
(`DATABASE_URL`) and `frontend/.env` (`REACT_APP_BACKEND_URL`) must exist for the app
to boot; if a fresh pod has neither, create them (Postgres user/db `kdps`/`kdps_dev`,
password `kdps`) before running the bootstrap script.

## Document history
This file holds the static problem statement and the current architecture snapshot
only. The full dated history of every review/build pass is in **`CHANGELOG.md`**
(newest first). Open backlog by priority is in **`ROADMAP.md`**.

## Current state — 4 Aug 2026 (Warehouse Ops + Offers/Pricing redesign)
Built and tested in this session, in the priority order the user confirmed:

**P0 — Distribution allocation grid.** New screen `/transfer/distribution`
(sidebar: Transfer → Distribution). Ops Head picks a source warehouse, ticks
destination stores, searches arrived stock by barcode/design, and enters a
qty-per-store grid with a live allocated-vs-available check. "Create transfers"
bulk-creates one **draft `store_split` transfer per destination store** via the
*existing* `POST /outbound/transfers` → approve → dispatch → receive pipeline —
nothing in the posting engine changed; this is purely a batch front-end over it.
Cross-state destinations require an e-way bill number inline before submit.
New `TransferReason.WAREHOUSE_ALLOCATION` tags every draft the grid raises.

**P0 — Partner store flag + configurable billing at Purchase Price.**
- `Store.is_partner` (boolean, default False) — Setup → Stores now has a
  "Partner store" checkbox and a Partner column.
- Every transfer to a partner-store destination now computes
  `StoreTransfer.partner_billing_value_paise` = qty dispatched × the books'
  own unit cost (Purchase Price), set **before** `.post()` (submitted documents
  are immutable — this cost the first attempt a rollback before the fix landed).
  Shown on the transfer detail page as a "Partner billing" card.
- **`BillingPolicy`** (singleton, `outbound/models.py`) is the chain-wide dial the
  user asked to keep configurable rather than hardcoded: `informational` (figure
  shown only, no ledger entry — matches every other transfer's "stock move only,
  no GL" rule) or `gl_posting` (also posts **Dr `PARTNER_RECEIVABLE` / Cr
  `INVENTORY`** at that value, no margin — a partner is billed at cost). Read at
  `money: view`, changed at `money: manage`. Its own page/nav item is
  **Money → Partner Billing** (`/money/partner-billing`) — it was first bolted onto
  `/setup/settings`, which is gated at `sell: manage` and walled Owner out; moved
  to its own Money-section page once the testing agent caught that.
  Verified end-to-end: dispatched a real transfer DEO→BANKA(partner) with
  `gl_posting` on, confirmed via Django shell a balanced
  `Dr PARTNER_RECEIVABLE 280000 / Cr INVENTORY 280000` posted, trial balance
  stayed ₹0. Left the demo policy on `informational` (the safe default) and
  BANKA (`id=5`) flagged as a partner for the testing agent's use.

**P1 — Offers & Pricing sidebar simplified, 5 items → 3.** "Offers & Price" now
shows **Price Book** (`/offers/price-list`, was "Price List"), **Promotions**
(`/offers`, was "Offers"), **Discount Reports** (`/offers/discounts`, was
"Discounts") — same URLs, just renamed and fewer rows, since `PageHeader` derives
each screen's H1 from the nav label. "New Offer" and "EOSS Planning" are no
longer separate sidebar entries but are fully reachable exactly as before: New
Offer via the existing "Write an offer" CTA already on Promotions, EOSS Planning
via a small in-page tab row (new shared `components/PromotionsTabs.tsx`) shown on
both `/offers` and `/offers/eoss`. Routes, gates and backend are all untouched —
this was a manifest + presentation change only, kept deliberately light (no fold/
strip architecture) because those two screens serve the same audience
(`offers_price: view`/`operate`) as the page hosting them.

**P2 — Mock tag printing.** Price Book rows have a "Print tag" button opening a
preview modal (design/color/size/MRP) with a "Print" action that shows "Sent to
printer (mock)" — explicitly **MOCKED**, no printer integration exists.

**Deferred, by the user's own choice** ("we can do it later"): the AI PT-file
chat assistant. Not started.

**Environment note for the next session:** this pod's `backend/.env` and
`frontend/.env` did not exist at session start (fresh reprovision) — recreated
per the Stack section above, then `bash scripts/dev-bootstrap.sh` rebuilt
everything. If backend 500s on boot with `ModuleNotFoundError: No module named
'django'`, that's this exact situation — check `.env` files first before
anything else.

**Recurred again (Partner Settlements session, same day):** fresh pod, `.env`
files this time DID exist but Postgres itself was never started and the
`kdps`/`kdps_dev` role+db didn't exist, and `/root/.venv` had no packages at
all (not even Django) — `dev-bootstrap.sh` was not run automatically this
time either. Fixed manually: `pg_ctlcluster 15 main start`, then as the
`postgres` OS user `CREATE ROLE kdps WITH LOGIN PASSWORD 'kdps' CREATEDB;`
+ `CREATE DATABASE kdps_dev OWNER kdps;`, then `cd backend && UV_PROJECT_
ENVIRONMENT=/root/.venv uv sync --active` (installs straight into the venv
supervisor's uvicorn shim already points at — do NOT let `uv sync` create a
second venv at `backend/.venv`; pass `--active`/set `UV_PROJECT_ENVIRONMENT`
so it targets `/root/.venv`), then `manage.py migrate` + `manage.py
seed_foundation` + `manage.py seed_demo_data` (the latter is idempotent —
if it errors partway through on a fresh DB, just re-run it once, it will
skip already-seeded steps and complete). **Run `bash scripts/dev-bootstrap.sh`
first thing next time** rather than these manual steps — it exists precisely
for this. No partner store came pre-seeded; BANKA (`store_id=5`) was flagged
`is_partner=True` and given one dispatched transfer via Django shell so the
Partner Dues / Settlements screens had real data (see next entry).

**Follow-up (same session): Security audit + hardening.** Ran `security_audit_agent`
against the deployed preview — verdict was DO-NOT-LAUNCH on 4 findings. User said
"fix all of the findings," so:
- **[CRITICAL, fixed]** `DJANGO_SECRET_KEY` was the dev/CI placeholder
  (`kdps-dev-secret-not-for-production`) in the deployed `.env` — forgeable JWTs,
  including an Owner login. Rotated to a strong random 64-byte key. Added a
  startup guard in `config/settings.py`: raises `RuntimeError` if `DJANGO_DEBUG=0`
  and `SECRET_KEY` is still a known placeholder, so this can't silently regress.
- **[HIGH, fixed]** `DJANGO_DEBUG` was `1` in the deployed env — leaked
  tracebacks on 500s, published migration names, and (per `config/urls.py`'s
  existing `_ENABLE_ADMIN` gate) mounted Django admin. Set to `0`. Ran
  `collectstatic` (WhiteNoise needs it once DEBUG=0).
- **[HIGH, fixed — same DEBUG flip]** `/admin/` is no longer mounted by Django
  (confirmed 404 hitting the backend directly on :8001). Left the seeded
  superuser password unchanged — it's a documented test credential
  (`test_credentials.md`) and the admin route is now unreachable regardless.
- **[MEDIUM, fixed]** CORS was reflecting any `*.emergentagent.com` origin
  with credentials (`CORS_ALLOWED_ORIGIN_REGEXES`, DEBUG-gated already but
  DEBUG was on). Pinned `CORS_ALLOWED_ORIGINS` + `CSRF_TRUSTED_ORIGINS` env
  vars to the exact deployed origin instead. Verified at the Django layer: an
  allowed origin gets echoed back with credentials, a disallowed one gets no
  CORS header at all. **Caveat surfaced by the testing pass:** on *this*
  preview platform, the ingress/edge in front of the app adds its own
  unconditional `Access-Control-Allow-Origin: *` to every response — so this
  fix is real and correct for actual production hosting (Render, custom
  domain) but is superseded by the platform's own edge on the shared preview
  URL. Told the user this plainly rather than claiming the preview URL itself
  is now CORS-locked.
- **[Hardening, fixed]** `AUTH_PASSWORD_VALIDATORS` had only
  `MinimumLengthValidator`; added `CommonPasswordValidator`,
  `UserAttributeSimilarityValidator`, `NumericPasswordValidator`. Applies to
  new/changed passwords only — existing seeded hashes untouched, verified all
  still authenticate.
- **[Attempted, reverted]** Tried tightening `DJANGO_ALLOWED_HOSTS` from `*`
  to an explicit host list — this broke every request through the platform's
  public ingress with `400 DisallowedHost` (the Host header this platform's
  edge forwards doesn't match the public hostname 1:1). Reverted to `*`.
  **Do not retry this on this platform** unless the actual forwarded Host
  header is confirmed first.
- **[Deferred, not done]** Moving the frontend off `localStorage` JWTs onto
  the httpOnly-cookie-only path the backend already supports
  (`CookieOrHeaderJWTAuthentication`, `_set_auth_cookies` in
  `accounts/views.py`) was flagged as a lower-priority hardening note in the
  audit. Skipped: it's an app-wide auth-flow change (every page's axios
  interceptor + session-bootstrap logic) for a defense-in-depth improvement
  against a currently-theoretical XSS vector, not an active exploit path —
  disproportionate risk for the residual gain. Offered as a backlog item.
- `testing_agent_v4` (iteration_34): wrote
  `backend/tests/test_security_hardening_regression.py` (14 tests: health,
  clean 404/no-traceback, login for 4 roles with valid JWT, `/me`, logout,
  unauth rejection, Partner Dues/Vendor Ledger/Stores reads, admin-route
  check) — 100% pass, backend + frontend, zero regressions from the
  secret-key rotation / DEBUG flip; all seeded passwords still work.

**Follow-up (same session): Settlement Receipts.** A "Receipt" button on every
payment row in `PartnerDues.tsx`'s history table (only on `payment` rows, not
reversals — a reversal isn't money received) opens a printable, letterhead-
styled A4 voucher: `frontend/src/lib/settlementReceipt.ts` builds a whole HTML
document (same convention as the till's own customer receipt,
`till/receipt.ts`) and prints it through the already-built, already-tested
`till/print.ts`'s `browserPrintAdapter` (hidden iframe + `window.print()`) —
reused as-is, no till-specific coupling in that module. User's explicit
choices: letterhead style ("KDPS LIFESTYLE PVT LTD"), titled "Settlement
Receipt." No fabricated address/GSTIN on it — `masters.LegalEntity` has no
address field and this is an internal payment voucher, not a GST tax invoice,
so it doesn't need one. Shows voucher no., date, store, amount, mode,
reference, note, and who recorded it (`PartnerSettlementsView` now also
returns `posted_by_name`, resolved server-side from
`PartnerLedgerEntry.posted_by`). Prompted by a user-uploaded document, `KDPS
Daily Work Survey - Accounts Team.pdf` (Chetna, Account Head) — her stated
pain point is not trusting a figure until she's chased it down, which a
printable per-payment voucher directly answers. Self-tested (Playwright):
button renders only on payment rows, click spawns the print iframe with the
correct letterhead/amount, no console errors; a direct unit check of
`settlementReceiptHtml()` confirmed correct data substitution and that
free-text `reference`/`description` fields are HTML-escaped (no injection).

**Follow-up (same session): Cookie-only sessions.** The one hardening item
deferred above — moved the frontend fully onto the httpOnly-cookie auth path
the backend already supported (`CookieOrHeaderJWTAuthentication`,
`_set_auth_cookies`/`_clear_auth_cookies` in `accounts/views.py`), instead of
storing the access/refresh JWTs in `localStorage`. `frontend/src/lib/api.ts`:
removed the `tokens` object (`kdps_access`/`kdps_refresh` localStorage keys)
entirely; the request interceptor no longer attaches any `Authorization`
header (pure `withCredentials: true` + auto-sent httpOnly cookies); the
401→refresh→retry flow now posts an empty body to `/auth/refresh` (the
existing `CookieRefreshView` already falls back to
`request.COOKIES.get('refresh_token')`); replaced the old "compare the
localStorage refresh token before/after" race-guard with a small
`authSession.bump()` epoch counter, bumped by `AuthContext` on every
login/logout, so a stale request's failed refresh can never fire a spurious
`kdps:session-expired` after a newer login/logout already replaced the
session. `AuthContext.tsx`: the mount-time bootstrap now always calls
`/auth/me` (can't check "is there a token" client-side anymore — a 401 just
means logged out, not an error). Backend: `LogoutView` now also falls back to
`request.COOKIES.get('refresh_token')` for blacklisting, since the browser
no longer sends it in the body. **Login/refresh still return the JWTs in the
JSON body too** — intentionally preserved for curl/Postman/API-testing via
`Authorization: Bearer`, only the *browser* stopped using that path.
Hit one debugging red herring worth recording: direct `curl` against
`localhost:8001` over plain HTTP showed the `access_token` cookie
inconsistently surviving logout in curl's own cookie jar while
`refresh_token` cleared correctly — proved via Django's test client that the
server's two delete-cookie responses are byte-for-byte symmetric, then
confirmed with a real Playwright/Chromium session against the public HTTPS
URL that both cookies clear correctly in an actual browser. That curl
behaviour was a curl-specific quirk (likely its inconsistent enforcement of
the `Secure` attribute over a plain-HTTP direct connection), not a real bug —
**test cookie-clearing against a real browser or the public HTTPS URL, not
raw curl on the local HTTP port.**
`testing_agent_v4` (iteration_35): wrote `backend/tests/
test_auth_cookie_migration.py` (7 pytest) + full real-browser Playwright pass
— 100% pass. Confirmed: localStorage stays empty of token keys post-login;
session survives a full reload; logout clears both cookies and truly ends the
server-side session (direct nav to `/` post-logout bounces to `/login`); 3-role
regression (owner/accounts1/deo.manager) all fine; a real mutation (Partner
Dues → Record Payment) succeeds with zero `Authorization` headers anywhere;
a fresh cookie-less context hitting `/` redirects cleanly with no retry loop;
header-based `Authorization: Bearer` auth for non-browser clients (curl/API
testing) still works fully, unaffected.

**Follow-up (same session): Partner Settlements — Accounts can now record a
payment against a partner store's dues.** New append-only
`finledger.PartnerLedgerEntry` (mirrors `VendorLedgerEntry`'s shape, but only
`payment`/`reversal` kinds — there is deliberately no `BILL` kind on this
ledger; the billed side stays `StoreTransfer.partner_billing_value_paise` as
before, so nothing double-counts). `finledger.posting.post_partner_settlement()`
/ `reverse_partner_settlement()`: records the payment (+ optional paired
cash-in receipt on the cash ledger), and only bridges to the value GL
(`Dr CASH / Cr PARTNER_RECEIVABLE`) when `BillingPolicy.mode == GL_POSTING` —
under `informational` mode there was never a GL receivable to clear, so a
settlement stays subledger-only too, exactly mirroring the billing side's own
GL-skip logic. `outbound.PartnerDuesView` now also returns `total_paid_paise`
/ `net_outstanding_paise` per store and in aggregate (Outstanding = Owed −
Paid). New `PartnerSettlementsView` (`GET`/`POST /api/outbound/
partner-settlements`, `money:view` read / `money:manage` write) and
`PartnerSettlementReverseView` (`POST .../<id>/reverse`). User's explicit
choices: payment mode is a free-form dropdown (cash/bank/upi/cheque/other,
not restricted); partial payments are allowed with no blocking (overpayment
is allowed too — Net Outstanding can go negative, meaning a credit); payment
history is shown in the UI. Frontend: `/money/partner-dues` now shows
Owed/Paid/Outstanding stat cards + table columns, a per-row "Record Payment"
inline form, and a per-store expandable "Payments received" history table
with a Reverse action per entry (append-only correction, not an edit).
`testing_agent_v4` (iteration_33): wrote `backend/tests/
test_partner_settlements.py` (12 tests: dues aggregation math, full payment
lifecycle incl. partial/overpay/reverse/double-reverse-409, non-positive
amount rejection, RBAC 403 for a non-finance role) — 100% pass, backend +
frontend, no bugs found, no regression on Vendor Ledger / Partner Billing
Policy pages.

**Follow-up (same session): Distribution grid now suggests a starting split.**
Adding a SKU row pre-fills its qty-per-destination cells with an even split of
the available quantity across the currently-selected destinations (remainder to
the earliest-picked stores) instead of opening blank — `equalSplit()` helper in
`DistributionGrid.tsx`. Every cell stays freely editable; a per-row "re-split"
button recomputes the even split on demand (useful after a manual edit, or
after changing which destinations are selected — existing rows never
auto-recompute on a destination change, only on that explicit click, so a
manual edit is never silently clobbered). `testing_agent_v4` (iteration_31):
100% pass, all 6 scenarios (pre-fill on add, edit+re-split override, a second
row's independent pre-fill, no-auto-recompute-on-dest-change, re-split-picks-up
-new-dest-set, submit still creates drafts correctly).

**Follow-up (same session): Partner Dues Report + Real Tag Printer.**

*Partner Dues report* (Money → Partner Dues, `/money/partner-dues`): a
read-only summary of what each partner store owes, summed directly off
`StoreTransfer.partner_billing_value_paise` for `SUBMITTED` transfers to
`is_partner=True` destinations — new `PartnerDuesView` (`money:view`,
`GET /api/outbound/partner-dues`), returns per-store totals + a drill-down
transfer list. Means the same thing under either `BillingPolicy` mode, since
it reads the figure every transfer already carries rather than the GL.
No payment/settlement tracking exists yet, so "owed" is a running total
billed, not netted against anything received — called out on the page itself.

*Real tag printing*, replacing the earlier mock: user's choice was "the most
universal option" (no vendor SDK, no specific printer in hand) at a
**50mm × 50mm rounded label**, "2 tags or it should be configurable" for
copies. Implemented as browser-native `window.print()` with `@media print`
CSS (`TagPrint.tsx` + `TagPrint.css`) sized to exactly that label — works with
whatever printer/driver is installed on the computer, including thermal
label printers (Zebra/TSC/Brother QL) that install as a normal OS printer.
Price Book rows got a checkbox column + "Print N selected tags" bulk toolbar
button, so one print job can cover many SKUs at once; a "Copies per tag"
input (default 2, clamped 1–20) applies to every tag in that job. This is
**no longer mocked** — it is a genuine (browser-based) print integration.

`testing_agent_v4` (iteration_32): 100% pass, no bugs — nav item, summary
card, expand/drill-down, doc-number link to transfer detail, checkbox
selection + bulk button + count, copies clamp at both ends, Print button
label reflecting rows×copies, no crash/hang on click, no leftover "mock"
wording anywhere, and the pre-existing "Ticket & trail" modal unaffected.

**Follow-up (new session): Daily Cash Dashboard + Bank Reconciliation — wired
in and shipped.** Backend (models, `finledger/reconciliation.py` matching
engine, `/api/finledger/cash/daily` + `/api/finledger/bank/imports` +
`/api/finledger/bank/imports/<id>/lines` + `/api/finledger/bank/lines/<pk>/
match`) and both screens (`DailyCash.tsx`, `BankReconciliation.tsx`) were
already fully coded from the prior session — the actual gap was that neither
screen was in `routes.tsx`'s `BUILT` table, so `/money/daily-cash` and
`/money/bank` 404'd/redirected despite already showing in the sidebar. Fixed:
added both imports + route entries. Also added a static, non-interactive
roadmap note on Bank Reconciliation (`data-testid="bank-api-roadmap-note"`)
acknowledging the user's stated wish for a future direct bank-API sync ("using
file upload for now — direct bank API sync is on the roadmap once your bank
provides API access") — deliberately not a fake button, just an honest
acknowledgement; `finledger.reconciliation`'s own module docstring already
notes the parser/matcher split so a real bank API feed would plug in without
a rebuild. Self-verified backend via curl: logged in as `accounts1`, read
real daily-cash figures, uploaded a CSV, confirmed the matcher correctly
excludes an already-matched `CashLedgerEntry` from later candidates
(append-only, no double-matching), confirmed `ignore` action works.
Also fixed an unrelated environment issue hit while smoke-testing: this pod's
inotify watch limit (`/proc/sys/fs/inotify/max_user_watches`, read-only,
cannot be raised) was exhausted, crash-looping the vite dev server with
`ENOSPC`. Fixed in `vite.config.ts`: `server.watch = { usePolling: true,
interval: 300 }`, which bypasses inotify entirely. **If a fresh pod hits the
same `ENOSPC` crash-loop again, this is already fixed in committed config —
no action needed unless the fix itself was reverted.**
`testing_agent_v4` (iteration_36): 100% pass, frontend-focused (backend
pre-verified via curl) — login/sidebar nav, Daily Cash date picker + refetch
+ empty-day state, Bank Reconciliation upload → imports table row → lines
table, all 5 status tabs, link/unlink/ignore full round-trip, roadmap note
renders, zero console errors, no regression on Cash Ledger/Vendor Ledger/
Partner Dues/Partner Billing. Also explicitly investigated and could **not**
reproduce a "stuck on 'Loading KDPS…' forever" concern the main agent raised
from its own screenshot-tool session (that tool's Playwright wrapper was
returning unawaited coroutines from several sync-looking calls this session —
a tool/env artifact, not an app bug; confirmed by clean backend curl results,
clean `vite`-transformed source with no build errors, and the testing agent's
own clean Playwright pass).

**Testing.** Backend: `pytest outbound masters core/tests tests/test_outbound_*
tests/test_cross_store_*` all green (run in the `/opt/kdpsvenv` venv, budget
~90–150s per batch, the sandbox's own command timeout — not pytest — is what
kills a same-call run past ~120s, so give it a generous explicit `timeout` or
background it with `&`/log file and poll). Frontend: `tsc --noEmit` clean,
`vitest run` — `navConfig.test.ts` (55), `routes.test.ts` (11, one updated for
Distribution no longer being a legacy redirect), `pageVocabulary.test.ts` all
pass. Pre-existing, unrelated to this session: 36 `src/till/*` vitest failures
in this pod (`navigator is not defined` — jsdom environment gap, not code).
`testing_agent_v4` ran two passes (`iteration_29.json` found one blocking
placement bug in the Partner Billing page's permission gate, fixed;
`iteration_30.json` confirmed the fix, 100% pass, no open issues).
