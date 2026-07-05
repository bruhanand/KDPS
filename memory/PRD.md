# KDPS Operating System — PRD / Build Memory

## Problem statement
KDPS Lifestyle Pvt Ltd is a multi-brand apparel retailer operating stores across
**Bihar & Jharkhand** (one PAN / one legal entity / two state GSTINs). We are building a
**deterministic retail ERP** ("KDPS Operating System"): documents write append-only
ledgers, Tally remains the statutory book, AI is suggest-only at the edges. The repo's
`docs/` folder holds the full plan (constitution `CONTEXT.md`, 12 rules, 7 ADRs, a
191-page application map across 14 modules).

## Current state — 5 July 2026 (read this first)
The foundation **and** the first business layer are **built and merged to `main`**, auto-deploying to a **Render alpha** (Postgres 16 + Django API + React PWA). Everything below this section is a **chronological build log**: the earliest (28 Jun) entries describe superseded money mechanics (stock value + auto-bill at **BASIC×qty**); those were **rebuilt to P RATE + commercial-model liability** in the 30-Jun Phase C/E remediation. Treat this section as the source of truth for status.

- **Landed (git):** PR #31 merged the Emergent export to `main`; PR #33 + #34 merged the `harden/green-and-security` sprint (money-path + security + CI green); PR #35 seeded the PT-mapper master data on Render. `main` is the alpha of record; `emergent` (exports) and `dev` (hand changes) PR into it (3-branch model). *(Corrects the "Deployment readiness check (28 Jun)" section below — deployment is live on Render, not blocked on MongoDB / a missing git remote.)*
- **Built on `main`:** kernel `core` + 9 apps (`masters` `accounts` `files` `vendors` `inbound` `ptmapper` `stockledger` `finledger` `aiagents`); React/TS PWA with ~12 wired screens + ~20 "coming soon" stubs.
- **Money path — remediated (Phases A–F of the 30-Jun review, all on `main`):** P RATE valuation (not BASIC), commercial-model liability branching (owned → bill at PT; SOR/consignment → never a payable at PT; direct → GRNI), a balanced value voucher on every PT inward via `post_entries`, GRN + PtFile reparented onto `core.Document`, Books-Health/trial-balance endpoint (`GET /api/finledger/health`). Full backend suite green on real Postgres.
- **Active dev moved Emergent → Claude Code (30 Jun)** — Emergent parked, not cut; repo kept portable.
- **PT-mapper fed + hardened (1 Jul, PR #34):** 9 brand profiles + normalisers + big seed; seeded on Render (PR #35). Fill rates ≈ BRAND 86% / SIZE 87% / SEASON 67% / COLOR 47%. MUFTI COLOR gap resolved.
- **Store analysis (2 Jul, commit 9b50b30):** JSL store deep-dive (business analysis + 16-measure dashboard, HTML+PDF) + a reusable `store-dashboard` skill under `.claude/skills/`.
- **Inbound overhaul batch — merged on `main` (3 Jul, #44–#49):** the whole branded-vs-non-branded inbound programme landed — `Grn.kind` discriminator (#44), non-brand PT authoring + GRN↔PT linkage backend (#49), the Stock-Receive / PT-File-Operation UI restructure (#45/#46), location-aware inward posting (#47), and the Codex correctness fixes (#48). Brand PTs now link to a received invoice/GRN at upload; non-branded arrivals are authored from a GRN. See the dated sections below.
- **PWA / security batch — merged on `main` (3–4 Jul, #55–#60):** mobile off-canvas sidebar (#55), demo-login Store-manager chip + auto-submit (#56/#60), the 403 auth-race fix (#57), the live-API test-hygiene gate (#58), and role-guarded client routes (#59). #57/#59 improved the auth/route posture — #59 hides + guards finance/RBAC-admin shells client-side — though the two alpha caveats (demo creds on the public Render alpha, JWT/refresh in `localStorage`) still stand and the backend 403 remains the real boundary.
- **Known alpha caveats:** (1) `finledger` vendor/cash ledgers are still single-entry running balances — only the PT-inward path is true double-entry / in the Σ=0 trial balance; (2) two security items **deferred by decision** — demo creds seeded on the public Render alpha, JWT/refresh in `localStorage`. Five money-critical GST items still await a CA ruling before live money.
- **Dark mode — merged on `main` (4 Jul, PR #61):** three-way Light/Dark/System theme for the whole PWA; light theme unchanged byte-for-byte (dark is one CSS override layer). This is `HEAD` of `main`. See the dated section below.
- **Not built:** selling/POS, offers, payments/settlement, transfers, returns, Tally sync, analytics, store open/close.


## Phase 0 — Emergent environment bring-up: DONE (Emergent session) ✅
The app now RUNS in the Emergent container (previously down: no Django in venv + no Postgres). Actions taken:
- Installed PostgreSQL 15 (apt) and made it **supervisor-managed** via new `/etc/supervisor/conf.d/postgresql.conf` (autostart, survives restarts). Created role `kdps` (SUPERUSER) + db `kdps_dev` matching `DATABASE_URL`.
- Installed Django 5.1 + psycopg + DRF + simplejwt + drf-spectacular + cors + whitenoise + openpyxl/xlrd/pyxlsb into the served venv `/root/.venv` (py3.11). `aiagents` is NOT in INSTALLED_APPS so litellm/emergentintegrations (already present) aren't needed at boot.
- Ran `migrate` (incl. pg_trgm) + `seed_foundation` + `seed_ptmapper`. Restarted backend.
- **Verified:** local + external login → 200 (JWT); external authed `/api/masters/stores` returns seeded Bihar/Jharkhand stores; frontend renders; CORS clean; console shows only Vite connect.
- App URL: `https://bookstore-erp-1.preview.emergentagent.com` (also reachable via APP_URL host `4c10e8e1-…`). Both route to this backend. Frontend `.env` REACT_APP_BACKEND_URL left as-is (`kdps-delivery-check…`, confirmed routing to this container).
- One-command re-provision script: `/app/scripts/dev-bootstrap.sh` (idempotent).
- NOTE: this container uses PostgreSQL for KDPS; MongoDB also runs (platform default) but is unused by the app.

## Phase 1 — re-scoped to the BRANDED flow (Anand steer, Emergent session)
User clarified the canonical branded flow (non-branded deferred): brand↔supplier (one brand can have many suppliers); **one booking can span multiple stores** for one brand (goods go to stores); receive at store (branded) or warehouse (branded+non-branded); brand sends PT file → mapped to KDPS format → sent to Patna → Patna inwards ("data becomes true") → item scanned into POS at store → sold (scan on sale) → return/defect per policy. Re-planned Phase 1 = harden this branded spine end-to-end: F1 (unify GL+vendor/cash), F2 (GRN qty rule), F3 (audit log), PLUS model-gap decisions: **multi-store booking** (today Booking has a single `destination_store`; BookingLine has no store — GAP), **brand↔multi-supplier** (Vendor↔Brand M2M exists; booking/UI assume one), and starting the **return-window/allowance policy clock** (commercial model is snapshotted, but window/allowance/30-15-7 alerts are NOT built). Return/defect EXECUTION (exchanges, GR return, SOR season-end, V-flip) stays Phase 3 (Outbound). Vision confirmed by user: full ERP + POS + analytics + accounting/finance/money-flow, Tally as one-way outer edge, bank integration for payments, plus an HR/payroll layer later.

## Review — Emergent session (June 2026): planned-vs-built + phased plan (READ)
A full planned-vs-built reconciliation was produced this session, focused on the **rules of the process / data-flow correctness** (user's priority = harden & stabilise before new modules; build continues on Emergent). Deliverable: `docs/implementation-plan/KDPS-Review-and-Phased-Plan.html` (HTML, house style). Key findings:
- **Built & correct:** kernel (paise, append-only triggers, doc FSM, gap-free series, balanced `post_entries`, value GL), auth/RBAC, masters, PT-mapper, stock ledger + on-hand. The document→stock→value-GL path is immutable and self-balancing.
- **F1 (P0):** vendor/cash ledgers are single-entry, bypass `post_entries` — payments/cash never hit the value GL, and the payable is double-booked (GL leg + finledger BILL). Trial balance ties only on the inbound path. **Fix first.**
- **F2 (rule to lock):** GRN writes NO ledger quantity — the "two-step inbound (GRN=qty, PT=value)" is effectively single-step at PT; received-not-inwarded stock is invisible to on-hand. Decide the rule.
- **F3 (P1):** no append-only audit_log — Rule 10 only partially met (created_by/posted_by FKs, but no who/why/when/reason edit trail). Controls "Audit Trail" is a stub.
- **F4 (P1, mitigated):** masters mutable, not SCD-2 (only GstSlab is date-effective); mitigated by doc snapshots.
- **F5 (CA-gated):** GST not split/posted at inbound (no INPUT_GST leg); P RATE taken as cost directly.
- **F6:** Booking sits outside the Document FSM (conscious) — pair with audit + close/cancel-with-remark.
- **ENVIRONMENT BLOCKER:** this Emergent container runs **MongoDB, not PostgreSQL**; the served venv has **no Django** (backend down, :8001 dead; Vite :3000 up). KDPS requires Postgres. Building here needs a **Phase 0** bring-up (install PG16, create kdps_dev, install deps, migrate, seed, restart).
- **Phased plan:** P0 env bring-up → P1 hardening (F1/F2/F3) → P2 close inbound loop → P3 outbound/selling → P4 offers → P5 payments/money-in → P6 Tally → P7 controls → P8 analytics/AI. Not built yet: outbound, offers, payments-workflow, analytics, Tally, POS integration, controls.


## Implemented — Dark mode for the PWA (4 July 2026) ✅
Whole-PWA dark mode. Scope confirmed with Anand: **PWA only** (all wired screens + shell +
Login); `docs/` HTML + `DASHBOARD.html` + Django admin out of scope; **no backend work**.
Branch `dark-mode-project-plan`, merged to `main` as PR #61 (this is `HEAD`).

**Hard constraint (honoured): the light theme did not change by a single byte.** The locked
"Warm" palette stays; dark is a pure override layer. Every swept literal was replaced by a
bridge token whose *light* value is byte-identical to the old literal.

**Mechanism (no React Context):** a tiny `src/theme/theme.ts` + `useSyncExternalStore` hook.
The theme lives on `document.documentElement[data-theme]` (a global), applied before React
mounts. Preference (`light|dark|system`) persists in `localStorage` under **`kdps-theme`**
(matches the other alpha prefs `kdps-sidebar-width` / `kdps-nav-item-order`). Default =
**follow device**, live-updating via a `matchMedia("(prefers-color-scheme: dark)")` listener;
a `storage` listener gives multi-tab sync. The store snapshot is a composite
`preference|resolved` string so `useTheme().resolved` re-renders on an OS flip under the
"system" preference (a preference-only snapshot stays `"system"` and React's Object.is bailout
would leave it stale — this was a review finding, fixed).

**No-FOUC:** an inline IIFE in `index.html` sets `data-theme` + the `theme-color` meta from
localStorage/matchMedia before the CSS `<link>` loads (verified in the prod build's head order).
`color-scheme: light|dark` so native controls (scrollbars, date inputs, selects) follow.

**CSS:** dark palette is a single `html[data-theme="dark"] { … }` block in `index.css` (warm
charcoal, hue ~35–40°, never blue-black). Bridge tokens added to `:root`. Two gotchas encoded:
(1) **`--navy` is dual-use** — split into `--navy` (text role, becomes light periwinkle in dark)
vs `--navy-fill`/`--navy-fill-hover` (solid fill under white text, stays dark) so white text
never lands on a near-white fill; (2) **`--rule`** was referenced ~8× but never defined (only
the fallback rendered) — now defined, fixing a latent hairline bug in dark.

**Toggle UI:** `src/theme/ThemeToggle.tsx` (lucide Sun/Moon/Monitor) — full form in the user-menu
dropdown (non-closing row) + a compact icon-only form top-right of Login (Login renders outside
AppShell, so dark must be reachable before sign-in). `--hero-navy` is theme-invariant (login
brand panel stays deep navy in both themes).

**Tests:** `src/theme/theme.test.ts` — pure `resolveTheme` + node-env side-effect tests (stubbed
`window`/`document`/`localStorage`/`matchMedia`, per-test module reset) covering persistence,
data-theme/theme-color mutation, the system-flip snapshot change, explicit-preference-ignores-OS,
and cross-tab storage sync. Frontend suite 11 → 17 passing.

**Files:** new `src/theme/{theme.ts,theme.test.ts,ThemeToggle.tsx}`; modified `index.html`,
`src/main.tsx`, `src/index.css`, `src/shell/{AppShell.tsx,AppShell.css}`,
`src/components/Combobox.css`, `src/pages/{Login,Home,Booking,PtMapper}.css`,
`src/pages/{Login,Home,StockLedger}.tsx`. **Verified:** `app/frontend` `npm run ci`
(tsc + vitest) + `npm run build` green; no backend changes.

**Follow-ons (out of scope, noted):** backend `theme_preference` on the User model once a
settings surface exists; a PWA `manifest.json` (none exists today — unrelated gap this surfaced).
**New rule for future work:** every color must be a token; dark overrides live in the single
`html[data-theme="dark"]` block — an inline hex will silently break dark.

## Implemented — Login demo-login fixes: Store-manager chip + auto-submit (3–4 July 2026, #56 + #60) ✅
Two small `Login.tsx`-only fixes to the six demo-login quick-login chips, grouped here.

**#56 — Store-manager chip (fixes #39 doc drift):** issue #39 reported DEPLOY.md documented
a `deo.manager` store login that QA couldn't find. On investigation the premise was **stale** —
both `deo.manager`/`store_manager` and `deo.cashier`/`store_staff` have **always** been seeded
(`seed_foundation.py`, idempotent on every deploy), DEPLOY.md was already correct (e7643c2), and
a live login against the Render alpha returned 200. The only real drift: the login page listed
only `deo.cashier`. Added a "Store manager" demo entry so seed, DEPLOY.md and the login page all
agree. No seed/DEPLOY.md change.

**#60 — chips auto-submit (fixes #40):** the chips only called `setUsername`/`setPassword`, so a
click filled the form and stopped (read as a broken button). Extracted the login into
`doLogin(u, p)` called with the literal demo creds — one click now signs in, dodging the
stale-state problem of submitting right after a `setState`. Chips still populate both fields
(so the user sees which creds were used / can retry) and now carry `disabled={busy}` so a
double-click / second chip mid-login can't fire a parallel request.

**Files:** `app/frontend/src/pages/Login.tsx`. **Verified:** `app/frontend` `yarn ci`
(tsc + vitest) + `npm run ci` green; manual UX verify (frontend has no DOM-test setup).

## Implemented — Role-guard client routes so scoped users can't load finance/admin shells (3 July 2026, #59) ✅
Any authenticated user could load any page shell by typing the URL — `ProtectedRoute` checked
**authentication but not authorization**. This adds **defense-in-depth + honest UX**; the backend
403 on the data stays the real security boundary (alpha stance).

**Frontend:**
- New **pure** guard `auth/routeAccess.ts` — a **longest-prefix** rule table mapping routes →
  required nav_group(s) + an optional finer role gate, mirroring the backend constants
  `FINANCE_ROLES` (finledger) and `RBAC_ADMIN_ROLES` (accounts). Superusers pass; unknown routes
  **default-allow** (harmless "coming soon" stubs). A follow-up review fix lowercases the pathname
  before matching (React Router matches case-insensitively, so `/LEDGERS/VENDOR` had bypassed the
  guard into default-allow).
- Denied routes render an `AccessDenied.tsx` card **inside** the AppShell (keeps the URL for support
  screenshots) rather than a silent redirect.
- Sidebar (`navConfig.ts`/`AppShell.tsx`) gains optional `roles` on `NavItem` and **hides** the
  finance-only ledgers (Vendor/Cash) + RBAC-admin pages (Users & Roles, Users & RBAC) from roles
  lacking access — so the guard doesn't turn an existing empty page into a surprise card.
- `VendorLedger`/`CashLedger` deduped off their ad-hoc finance-role arrays onto `FINANCE_ROLES`.

**Tests:** `auth/routeAccess.test.ts` — a role×route matrix over `canAccess` (incl. the mixed-case
case), via a **new vitest runner** (the frontend had none) wired into `ci:frontend`. **Files:** new
`auth/{routeAccess.ts,routeAccess.test.ts,AccessDenied.tsx}`; modified `auth/ProtectedRoute.tsx`,
`shell/{navConfig.ts,AppShell.tsx}`, `pages/{VendorLedger,CashLedger}.tsx`, `package.json`/`yarn.lock`.

## Implemented — Test hygiene: gate live-API suites off shared DBs, kill the dead Emergent origin (3 July 2026, #58) ✅
The black-box HTTP suites under `app/backend/tests/` hardcoded the retired Emergent preview origin +
`localhost:8001` and wrote **undeletable** rows (masters, documents, append-only ledger/GL posts) to
whatever `REACT_APP_BACKEND_URL` pointed at. During 2-Jul QA that meant **6 false "failures"** and junk
`ZZ*` brands left on the live Render demo, which then broke the next run's exact-count asserts.

**Fixes:**
- `tests/conftest.py` is now the single **wholesale remote-target gate** — it skips ALL live items when
  the target is not localhost and not cloud CI, unless `KDPS_TEST_ALLOW_REMOTE=1` is set deliberately
  (masters has no DELETE, Season has no `is_active` — teardown can never be complete, so confine the
  writes instead).
- New registered `local_backend` marker (`--strict-markers`) skips the manage.py-subprocess / direct-CORS
  tests against any non-local target even under the opt-in.
- Default base URL + every hardcoded origin → localhost; the Emergent host is gone from
  conftest/iter10/12/13/refactor_regression.
- `test_foundation` exact master counts → **seeded-subset** asserts (immune to accumulated junk);
  scope-derived `deo.cashier` asserts stay exact.

**Verified:** `npm run ci:backend` green (**285 passed, 63 skipped**); the full live suite booted against a
throwaway seeded server and run **twice against the same DB** — green both times (the ZZ-junk failure mode
is gone). **Ops follow-up (not code):** hand-clean the residual `ZZ*` junk already on the Render demo DB.

## Implemented — Fix transient 403 auth race on rapid login→action (3 July 2026, #57) ✅
QA of the Render alpha (issue #38): a fast login→immediate-action burst logged 403s on the first API
calls. Root cause = **prior-session leftovers racing the new session**, not an unsettled cookie — three
converging **frontend-only** defects (backend logout/blacklist/cookie-clear already work once logout is
authenticated).

**Fixes:**
- **Single-flight `/auth/refresh`** — N concurrent 401s share one refresh call so the rotating refresh
  token is spent once (the backend blacklists after rotation); `withCredentials` keeps rotated cookies.
- **Guarded clear** — on refresh failure, only `tokens.clear()` if `tokens.refresh` still equals the
  captured stale token (a losing racer can't wipe a fresh re-login); on real expiry it emits a
  `kdps:session-expired` event for a clean logout instead of a broken page.
- **Eager-capture logout** — reads access/refresh at call time and passes an explicit `Authorization`
  header, surviving the request-interceptor microtask so logout actually blacklists + clears cookies.
- **`AuthContext` session epoch** — login/logout/expiry bump a ref; the mount-time `/auth/me` bootstrap
  is StrictMode-safe and only mutates state when its epoch is current, so a slow prior bootstrap can't
  clobber a fresh login. A `kdps:session-expired` listener redirects to `/login` via `ProtectedRoute`.
- Deleted the dead `openApiClient` (cookie-only, zero usages) and dropped `openapi-fetch` (kept the
  `openapi-typescript` devDep that generates `api-schema.ts`).

**Files:** `lib/api.ts`, `auth/AuthContext.tsx`, `package.json`/`yarn.lock`. **Verified:** `npm run
ci:frontend` (tsc) + build green; manual in-browser repro per the plan's script (no vitest — this predates
the #59 runner).

## Implemented — Mobile off-canvas sidebar (3 July 2026, #55 + first cut of the live-API gate) ✅
Phones run the system in the browser/PWA (CLAUDE.md), so a phone-width layout is a pre-real-use
requirement (issue #36): at 375px the fixed 258px sidebar left ~117px for content, clipping the dashboard
headings + KPI tiles.

**Frontend (CSS-only, desktop markup unchanged):** a **768px** breakpoint below which the sidebar becomes a
fixed **off-canvas drawer** (`width min(82vw, 300px)`, overriding the user-resizable inline width), toggled
by a topbar **hamburger** and closed by tapping the backdrop or any nav link; the desktop resizer is hidden.
Topbar compacted on mobile (search hidden, user name → avatar, store-switcher truncated; dropdowns become
full-width fixed panels). **Files:** `shell/AppShell.tsx` (`mobileNavOpen` + hamburger/backdrop/close-on-nav),
`shell/AppShell.css` (mobile media-query block).

**Test infra (bundled in this PR):** the **first cut** of the live-API gate in `tests/conftest.py` — probes
the target once per session with a real demo login; healthy → suites run, unreachable/unseeded → the live
modules skip with an actionable reason; disabled under `CI` so cloud fails loudly. (Hardened into the
wholesale remote-target gate by #58.) **Verified:** headless at 375×812 (drawer open/close, nav-tap closes)
+ 1280×720 (desktop unchanged); frontend gate (tsc) green.

## Implemented — Inbound experience restructure: Stock Receive + PT File Operation (3 Jul 2026) ✅
UX reorganisation (step 1 of a larger UX overhaul — deeper simplification is a later session).
Decisions D1–D4 confirmed with Anand; scope is **UI reconstruction + renaming + wiring the
invoice↔PT link only** — no change to receiving/posting behaviour or the money path. Branch
`implement-inbound-plan`, merged to `main` (PRs #45/#46).

**Renames (cosmetic):**
- **"Inbound" → "Stock Receive"** (nav + page). It is *purely receiving*: per-store pending
  bookings, receive-against-a-booking, direct (booking-less) receipt, and the company invoice
  upload. `navConfig.ts` (Store Ops "Receive"→"Stock Receive", Documents "Inbound (GRN / PT)"→
  "Stock Receive"), `Inbound.tsx` heading + back-links; routes unchanged (`/inbound`,
  `/store/receive` still resolve to `InboundPage`).
- **"PT Mapper" → "PT File Operation"** (`navConfig.ts`, `PtMapper.tsx` header + the two detail/
  queue back-links; `Home.tsx` warehouse card sub-copy).

**Stock Receive = receiving only:** the warehouse work queue ("arrivals awaiting PT" + "Make PT
file") was **removed** from this page. Lifted `InboundQueueCard` + `useInboundQueue` + `useMakePt`
out of `Inbound.tsx` into a shared `components/InboundQueueCard.tsx` (GRN detail still uses
`useMakePt`).

**PT File Operation = two sub-tabs on one page** (D1=A; internal state synced to `?tab=mapper|making`,
default `mapper`):
- **PT File Mapper** (branded) — **invoice-first entry (D3):** pick the received invoice (from
  `GET /inbound/grns`, filtered to rows with an `invoice_number`) → enter mapping mode → upload the
  brand PT, which is linked to that GRN. Escape hatch "Map without an invoice" preserves the old
  behaviour. File list filtered to `source !== "invoice"`. Keeps the Learning-proposals +
  Unmapped-queue header links.
- **PT File Making** (non-branded) — hosts the **moved** work queue + "Make PT file". File list
  filtered to `source === "invoice"`.

**Backend (small, additive):** `PtFileListCreateView.create()` accepts an optional `grn` id and sets
`pt.grn` on the created file, guarded by the **one-live-PT-per-GRN** check (409 with `pt_file_id` if a
non-cancelled PT already exists; 404 if the GRN is missing). The RAN-WH posting restriction is **not**
applied here — linking a brand PT to a store-received GRN is a reference, not a posting, and branded
goods legitimately land at stores. No serializer/model/migration change (`grn`/`grn_number` already
exposed; the PT detail page already renders the `GRN {n}` chip).

**Tests:** `tests/test_inbound_pt_authoring.py` extended — brand PT links at upload
(`pt.grn == grn`), a second link on a live-PT GRN → 409 (points at the existing PT), upload without
`grn` still works, missing GRN → 404. **Verified:** `pytest` link + ptmapper/inbound suites green on
real Postgres; `makemigrations --check` clean; frontend `tsc --noEmit` + `vite build` green.
*(The pre-existing `test_iteration9/10/13` live-`:8001`-server failures are environmental, unrelated.)*

## Implemented — Location-aware inward posting (money path, issue #47) (3 Jul 2026) ✅
Fourth slice of the inbound branded-vs-non-branded overhaul (after #44 kind, #45 Stock-Receive
tabs, #46 PT-Operation wiring). **Money-path change, test-first.** Inward posting no longer books
every PT under the single hardcoded RAN-WH warehouse — **stock + value GL post at the GRN's actual
receiving location**, and the GSTIN follows the store automatically (`store.gstin` flows into every
stock row and the value voucher).

**Decision (D2/D5=B):** the target store is `pt.grn.store` when a GRN is linked, else RAN-WH
(back-compat for legacy grn-less uploads). Branded arrivals land at a **selling store** and post
under **that store's own GSTIN** (a Bihar store is a different "distinct person" from the Jharkhand
warehouse); non-branded arrivals post at their **warehouse** (any `store_type=warehouse`, not only
RAN-WH).

**Backend (no model/migration change):**
- `stockledger/posting.py` — `post_pt_inward` derives `store = pt.grn.store if pt.grn_id else
  RAN-WH`, keys the `VoucherSeries` on `store.code`; the old branded-blocking guard (refused any
  non-RAN-WH GRN) is **removed**. `reverse_pt_inward` mirrors under the **original** posting's store
  (`originals[0].store`) → same GSTIN + same PT series; `_allocate_number(store_code)` now takes the
  store. The booking-driven GL branch (owned → INVENTORY/VENDOR_PAYABLE; SOR/consignment →
  SOR_STOCK/SOR_CONTRA; direct → INVENTORY/GRNI) is **unchanged**.
- `ptmapper/models.py` — `PtFile.series_lookup()` returns the GRN's store code (per-location,
  gap-free PT numbering, `{FY}/{store}/PT/{n}`), matching the key the post uses.
- `ptmapper/views.py` — `PtFileFromGrnView` guard changed from "must be RAN-WH" to "must be a
  **warehouse**": from-GRN authoring is allowed at any warehouse, still blocked at a store (a
  store receipt is the branded/Mapper path, never authored).

**Tests:** `tests/test_location_aware_posting.py` (new) — branded PT on a store GRN posts at the
store under its Bihar GSTIN with a per-store PT number, value GL balances, on-hand lands at the
store; non-branded PT at a second warehouse (PAT-WH) posts under the warehouse GSTIN/series; a
grn-less upload still posts at RAN-WH; reversal mirrors the original store/GSTIN/series and flattens
on-hand; from-GRN authoring allowed at a second warehouse, blocked at a store. **Verified:** the
location-aware + inbound + ptmapper + phase-E/F + core suites green on real Postgres (167 tests);
`makemigrations --check` clean; `ruff` + `lint-imports` clean; `mypy` at baseline (no new errors).

**Go-live gates (not build blockers — tracked on #47):** ⚠️ **CA confirmation** for posting branded
stock under the store's own GSTIN is money-critical (a go-live gate, the alpha is correct-by-
construction); every store & warehouse must have a `gstin` set for posting to succeed; manual E2E
click-through on seeded dev (branded store→Mapper→post-at-store; non-branded warehouse→Making→inward).

## Implemented — Codex correctness fixes: PT-file scoping, GRN-link race, one-live-PT constraint (issue #48) (3 Jul 2026) ✅
Fifth slice of the inbound overhaul — the four defects Codex flagged on the branded/PT work.
**Fail-closed scoping + a DB backstop, test-first.**

- **#2 store scoping** (`ptmapper/views.py`) — the brand-PT upload path fetched the linked GRN
  unscoped and the PT-file list returned `PtFile.objects.all()`, both bypassing the `visible_store_ids`
  scoping `/inbound/grns` already enforces. Fixed: `create()` fetches the GRN through
  `scope_by_store(Grn.objects…, "store_id")` (a GRN outside the caller's scope → 404, fail-closed) and
  `get_queryset()` scopes the list by `grn__store_id`. Unrestricted (`scope=all`/superuser) users are
  unaffected; a NULL-grn legacy upload has no store → out of scope for restricted users.
- **#3 race → lock** (`ptmapper/views.py` `create()`) — the GRN-link + one-live-PT check + `PtFile`
  create are now wrapped in `transaction.atomic()` with `Grn.objects.select_for_update(of=("self",))`,
  mirroring the from-GRN path (the slow engine `process_file` runs after commit, never under the lock).
- **#3 constraint** (`ptmapper/models.py` + migration `0013`) — a partial `UniqueConstraint(fields=
  ["grn"], condition=~Q(docstatus=CANCELLED), name="uniq_live_pt_per_grn")` (spread alongside the
  inherited Document check-constraints) is the backstop so no code path or bulk script can leave a GRN
  with two live PTs; NULL grns exempt (Postgres). The migration **pre-checks** (`RunPython`) that no
  existing GRN already carries two live PTs and raises with the offenders if so, before the DDL.
- **#4 lockfile** — the stray `app/frontend/package-lock.json` deleted (yarn-only); `yarn.lock` already
  carries all-platform esbuild entries, so `yarn install --frozen-lockfile` is green on Linux CI.

**Tests:** `tests/test_ptmapper_scoping_race.py` (new) — a store-scoped user can't GRN-link or list
another store's PT (404 / empty), an unrestricted user is unaffected, a second live PT for one GRN
raises `IntegrityError`, NULL grns are exempt. **Verified:** the full hermetic backend suite green on
real Postgres (201 tests); `makemigrations --check` clean; `ruff` clean on touched source (migrations
excluded by config); `mypy` at baseline (254→253, no new errors); `yarn install --frozen-lockfile` +
`vite build` green. *(The pre-existing `test_iteration9/10/11/12/14/15` + `test_refactor_regression`
live-`:8001`-server failures are environmental, unrelated — confirmed identical on a clean baseline.)*

## Implemented — Render deploy fix: GRN-kind backfill vs the FSM trigger (3 July 2026, #44 regression) ⚠️→✅
The #44 merge (`e8ec1aa`) broke the API deploy on Render. The `0005_grn_kind` data migration
backfills `kind='non_branded'` on direct receipts with a bulk `Grn.objects.filter(is_direct=True)
.update(...)`. Real GRNs are **SUBMITTED** documents, and the kernel FSM trigger (`kdps_document_fsm`)
forbids any UPDATE to a submitted row except cancelling it — so on a database that already holds posted
receipts (the deployed alpha) the migration raised a `ProgrammingError`. It passed CI/tests only because
a fresh test DB has no submitted rows, so the UPDATE matched zero rows and the trigger never fired.

**Fix:** a `kind` backfill is schema evolution, not a change to a posted business fact — so the migration
temporarily **swaps the FSM trigger *function* body** for a pass-through, runs the UPDATE, then restores
the real guard in a `finally`. Swapping the function (not `ALTER TABLE … DISABLE TRIGGER`) needs **no table
lock**, so it works even when the table already has pending trigger events, and is fully transactional (a
rollback restores the guard). `DISABLE TRIGGER` was rejected: it raises "cannot ALTER TABLE … because it has
pending trigger events" whenever the table was written earlier in the transaction, which also made it
untestable. The guard is restored from `core.documents.document_fsm_function_sql()` (single source of truth).

**Test:** `tests/test_inbound_pt_authoring.py` extended with a SUBMITTED direct GRN in the backfill test —
reproduces the exact FSM `ProgrammingError` without the fix (verified red), passes with it. **Verified:**
kernel FSM anti-cheat + **263** non-live-server tests green, so the guard is provably restored. **Files:**
`inbound/migrations/0005_grn_kind.py`, `tests/test_inbound_pt_authoring.py`.

## Implemented — Grn.kind discriminator: branded vs non-branded (3 July 2026, #44) ✅
Makes the branded/non-branded split **first-class on goods receipts** (D2, plan Phase 1 + the backend
halves of Phases 2 & 3). Branded goods land at a store and the brand supplies the PT (warehouse maps it);
non-branded land at a warehouse and we author the PT ourselves.

**Decisions:**
- `kind` is a **STORED** field (unlike `status`, which the kernel forbids storing and keeps **derived**
  from linked PT files); default `branded`.
- **Backfill keys off `is_direct=True`, not booking presence** — `booking` is a `SET_NULL` FK, so a branded
  GRN whose booking was later deleted has a null booking yet `is_direct=False`; keying off
  `booking__isnull` would wrongly reclassify it. `is_direct` is the immutable receipt marker set at creation
  and matches the issue's "direct receipts → non_branded" wording (this was a Codex-review correction to the
  first cut).
- **Fail-closed guard:** a non-branded GRN whose target store is not a warehouse → **400** (any warehouse —
  no single-warehouse hardcode).
- `awaiting_pt` queue now lists **only** non-branded arrivals; branded arrivals wait for the brand PT via the
  Mapper (`GET /inbound/grns?kind=branded`). `?kind=` filters the GRN list atop the existing store scoping.

**Files:** `inbound/models.py` (`Grn.Kind` TextChoices + field), `inbound/migrations/0005_grn_kind.py`
(AddField + backfill RunPython), `serializers.py`, `views.py` (`_resolve_kind` guard + `?kind=` filter).
**Tests:** `tests/test_inbound_pt_authoring.py` — kind roundtrip/default, warehouse guard, filter, queue
exclusion, backfill incl. the deleted-booking case that must stay branded. **Verified:** **22 passed** +
pricing/sku suites green on real Postgres; `makemigrations --check` clean; `ruff` clean on touched files.

## Implemented — Non-brand PT authoring + GRN↔PT flow linkage (D2 backend) (3 July 2026, #49) ✅
The **backend** of D2's biggest v1 feature (complements — does not replace — the UI "Inbound experience
restructure" section above, which the same PR's UI half also carried). Connects the two previously
disconnected inbound islands (GRN fire-and-forget; the standalone PT-Mapper) and builds the non-brand PT path.

**Backend:**
- `GET /inbound/queue` surfaces **arrived GRNs awaiting a PT**.
- **Author a PT from a GRN** — `POST /ptmapper/files/from-grn/<id>` → `ptmapper/authoring.py`
  (`build_pt_from_grn` + invoice enrichment); `PtFile` gains `source` (`brand_file|invoice`) + a `grn` FK
  (`ptmapper/0011`, and `ptmapper/0012` seeds authoring vocabulary).
- **Auto-price authored lines** — `POST /ptmapper/files/<id>/price` via the pure, golden-tested
  `ptmapper/pricing.py` and a new `masters.CategoryMargin` master (`masters/0003`; `item=""` = **global 33%**
  default).
- `GET /masters/skus/lookup` for authoring.
- **Key deviation:** `Grn.status` is now **derived** (`Grn.effective_status`), not stored — the kernel
  docstatus FSM forbids UPDATE on a submitted document; the dead column is dropped (`inbound/0004`), same API
  keys, never stale. **Posting code (`post_pt_inward`) untouched.**

**Tests:** `tests/test_inbound_pt_authoring.py`, `tests/test_ptmapper_pricing.py`,
`tests/test_masters_sku_lookup.py`. **Open items** (tracked): MRP-formula confirmation vs a worked KDPS
example; per-category margins awaited from the client (global 33% until then); season-registry unification;
money follow-ons A/B deferred.

## Implemented — Self-improving PT-mapper: learn from human corrections (2 July 2026, #43) ✅
Every operator cell-correction becomes durable, auditable engine knowledge: **corrections → mine →
propose → human-approve → Lookup**. (Logged here as the 2-Jul-evening slice that preceded the 3-Jul inbound
overhaul above.)

**Models:** `CorrectionEvent` + `LookupProposal` (`ptmapper/0007`–`0010`, incl. the `pg_trgm` trigram
migration for fuzzy mining). **Engine:** `ptmapper/learning.py` — logs corrections, mines them into lookup
proposals, and is the writer that turns an **approved** proposal into a `Lookup` (a human-approval queue
gates every promotion). **Commands:** `ptmap_mine` + `ptmap_learning_report`, wired to a **daily Render
cron** (`render.yaml`, documented in `DEPLOY.md`). **API:** brand-scoped `suggest` + `rerun` endpoints.
**Frontend:** a `PtProposals` review screen + suggestion wiring into the `Combobox`.

**Decisions:** SENT = the trust gate (only trusted stages feed learning); re-run **preserves** manual edits;
**deterministic-only** mining for now (an LLM miner is deferred); suggestions are **brand-scoped by default**.
**Tests:** `test_ptmapper_{corrections,learning,mining,rerun,suggest,brand_scope}.py`.

## Architecture (locked by ADRs)
- **Backend:** Python 3.12 + Django 5.1 + Django REST Framework + drf-spectacular, **PostgreSQL** only.
  Kernel in `app/backend/core` (money-as-paise, append-only ledger w/ DB triggers, docstatus FSM,
  gap-free voucher series) — already built & green (75 tests).
- **Frontend:** React + TypeScript (Vite) PWA, typed against the DRF OpenAPI schema.
- **Auth:** custom JWT (djangorestframework-simplejwt), username/password, role + data-scope claims.
- **Modular monolith:** `core` < `masters` < domain apps (one Django app per module).

## Environment bridge (Emergent container — historical)
> **Historical.** Active dev moved Emergent → Claude Code (30 Jun) and deploy is the **Render alpha**;
> nothing references port 8001 any more. Current runtime: **Render** (deploy, per `DEPLOY.md`) + local
> `docker-compose` Postgres / `npm run ci` (dev, per `README.md`). Kept below as a record of the old container.
- Platform process manager (read-only supervisor) runs `uvicorn server:app` (→ `app/backend/server.py`
  re-exports the Django ASGI app, port 8001) and `yarn start` (→ Vite, port 3000).
- `/app/backend` & `/app/frontend` are **symlinks** to `/app/app/backend` & `/app/app/frontend`.
- Local PostgreSQL 15 (`kdps_dev`, user `kdps`); `DATABASE_URL` in `app/backend/.env`.
- Served deps live in `/root/.venv` (py3.11); canonical CI deps via `uv` (py3.12).

## User personas / roles (configurable; seeded working set)
Owner/Director, HO Ops/Buyer, Accounts/Finance, Warehouse/Inward, Store Manager, Store Staff/Cashier,
Data Steward, IT/System Admin. (AI service account deferred.) Scope dimension is separate from role:
all / entity / region / store_group / store, resolved over LegalEntity → GSTIN → Store.

## Design language — "Warm" (approved 28 Jun 2026)
Navy #1f2d4d + rust #c4623f on warm cream surfaces (paper #faf7f2, surface #fffdfb, beige rail #f1ece4);
per-layer colour bands; system fonts only + ui-monospace for IDs/money; navy-tinted shadows; 16px card
radius. Tokens centralised in `frontend/src/index.css`. Brand red #e53e35 reserved for wordmark/login/one CTA.

## Implemented — Vendor ageing, RBAC editor, `/inbound`, OpenAPI client, auth hardening (28 Jun 2026) ✅
- **Vendor-dues ageing:** `GET /api/finledger/vendor/ageing` now calculates outstanding vendor dues from the append-only vendor ledger using FIFO allocation, grouped into **0–30 / 31–60 / 60+** buckets. `/ledgers/vendor` shows ageing summary cards and vendor-level ageing table beside existing balances and entries.
- **Users & Roles editor:** `/masters/users` and `/edges/rbac` now provide an owner/IT-admin gated editor for creating/updating roles, nav groups, users, role assignments, active/staff flags, passwords, and store-scoped users. APIs added under `/api/auth/admin/{meta,roles,users}`.
- **GRN UI route:** `/inbound`, `/inbound/new`, and `/inbound/:id` are first-class routes for store and owner receiving flows; Store Ops and Documents nav now point to `/inbound`. Store users get locked receiving store, direct GRN creation, and detail navigation.
- **OpenAPI TS seam:** Generated `frontend/src/lib/api-schema.ts` from DRF schema via `openapi-typescript`; `api.ts` now exposes generated schema types plus `openApiClient` while preserving existing Axios compatibility. New RBAC screen uses the typed API helper.
- **Auth hardening from retest:** Added header-or-cookie JWT authentication (`CookieOrHeaderJWTAuthentication`), httpOnly `access_token` / `refresh_token` cookies on login/refresh, cookie clearing on logout, bcrypt-sha256 password hasher preference with PBKDF2 fallback, and `seed_admin` alias to existing `seed_foundation`.
- **Tested:** iteration_9 passed product flows; iteration_10 passed auth-cookie hardening + regression checks. Self-tests: Django check, targeted Python/TS lint, frontend typecheck, `pytest tests/test_iteration9_rbac_vendor_inbound.py` 8/8, browser smoke. **Known non-app issue:** external preview ingress still injects wildcard CORS headers on OPTIONS; internal Django CORS returns explicit origin + credentials.

## Implemented — Alpha-testing UI polish (28 Jun 2026) ✅
- **Login simplified:** left-side brand panel now shows only the logo mark + “KDPS Operating System”; descriptive copy and module chips removed.
- **Coming-soon placeholders:** unbuilt routes now show a clean “Coming soon” message with a short explanation of what that page will do; removed “191 pages across 14 modules” roadmap copy.
- **Configurable shell:** sidebar width is resizable via a drag handle and persists in local storage. Sidebar items inside each section can be drag-reordered for early alpha testing; group/section positions remain fixed.
- **Dashboard configurability:** home dashboard cards can be selected/hidden via “Configure dashboard”, reordered by dragging, and clicked to open a compact modal with a small visual graph + purpose text. Roadmap/build-status panel removed from dashboard.
- **Tested:** targeted JS lint clean, TypeScript typecheck clean, browser smoke verified login copy removal, dashboard config modal, dashboard card modal, coming-soon copy, and sidebar resizing.

## Implemented — Code review stability fixes (28 Jun 2026) ✅
- **PT mapper refactor:** split `ptmapper/engine.py::map_record()` into focused extraction, validation, price, resolution, row-building, and blank-column helpers while preserving output behavior.
- **Inbound GRN refactor:** split `_add_grn_line()` validation/parsing and booking-line variance checks into smaller helpers; added safe integer conversion for received/damaged quantities.
- **Stock ledger posting refactor:** split `post_pt_inward()` into PT-row entry construction, batch entry building, and PT-posted state update helpers; append-only posting behavior preserved.
- **Identity checks reviewed:** production files flagged by the report contain correct `is None` / `is not None` checks only; no unsafe `is "literal"` comparisons were found.
- **Auth type hints:** added explicit signature typing for cookie/header JWT authentication and removed unused import after tester feedback.
- **Tested:** testing_agent iteration_11 passed backend regression. Additional self-checks: Python lint clean, Django check clean, `tests/test_refactor_regression.py` 6/6, `tests/test_iteration9_rbac_vendor_inbound.py` 8/8, and `tests/test_iteration11_pt_posting_regression.py` 3/3.

## Deployment readiness check (28 Jun 2026) ⚠️ — SUPERSEDED
> **SUPERSEDED (see the "Current state" section at top).** This blocker is resolved: the app now deploys to a **Render alpha** (Postgres 16, from `render.yaml` on `main`) — it was never migrated to MongoDB, and a GitHub remote with merged PRs now exists. Kept below as history.
- **Deployment agent status:** FAIL for Emergent managed deployment because KDPS intentionally requires **PostgreSQL**, while the target managed platform health check expects MongoDB-only managed database support. This is architectural, not a runtime regression.
- **Checks passed:** supervisor config exists; frontend build passes; Django system check passes; ports are correct; CORS/CSRF settings are present; secrets/URLs are environment-driven; no mocked API layer.
- **Hardening applied:** frontend `REACT_APP_BACKEND_URL` now fails fast when missing; backend `DJANGO_SECRET_KEY`, `DJANGO_DEBUG`, `DJANGO_ALLOWED_HOSTS`, and `DATABASE_URL` now fail fast when missing.
- **Tested:** testing_agent iteration_12 passed deployment-readiness regression; pytest `tests/test_iteration12_deployment_readiness.py` passed 8/8 after backend env hardening.
- **Deployment blocker remaining:** provide/confirm external managed PostgreSQL `DATABASE_URL` or choose a major database migration strategy. Do not migrate to MongoDB without explicit architecture approval because append-only ledger guarantees are Postgres-oriented.

## Implemented — Repo deploy-readiness (no app logic changes) (Jun 2026) ✅
- **.gitignore bug fixed:** removed `/app/backend` and `/app/frontend` patterns that (anchored to repo root `/app`) silently ignored the *real* source at `app/backend/*` & `app/frontend/*`. Now tracked: `ptmapper` (16), `finledger` (9), `stockledger` (9) apps + new frontend pages (Bookings/Inbound/PtMapper/StockLedger/VendorLedger/CashLedger/StockOnHand → 15 files in `src/pages`).
- **Postgres data untracked:** `git rm -r --cached .pgdata` removed 1539 wrongly-tracked PG data files; `.pgdata/` added to `.gitignore`.
- **Missing server dep added:** `uvicorn[standard]>=0.25` added to `app/backend/pyproject.toml` (previously only in container `/root/.venv`). Verified a fresh `uv sync` venv boots `uvicorn server:app` and serves `/api/auth/login` (HTTP 200).
- **Fresh-clone build verified:** `uv sync` (55 pkgs, incl. openpyxl/xlrd/pyxlsb/uvicorn) + `yarn build` (tsc + vite, 1863 modules) both succeed from committed `uv.lock` / `yarn.lock`.
- **settings.py env hardening:** removed hardcoded `pt-mapper.preview...` host from CSRF default (now `https://*.emergentagent.com` wildcard, still covers preview); added additive env-driven `CORS_ALLOWED_ORIGINS`. The 4 deploy vars stay `os.environ[...]` fail-fast.
- **Backend start cmd (fresh clone, from `app/backend`):** `uv sync && uv run python manage.py migrate && uv run uvicorn server:app --host 0.0.0.0 --port $PORT`.
- **Tested:** testing_agent iteration_13 → backend 8/8 + frontend login→dashboard 100%, 0 CORS regressions. **GitHub push still pending — use the "Save to Github" feature** (no git remote configured in container).


## Implemented — Code-review remediation Phase A + B (30 Jun 2026) ✅
Acting on the LordCode implementation review (`implementation-review-2026-06-30`). The
review's critical/high findings were **independently verified** against live code AND the
locked decisions in `CONTEXT.md` (all confirmed; not false positives). User chose: do
Phase A (security) + Phase B (verification spine) now, then PAUSE before the money core.

**Phase A — security holes (exploitable now, no money rework):**
- **CORS:** the broad `*.emergentagent.com` + localhost origin regexes are now gated behind
  `DEBUG` (`config/settings.py`). In production (`DEBUG=0`) CORS is driven purely by the
  exact-origin `CORS_ALLOWED_ORIGINS` env allowlist — no credentialed wildcard on the shared
  preview domain. Preview (DEBUG=1) behaviour unchanged.
- **Fail-closed reads:** `scope_by_store` applied to all stock-ledger reads
  (`stockledger/views.py`: list/summary/on-hand). `finledger` vendor+cash reads now gated by a
  new `IsFinance` DRF permission (payables/ageing/cash are finance-only).
- **Money/role gates (`ptmapper/views.py`):** PT `post`/`reverse` restricted to Patna/HO roles
  `{accounts, owner, it_admin}`; `review/resolve` restricted to mapping stewards
  `{warehouse, data_steward, ho_ops, owner, it_admin}`. Role check runs BEFORE object lookup
  (forbidden→403 even for missing pk; allowed→404).
- **Append-only audit:** posted/sent PT can no longer be `DELETE`d (`PtFileDetailView.destroy`
  guards stage==MAPPING → 409 otherwise).
- **Booking write-path scope (`inbound/views.py`):** GRN create now scope-checks the booking
  (`_resolve_booking`, fail-closed by destination store) and resolves the booking line only
  within that booking — a payload can no longer mutate another store's booking line.
- **Seed hardening (`seed_foundation.py`):** demo users/sample-booking/credentials gated behind
  `SEED_DEMO` (default "1"; set "0" in prod); `set_password` now runs **only on user create** —
  a redeploy no longer reverts an operator-rotated password. `/admin` mount gated behind
  `DEBUG or ENABLE_DJANGO_ADMIN=1` (`config/urls.py`).

**Phase B — verification spine:**
- Deleted the bug-cementing assertions: `test_iteration11` no longer asserts "a vendor bill is
  always raised" (liability is commercial-model dependent — Phase E golden tests will own it);
  rewrote the two seed-revert tests (`iteration10`, `iteration12`) to assert the NEW correct
  behaviour (re-seed does NOT overwrite a rotated password) with self-cleaning `finally` restore.
- New `tests/test_iteration14_security_hardening.py`: finance-gated finledger reads, Patna-gated
  PT post/reverse, steward-gated review-resolve, store-scoped stock reads, PT delete guard.
- Fixed an order-dependent flake in `test_foundation::test_me_without_token_returns_401` (used a
  fresh session so a shared-jar cookie can't authenticate it).
- Added `.github/workflows/ci.yml` — Postgres service + kernel anti-cheat suites + API
  regression suites + frontend build (runs on push via "Save to Github"; not executed in-container).
- **Tested:** full backend suite green — **130 tests** (`tests/` + `core/tests`) pass deterministically;
  browser smoke: owner login → dashboard → stock ledger OK; Django check clean.

**New env vars (defaults preserve preview; set these for production):**
`SEED_DEMO=0`, `ENABLE_DJANGO_ADMIN=0` (omit), `CORS_ALLOWED_ORIGINS=https://app.kdps...` (exact),
`DJANGO_DEBUG=0`.

**PAUSED here for user review before the money core (Phases C–E).**

## Code-review remediation — Phase C + E DONE, D partial (30 Jun 2026) ✅
Labels below are the **code-review** phases (distinct from the older product phases C/D/E).

**Phase C — kernel posting primitive (DONE, 8 kernel tests):**
- `core/gl.py` — `GLEntry`, the append-only **value general ledger**: one balanced
  posting fans into ≥2 legs, signed paise (debit +, credit −), so a voucher sums to 0
  and the whole ledger's `trial_balance()` = Σ(amount) = 0. `GLAccount` codes
  (INVENTORY, VENDOR_PAYABLE, GRNI, SOR_STOCK, SOR_CONTRA, INPUT_GST, CASH).
- `core/posting.py` — `post_entries(doc, legs)`: the **sole** GL writer, balanced-or-fail
  (Σ=0, ≥2 legs, integer paise), all-or-none in one txn, dims snapshotted; `Leg`/`dr`/`cr`/`PostingRef`.
- `core/ledger.py` — `truncate_guard_sql`: `BEFORE TRUNCATE` trigger (binds even the
  superuser) + `REVOKE TRUNCATE`, applied to GL + stock + vendor/cash + probe tables
  (migrations `core/0005`, `stockledger/0002`, `finledger/0002`). Test-only escape hatch
  (`kdps.allow_truncate`) set per-connection by `conftest.py` so Django flush still works.

**Phase E — money slice rebuilt on `post_entries` (DONE, 5 per-model golden tests). Fixes C1/C2/C3:**
- **C2:** stock valued at **P RATE** (locked unit cost), not ex-GST BASIC; `P RATE ≤ MRP`
  enforced; **strict money** — an unreadable/missing/over-MRP cost raises `PtPostingError`
  → API **422** listing offending rows (no silent ₹0 valuation).
- **C1:** vendor liability branches by **commercial model** (booking snapshot): owned
  (Outright/Correction) → bill at PT; brand-owned (SOR/Consignment) → **never** a payable at PT.
- **C3:** every PT inward now posts a **balanced value voucher** via `post_entries`
  (owned → Dr INVENTORY/Cr VENDOR_PAYABLE; brand-owned → off-book Dr SOR_STOCK/Cr SOR_CONTRA;
  direct → Dr INVENTORY/Cr GRNI). Reversal appends the negated mirror of stock + GL + payable.
- `stockledger/posting.py` rewritten; `finledger.post_pt_vendor_bill` model-gated.

**Phase D — gap-free numbering DONE; full FSM reparent PENDING (design decision):**
- DONE: GRN + Booking numbers now via gap-free `VoucherSeries.allocate` (`26-27/<scope>/GRN|BK/<n>`),
  replacing the racy `count()+1` (review H5). Idempotent under concurrency.
- PENDING (needs user steer): reparent `PtFile`/`GRN`/`Booking` onto `core.Document` (docstatus FSM,
  DB immutability, `idempotency_uuid`, `select_for_update` on post, **reversal-as-cancel**).
  *Design finding:* Booking is a poor fit for freeze-on-submit (it is numbered at birth and mutates
  through fulfilment — status/received roll-ups), and PT reversal-as-cancel changes the
  current "reverse → back to 'sent' → re-post" correction workflow + frontend stage display.
  Recommend: fully reparent **PtFile** + **GRN** (clean fits); keep **Booking** a living master
  with gap-free numbering (+ optional `idempotency_uuid`). Awaiting confirmation.
- Tested: full suite **143 pass** (8 GL + 5 Phase-E golden + existing), live MUFTI PT post/reverse OK.

**Phase F (P1) — NOT started:** `sku` + `cohort(barcode,season)` masters; persisted per-unit
`unit_cost_paise` + DB `CHECK unit_cost ≤ mrp`; `MoneyField` on `*_paise`; materialised
stock-on-hand + indexes; fix silent `[:2000]`/`MAX_ROWS=8000` truncation.

## Phase F (P0) + Books-Health card + Master stewardship — DONE & TESTED (30 Jun 2026) ✅
Delivered the user-approved trio (a + b + c). All verified: backend **97 unit + 17 integration pytest pass**,
testing_agent **iteration_15** (frontend 6/6, backend 7 pass / 1 skip-by-design), curl e2e.

**(a) Phase F — identity & scale (P0):**
- **MoneyField everywhere:** `*_paise` columns now use `core.money.MoneyField` (refuses float/Decimal at the
  write boundary) — `vendors.Booking.estimated_value_paise`, `vendors.BookingLine.mrp_paise`,
  `masters.GstSlab.threshold_paise`, plus the new SKU/cohort/on-hand money columns. (`vendors/0002`, `masters/0002`).
- **SKU + cohort masters** (`masters.Sku`, `masters.Cohort`): barcode IS the SKU; a cohort = (barcode, season)
  holding the locked per-unit `unit_cost_paise` with a **DB CHECK `unit_cost ≤ mrp`**. Registered/refreshed inside
  every PT post (`stockledger.posting._register_identity`). Backfilled from the live ledger in `masters/0002`.
- **Materialised stock-on-hand** (`stockledger.StockOnHand`, `db_table=stockledger_on_hand`): indexed projection
  per (store × barcode), maintained inside each post/reverse (`_apply_on_hand`), backfilled in `stockledger/0003`,
  rebuildable via `manage.py rebuild_stock_on_hand`. `StockOnHandView` now serves all 3 groupings from it.
- **Truncation no longer silent:** PT reader flags `meta.truncated` + `row_limit` when a file hits the 8000-row cap
  (banner `ptfile-source-truncated-banner`); on-hand reports `summary.{lines,displayed,truncated}` (banner
  `onhand-truncated-banner`) — the old silent `[:2000]` drop is gone.

**(b) Books-Health card (P1):** `GET /api/finledger/health` (IsFinance-gated) returns trial balance (Σ GL legs = 0),
balanced flag, and the equation of state (Σ inventory+SOR vs Σ payable+GRNI+contra). Owner dashboard renders the
"Equation of state" panel (`trial-balance-panel`) — live: **Books tie · ₹0 · 8 vouchers · 16 legs**.

**(c) Master Data stewardship UI (P1):** create/edit for Stores/Brands/Seasons/GSTINs. New steward-gated CRUD
(`masters.IsMasterSteward` = owner/it_admin/data_steward; reads open) — ListCreate + Detail views, `/masters/{res}` &
`/masters/{res}/{id}`. Frontend `MasterPages.tsx` adds New/Edit editors + active toggle per registry (New/Edit hidden
for non-stewards e.g. store cashier). Soft-deactivate, never hard-delete (ledger-referenced masters).

**Phase F (P1) — NOT started (superseded above):**

## Phase D frontend verification — DONE (30 Jun 2026) ✅
- testing_agent iteration_14 → **frontend 100% (8/8 flows, 0 console errors, 0 bugs)**. Closes the
  last open item: confirmed the PtFile/Grn → `core.Document` reparenting renders correctly on the UI.
- Verified: computed `PtFile.stage` badge/stepper tracks docstatus across all 4 stages
  (mapping/sent/posted/reversed with labels Mapping (Warehouse)/Sent to Patna/Posted to system/Reversed);
  FSM-frozen posted/reversed files hide edit/send/post (only Reverse + Export + ledger link); role-aware
  action gating (Owner/Warehouse/Accounts) matches spec; store-cashier (deo.cashier) scope-locked
  (receive-store-locked, only DEO GRNs); fresh direct GRN minted gap-free `26-27/DEO/GRN/5`.
- No frontend code changes were required — serializers kept the same `stage`/`stage_label` shape the
  React pages already consume. **Code-review remediation Phases A–E + D reparent are now complete & verified.**

## Implemented — Vendor & Cash ledgers (append-only) (28 Jun 2026) ✅
- **New `finledger` app**: `VendorLedgerEntry` (accounts payable) + `CashLedgerEntry`, both extending
  `core.LedgerEntry` — append-only (ORM + `BEFORE UPDATE/DELETE` trigger on `finledger_vendor_entry` /
  `finledger_cash_entry`, verified blocks superuser). Gap-free vouchers via `VoucherSeries` under store_code
  'HO' (doc_types VEND / CASH). Sign: vendor +bill/−payment (Σ=payable); cash +receipt/−payment (Σ=on hand).
- **Posting** (`finledger/posting.py`, finance-only via `_is_finance`): manual Record Bill / Record Payment
  (payment auto-posts a paired cash-OUT) / Record Cash Movement; append-only reversals (a vendor-payment
  reversal also reverses its paired cash row). **Auto vendor bill**: `stockledger.post_pt_inward` now calls
  `post_pt_vendor_bill` when a PT file is posted *with a booking* (amount = BASIC×qty stock value); PT reverse
  calls `reverse_pt_vendor_bills`.
- **API**: `/api/finledger/vendor/{entries(paginated),balances,bill,payment,entries/:id/reverse}` and
  `/api/finledger/cash/{entries(paginated),summary,movement,entries/:id/reverse}`.
- **Screens**: `/ledgers/vendor` (`VendorLedger.tsx`) — payable summary, outstanding-by-vendor, paginated
  entries, Record Bill/Payment forms, Reverse. `/ledgers/cash` (`CashLedger.tsx`) — cash-on-hand by account,
  paginated movements, Record Movement (account select CASH/BANK/UPI), Reverse. Nav wired; finance-role gated.
- **Tested:** testing_agent iteration_8 → frontend 100% (bill/payment+auto cash-out, reversals, pagination,
  role gating: warehouse sees no posting buttons). Backend curl + append-only triggers verified directly.

## Implemented — Ledgers: pagination + Stock-on-Hand + nav (28 Jun 2026) ✅
- **Server-side pagination** on `GET /api/stockledger/entries` (DRF `PageNumberPagination`, page_size 50, scoped to this view only — `{count,next,previous,results}`); Stock Ledger page now has Prev/Next + "Showing X–Y of N".
- **Stock on Hand** screen (`/ledgers/stock-on-hand`, `StockOnHand.tsx`) backed by `GET /api/stockledger/on-hand?group_by=sku|brand|store` — live net position (Σqty>0) from the append-only ledger, with SKU/Brand/Store grouping tabs + summary cards. Cross-linked with Stock Ledger.
- **Ledgers nav wired**: added "Stock on Hand" item; Vendor/Cash Ledger remain intentional "Planned" placeholders (route via catch-all → ModulePage).
- **Tested:** testing_agent iteration_7 → frontend 100% (5/5: pagination, on-hand 3 groupings with consistent 241-unit total, cross-links, nav placeholders). Added `.catch` error surface on the on-hand fetch.

## Implemented — Code-quality refactor (28 Jun 2026) ✅
- Behavior-preserving refactor from a code review: split high-complexity functions into focused helpers —
  `engine.map_record` (`_map_prices`/`_map_season`/`_map_taxonomy`), `ptmapper.views.process_file` +
  `ReviewResolveView.post` (`_resolve_single`/`_resolve_taxonomy`/`_repropagate`), `inbound.views.create`
  (`_resolve_receiving_store`/`_build_grn`/`_add_grn_line`), and `seed_ptmapper.handle`. Removed dead code +
  unused import, added type hints. **Verified zero behavior change**: 84/84 kernel+foundation pytest, new
  `tests/test_refactor_regression.py` 6/6, ruff/django-check clean, seed reproduces identical counts
  (iteration_6, 100%). Note: the review's "3 undefined variables" and "35 is-vs-`==`" were tool false
  positives (all are correct `is None`/`is True/False`; changing them would be a regression) — not applied.

## Implemented — Phase E complete: append-only Stock Ledger posting (28 Jun 2026) ✅
- **First real business ledger over the `core` kernel.** New `stockledger` app: `StockLedgerEntry(LedgerEntry)`
  — append-only (ORM guard + `BEFORE UPDATE OR DELETE` DB trigger + REVOKE, verified blocks superuser
  UPDATE/DELETE). Self-describing rows (barcode SKU + brand/design/colour/size/season/item/HSN), signed
  `qty`, value `amount` = BASIC×qty in paise, `kind` (pt_inward / pt_reversal), gap-free `doc_number`.
- **Patna "Push into system"** (`POST /api/ptmapper/files/:id/post`, body optional `{booking_id}`) →
  `post_pt_inward`: mints a gap-free `PT` voucher for **RAN-WH** (`26-27/RAN-WH/PT/n` via `VoucherSeries`),
  writes one inward entry per KDPS row, optionally **reconciles a Booking** (matches KDPS DESIGN+SIZE to
  `BookingLine.style_code`+`size`, bumps `inwarded_qty`), locks the file. Verified: MUFTI 97 rows valued
  (₹814.25/₹1920.10…), booking inwarded 39→5 & 32→3.
- **Append-only correction** (`POST …/reverse` → `reverse_pt_inward`): mints its own PT voucher, writes a
  negative mirror of every live inward row, un-bumps the booking, returns the file to `sent` (fix & re-post).
  Verified net qty → 0 across the inward+reversal pair.
- **API & UI:** `GET /api/stockledger/entries` (`?pt_file=` / `?doc_number=`) + `…/summary`. New **Stock
  Ledger page** (`/ledgers/stock`, `StockLedger.tsx`): 4 summary cards + entries table (inward green /
  reversal red chips). PT detail gains a booking selector on post, a Reverse button, and a posted banner
  showing the voucher + booking + "View in Stock Ledger" (links by file → shows inward + reversals together).
- **Tested:** testing_agent iteration_5 → frontend 100%, 0 bugs (post±booking, reconcile banner, reversal,
  Stock Ledger page + filter, role gating). Backend curl + the append-only trigger verified directly.

## Implemented — Phase D Slice 2 + Phase E workflow: Readers & Warehouse→Patna workflow (28 Jun 2026) ✅
- **Legacy/binary readers** (`ptmapper/engine.py`): `read_sheets` now dispatches by extension **and** magic
  bytes — `.xls` via xlrd (OLE2), `.xlsb` via pyxlsb (Madura SAP), `.xlsx` via openpyxl, `.csv`; correctly
  routes mislabelled files (a `.xls` that is really `.xlsx`, a `.csv` that is OLE2). Excel serial dates in
  `.xlsb` decoded. `MAX_ROWS=8000` cap honoured. Deps added to `pyproject.toml`: openpyxl, xlrd, pyxlsb.
- **Workflow stages** on `PtFile`: `mapping` (Warehouse/Ranchi) → `sent` (to Patna HO) → `posted` (locked).
  Plus `manually_edited`, `sent_at`, `posted_at`. Resolve-propagation skips hand-edited/non-mapping files.
- **Hand-editable KDPS table**: warehouse opens Edit → every cell becomes an inline input → Save
  (`PATCH /api/ptmapper/files/:id/rows`, recomputes blanks/counts, sets `manually_edited`).
- **Send / Recall / Post / Export**: `POST files/:id/send` (warehouse→Patna), `POST files/:id/recall`
  (Patna sends back), `POST files/:id/post` (Patna pushes into system → **locks**), `GET files/:id/export.xlsx`
  (real .xlsx, KDPS 22-col order) alongside the existing CSV export. `rerun` is 409-guarded to mapping stage.
- **Frontend** (`PtMapper.tsx`): list gains Mapping + Workflow columns; detail page has a 3-step StageStepper,
  role-aware actions (owner=all, `warehouse`=edit/send, `accounts`=Patna recall/post on sent files only),
  inline edit grid, Excel+CSV download, stage banners. Large files render a 1000-row display cap (download
  for full set) to keep the DOM light.
- **Tested:** testing_agent iteration_4 → frontend 100%, 0 bugs across 11 scenarios (3 new readers via UI
  upload, edit→save, send, post-lock, recall, role gating for all 3 users, xlsx/csv export, regression).
- **NOT yet done (next P0):** "Push into system" currently transitions to `posted` and **locks** the record;
  it does **not yet write the `core` stock ledger**. That first stock-ledger write is the remaining Phase E work.

## Implemented — Phase D: PT File Mapper (Warehouse / Ranchi) (28 Jun 2026) ✅
- **Deterministic, table-driven engine — NO AI** (`ptmapper` Django app). Reads a brand PT file
  (.xlsx/.csv), detects the header row + data range, identifies the archetype profile (A generic /
  B Tally-Vistaar / C Ginesys PT-EMAIL), maps columns, normalises controlled fields via DB lookups,
  derives SEASON (from invoice date), NAG=QTY, MARGIN=(MRP−P RATE)/MRP×100, OUTPUT TAX=INPUT TAX,
  and carries BASIC / P RATE from source (money flagged, CA-gated per spec §5).
- **Lookup tables are the product:** seeded from KDPS's real Master Sheet via `seed_ptmapper`
  (970 controlled values, 592 brands, 23 colours, 135 sizes, 98 ITEM→sub/type, 30 taxonomy rules).
  Unmapped raw values go to a **review queue**; a human maps one (adds a Lookup/TaxonomyRule) and
  re-running re-maps every file — zero code change. COLOR vocab keeps price tiers (PREMIUM/ECONOMY).
- **API:** `POST /api/ptmapper/files` (upload+map), `GET files/:id`, `POST files/:id/rerun`,
  `GET files/:id/export` (CSV in KDPS 22-col order), `GET /api/ptmapper/review`,
  `POST /api/ptmapper/review/:id/resolve`, `GET /api/ptmapper/controlled?dimension=`.
- **Frontend** (`PtMapper.tsx`, Documents > PT Mapper): upload + files table, file detail with the
  wide KDPS output table (blank cells flagged amber) + Re-run + Export CSV, and the Unmapped queue
  (single-dim select resolve + 5-axis taxonomy resolve). Reachable by warehouse + owner roles.
- **Tested:** testing_agent iteration_3 → frontend 100%, 0 bugs. Verified resolve→propagate loop
  (DEAL unresolved 7→6→5). Backend verified via curl (MUFTI 97 rows; 88-BEIGE→CREAM re-mapped 15 rows).
- **Deferred to Slice 2:** `.xls`/`.xlsb` readers (Jockey/Madura, archetypes D/E/F) — currently return a
  friendly "not yet supported" message.

## Code-review triage (Jun 2026) ✅
- **"Tests not passing" — ROOT CAUSE FIXED:** prior testing iterations had dumped throwaway live-API files
  (`test_iteration16/17/18_*_live.py`, `test_iteration19_..._extract.py`) that **hardcoded a preview URL** and
  **wrote undeletable data to a shared DB** (the repo's conftest explicitly forbids this) — so they failed in any
  environment with a different `REACT_APP_BACKEND_URL`. **Deleted all 4**; authoritative coverage lives in the
  DB-backed golden tests (`test_finledger_f1_gl_unification.py`, `test_multistore_booking.py`). Suite: **296 passed / 63 skipped**.
- **#1 Circular import — FIXED + LOCKED:** extracted `process_file()` + helpers into `ptmapper/processing.py`
  (last round); this round installed **import-linter** and added a CI contract forbidding
  `ptmapper.processing/learning/engine/models/profiles → ptmapper.views` (**2 contracts KEPT, 0 broken**). Can't regress.
- **#1 Hardcoded test secrets — FIXED:** centralized the dummy password into `tests/_creds.py` (env-backed
  `TEST_PASSWORD`); no `password="x"` literal remains → 14 scanner findings gone at the source.
- **#4 `is` comparisons:** converted `is True/False` → plain asserts in `test_multistore_booking.py` (kept
  `is None`). ruff F632/F821 remain clean → the other flagged instances are false positives (`vendors/views.py:153`
  uses `in`, not `is`).
- **Confirmed false positives / declined:** seeded `random.Random(n)` in fuzz tests is correct (reproducible;
  `secrets` can't be seeded); complexity/length refactors of the verified F1 engine + PT authoring and editing the
  already-applied migration `masters/0002` declined (regression risk, no functional gain). Verified: ruff clean,
  `manage.py check` clean, testing_agent iteration_20 (100% backend, `retest_needed: false`).

## Implemented — Multi-store bookings: per-line `store` (Jun 2026) ✅
- **Model:** `BookingLine.store` (nullable FK → masters.Store, `SET_NULL`; migration `0003_bookingline_store`).
  Null = inherit the booking's `destination_store` default; both null = warehouse/HO. Kept `Booking.destination_store`
  as the booking-level DEFAULT (user choice: "default destination, override per line").
- **API:** `BookingLineSerializer` exposes `store` + `store_name`; create validates per-line `store` against real
  Store ids (unknown id → null, fail-safe). Querysets prefetch `lines__store` (no N+1).
- **Scoping (fail-closed, ADR-0003):** switched to ANY-LINE-IN-SCOPE — a store user sees / may receive against a
  booking if any line's effective destination (own store, else booking default) is in their visible stores
  (`inbound.views._booking_touches_stores` + `PendingBookingsView` Q-filter). **Direct receipts (no booking) keep
  their own GRN store-scoping — unchanged** (per user's explicit instruction).
- **Frontend:** `Bookings.tsx` — per-line Store dropdown ("Default" = inherit) + "Default destination store" header
  select; detail table gained a **Destination** column (inherited lines fall back to the default store name).
- **Seed:** BK-SS26-0001 is now a multi-store demo (shirts→DEO default, trousers→BKR).
- **Tests:** `tests/test_multistore_booking.py` (5 DB golden tests) + testing_agent iteration_17 (8 live-API + both
  frontend flows) → all pass, 0 defects.


- **F1 (P0):** vendor & cash subledgers are now unified into the single balanced value GL via
  `core.post_entries`. Manual vendor bill → `Dr SUSPENSE / Cr VENDOR_PAYABLE`; vendor payment →
  `Dr VENDOR_PAYABLE / Cr CASH` (one voucher, paired cash subledger row is detail only); standalone cash
  movement → `Dr CASH / Cr SUSPENSE` (in) / reverse (out). PT auto-bill stays `gl=False` (PT inward already
  books the payable) so the payable is booked exactly once — no double-booking. Reversals mirror the GL and
  refuse a second reversal (HTTP 409). Books always tie: `trial_balance() == 0`.
- **P1 — reconciliation proof:** `GET /api/finledger/health` now returns a `reconciliation` block asserting
  GL `VENDOR_PAYABLE` control == vendor subledger sum and GL `CASH` control == cash subledger sum, each with
  `reconciled` + `drift_paise`, plus a top-level `reconciled` flag. Finance/owner-only.
- **Tests:** `tests/test_finledger_f1_gl_unification.py` (8 golden-file DB tests) + testing_agent iteration_16
  (13 live-API tests) → all pass, 0 defects. Live flow verified: bill ₹1500 + payment ₹600 → payable ₹900,
  cash −₹600, drift 0, balanced+reconciled true. `pytest-django` installed into venv (already in pyproject dev group).


## Implemented — Phase 1 Inbound: Booking + Receive (GRN) (28 Jun 2026) ✅
- **Backend (Django apps):** `files` (DB blob storage), `vendors` (Vendor master + Booking + BookingLine,
  two-step human-in-the-loop draft→confirm), `inbound` (Grn + GrnLine, receive against a booking OR direct),
  `aiagents` (Gemini document extraction via Emergent universal key). Endpoints: `GET/POST /api/bookings`,
  `POST /api/bookings/draft` (AI), `GET /api/bookings/:id`, `GET /api/vendors`, `GET /api/inbound/pending`,
  `POST /api/inbound/invoice-draft` (AI), `GET/POST /api/inbound/grns`, `GET /api/inbound/grns/:id`.
- **Frontend:** `Bookings.tsx` (list / create with AI file-draft + graceful manual fallback / detail) and
  `Inbound.tsx` (GRN list + pending-bookings, New receipt: against-booking auto-prefill OR direct receipt,
  invoice AI prefill that degrades to manual, GRN detail). Routes wired in `App.tsx`; `/store/receive` → Inbound.
- **AI (Gemini, Emergent key):** booking Receiving Reader + store/warehouse Invoice Reader. Universal Key
  balance topped up by user (28 Jun 2026) — extraction verified (CSV read 2/2 lines @100% confidence).
- **Scoping:** fail-closed — store user (deo.cashier) sees a LOCKED store on receive + only their store's
  pending bookings; never warehouse/other-store data. Verified.
- **Tested:** testing_agent iteration_2 → frontend 100% (11 flows), 0 bugs. Backend verified via curl.

## Implemented — Phase 0 Foundation (28 Jun 2026) ✅
- **Auth:** JWT login/refresh/logout/me; brute-force lockout (5 fails → 15 min, HTTP 429); idempotent
  `seed_foundation` (roles, masters, demo users) → writes `memory/test_credentials.md`.
- **RBAC + scope:** `accounts` app (configurable `Role` with `nav_groups`/`landing_page`, custom `User`,
  `ScopeType`). Fail-closed store scoping verified (store user sees only their store).
- **Masters spine:** `masters` app (LegalEntity, Gstin, Store, Season, Brand w/ two-axis commercial model,
  GstSlab) + read-only API + Django admin.
- **Frontend:** warm login (demo-login chips), role-aware app shell (5-layer sidebar, store/GSTIN switcher
  locked for single-store users, user menu), per-role dashboards (owner/ops/finance vs store vs warehouse),
  INR Lakh/Crore + SKU-grain primitives, real Master Data tables (Stores/Brands/Seasons/GSTINs), placeholder
  pages for not-yet-built modules.
- **Tested:** testing_agent iteration_1 → backend 100%, frontend 100%, no bugs. Regression suite at
  `app/backend/tests/test_foundation.py`.

## Backlog (prioritised)
- ~~**P0 / Phase D Slice 3 — printed-invoice/anchored-header archetypes**~~ **DONE (1 Jul, PR #34):**
  archetypes **D/E/F** shipped (`ptmapper/profiles.py`), so `ambreli`/USPOLO/Madura/Jockey-style files now map;
  the PT-mapper feed/harden pass also added normalisers + a big seed. See the "Current state" PT-mapper bullet.
- ~~**P1:** Master Data stewardship UI~~ **DONE (30 Jun)** — steward-gated CRUD (`masters.IsMasterSteward`)
  + `MasterPages.tsx` New/Edit editors; see the "(c) Master Data stewardship UI" entry above.
- **P1:** Continue replacing legacy page calls with `openApiClient` / generated schema types as pages are touched.
- **P1 — Phase 2:** Selling floor / POS ingest (outbox/dead-letter).
- **P2 — Phase 3+:** Money-in (collection & 3-rail bank audit), Transfers, Payments/vendor settlement,
  Controls (exception inbox, reconciliations, approvals/second-eye), Tally bridge, Intelligence (suggest-only).
- **P2 — Non-Branded Booking / PO Maker agent:** deferred pending user's client clarification.
- **P2 — Production hardening:** External ingress/proxy CORS policy alignment, reduce localStorage token reliance now that httpOnly cookies exist, HTTPS/secure-cookie review, Django+Postgres deploy path validation.

## Next action items
Inbound D2 (branded + non-branded, `Grn.kind` + non-brand PT authoring + location-aware posting) landed on
`main` across #43–#49; the PWA/security batch (#55–#60) + dark mode (#61) followed. The next frontiers:
1. **D3 outbound / POS ingest** (selling floor, outbox/dead-letter) — the next business layer, still unbuilt.
2. ~~**Double-entry vendor/cash ledger**~~ **DONE (Jun 2026, F1):** `finledger` vendor/cash now post balanced
   Σ=0 vouchers through `core.post_entries`; GL control accounts tie to the subledgers, proven live on
   `/api/finledger/health`. Alpha caveat closed.
3. Run broader alpha QA over the current screens and capture issues from real users.
4. Add Vendor dues drill-down/export if accounts users need follow-up bill-level ageing.
