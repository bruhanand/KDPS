# design-sync notes — KDPS

Repo-specific gotchas for syncing the KDPS PWA to claude.ai/design.
Read this before re-running the sync.

## What is being synced

The **live app's own design system** — `app/frontend`, the shipped React PWA.
Not the design directions in `docs/UI-design/` (five conflicting explorations authored 29 Jul 2026), and not the old hand-built HTML-card project "KDPS Operating System" from 26 Jun.
Anand chose the live system on 29 Jul 2026 because the POS screens being designed next must match the screens stores already use.

## The repo is an app, not a component library

There is no packaged build, no `dist/`, and no Storybook — so the converter runs in synth-entry mode (`[NO_DIST]`), bundling `app/frontend/src` directly.
Three consequences the setup works around:

- **The package must be self-linked.** The converter resolves the package at `<node-modules>/<pkg>`, which does not exist in the DS's own repo.
  Fix: `ln -sfn .. app/frontend/node_modules/kdps-frontend`. Recreate this after any fresh `npm install` that wipes `node_modules`.
- **`src/main.tsx` must be kept out of the synth entry.** It calls `ReactDOM.createRoot(document.getElementById("root"))` at import time; bundled in, it throws before the IIFE assigns `window.KDPS`, so *every* export goes missing and validate fails `[BUNDLE_EXPORT] 19/19`.
  Fix: `.design-sync/overrides/source-kit.mjs` (declared in `cfg.libOverrides`) adds a `BOOTSTRAP_RX` filter. On re-sync, diff it against the bundled `lib/source-kit.mjs` and merge upstream changes.
- **The fork imports `ts-morph`,** so node needs `ln -sfn ../.ds-sync/node_modules .design-sync/node_modules`. That link is gitignored — recreate it on every fresh clone.

## Component scope

19 components ship. The ~49 screen and infrastructure exports (`*Page`, `App`, `AuthProvider`, `ProtectedRoute`, `NotFound`, `Home`, `Login`, the ledger pages) are excluded via `cfg.componentSrcMap` nulls: they are whole screens that need the API and a session, so they would only ever render floor cards and would bury the real building blocks in the picker.
`ProposalsIcon` is excluded too — it is a bare re-export of a lucide icon, not a KDPS component.

They stay **in the bundle** (only the catalogue excludes them), which is deliberate: bundling every page is what pulls every page stylesheet into `_ds_bundle.css`, so the full class vocabulary reaches designs.

## The CSS is the bulk of the value

The app's building blocks are mostly CSS classes, not React components. `styles.css` → `_ds_bundle.css` (~55 KB) carries the token layer (`src/index.css`, light + dark) plus every component and page stylesheet.
No fonts ship, and none are missing — the app is system-fonts-only by design.

## Known render warns

- `[RENDER_BLANK]` on `Money`, `SkuLine`, `Stat`, `CommercialBadge`, `ApprovalPill` before their previews were authored: these are single-span primitives that render a few pixels tall with no props. Authoring the preview resolves it; it is not a component defect.

## Authoring gotchas

### Layout

- **`.kdps-table` has `min-width: 1500px`.** It is the PT-mapper's wide grid, not a general table class. Using it inside a preview card pushes every column after the first out of frame. Use a plain `<table>` or a CSS grid.
- **A capture cell is ~520px of usable width no matter what `maxWidth` you set.** A 720px card renders identically to a 520px one. Treat `maxWidth` as an upper bound and design for ~500px.
- **`PageHeader`'s root is `.toolbar`, which wraps.** Below ~600px its action buttons drop under the lead and read as a broken layout. Give header-with-actions cards `maxWidth: 640` and keep button labels short.
- **Never put a phrase-length chip in a flex row beside text** — it gets squeezed and wraps inside its own pill. `GapStatePill state="gap"` ("Gap - sent ≠ received") hits this. Stack chip above sentence with a grid.
- **`ApprovalTrail` renders its own `.card section-card`.** Wrapping it in another `card` double-borders it; use a plain `<div style={{maxWidth: 520}}>`. Same for `InboundQueueCard`.
- `SearchBox`'s pill caps at 420px, so a wider card leaves dead space. `ListSearchBar` wants ~580 because the count sits beside it.

### Environment

- Previews are wrapped in `DsPreviewProvider` (`app/frontend/ds-preview-provider.tsx`), a `MemoryRouter`, so `Link`/`NavLink`/`useNavigate` work. It is preview-only and never imported by the app.
- **The router is pinned to `/`,** and there is no way to change it from a preview file: `MemoryRouter` cannot be nested (React Router v6 throws), and importing `react-router-dom` inside a preview gets a *second* bundled copy with its own empty context (`story-imports.mjs` only shims the DS package). Consequence: `PageHeader` can only ever show the `HOME` eyebrow and can never render its second crumb. Fixing that needs a config-level knob letting a preview choose the provider's `initialEntries`.
- **There is no auth context in previews.** `useAuth()` returns undefined, so anything reading the session (notably `AppShell`) cannot render. `AuthContext` is not exported from `app/frontend/src/auth/AuthContext.tsx`; exporting it would let a future sync inject a fake user and give `AppShell` a real preview. Not done here — the run was scoped to not touch app source.
- Page-scoped CSS *does* reach previews (`.toolbar`, `.spacer`, `.filter-bar`, `.status-pill`, `.section-card`, `.stat-label`) even though those page components are `null` in `componentSrcMap` — the stylesheets ride in on the bundled modules. Still `grep -c` `_ds_bundle.css` before leaning on one.

### Per-component

- `Combobox`'s dropdown is opened by user interaction and positioned `fixed`, so the open list cannot be captured statically. Previews show the closed states only.
- `ApprovalTrail` takes a whole `ApprovalT`, not a status. The "Asked again by" line fires only when `requested_by !== made_by` (compared by id); the Ask again button needs `status: "rejected"` **and** an `askAgainPath`. Never click it in a capture — it posts.
- `ReceiptExceptions` returns null on an empty array. There is no empty state to author.
- `ThemeToggle` reads the live preference, so the active segment is whatever the capture session's theme is.

### Content

- SKU codes come in two real shapes and they are not interchangeable. `SkuLine` takes brand/style/colour/size separately, and brand style codes genuinely are long (`ASKPCRGFN12345`, `MFK-4471`). A combined `sku_code` field is short and four-part (`MF-JEAN-BLK-32`), per `seed_demo_data.py`. Long codes wrap badly in a `table.data` column.
- Anand's house style bans the em dash. Some app source emits one (`ApprovalTrail`'s decision line, `GapStatePill`'s "gap" label), so it shows in the sheets. Keep authored preview copy on a plain dash.

### Card-layout overrides (in `cfg.overrides`)

Four components tripped `[GRID_OVERFLOW]` and carry an override. Don't remove them without re-checking:

- `InboundQueueCard`, `Stat`, `GlobalSearch` → `cardMode: "column"` (wider than a grid cell).
- `ScanScreen` → `cardMode: "single"`, `primaryStory: "DispatchTransfer"`. It is `position: fixed; inset: 0` — a full-bleed phone overlay — so no grid layout can present it. The other two cells still exist and are reachable with `?story=`.

### Techniques worth reusing

- **Getting a phone-shaped frame out of a fixed-position component.** `.ds-cell` already sets `transform: translateZ(0); overflow: hidden`, which traps a `position: fixed` component in its cell. Nesting another `translateZ(0)` div at the size you want gives a phone frame instead of a cell-shaped one.
- **Driving internal state through the real input.** `ScanScreen` keeps scanned counts in `useState`, so props alone show "0". Its preview replays a scan run into the wedge sink on a 24 ms interval: set `sink.value`, then dispatch a bubbling `KeyboardEvent("keydown", {key: "Enter"})`. One scan per tick — `applyScan` closes over `scanned`, so two in a tick read a stale count.
- **Canning an API answer without touching app source.** `GlobalSearch` fetches on type. Its preview patches `XMLHttpRequest.prototype.open` and, for URLs containing `/search?q=`, redirects to a `URL.createObjectURL(new Blob([json], {type: "application/json"}))`. Real axios, real debounce, real panel — only the bytes are canned. This is the pattern for any other fetch-on-mount component here.
- Capture waits for `networkidle` plus a font settle, so a ~250 ms replay or a 220 ms debounce lands comfortably.

## Findings that belong to the app, not the sync

Surfaced while authoring; **not fixed here** because this run was scoped to not touch `app/`:

- **`chip-grey` is referenced but never defined.** `GapStatePill` maps the `closed` state to `chip-grey`, and `RECEIPT_TONE` in `OutboundTransfers.tsx` has the same grey fallback, but `index.css` defines only `chip-green|amber|red|blue|purple|navy`. Those pills fall through to a bare `.chip`. It looks deliberate, so it is cosmetic — but it is a real gap.
- **Em dashes in user-facing app copy**, against the house style (see above).
- **The receive shortfall-note input renders behind the fixed footer.** `.scan-notes` (shown only when `short > 0` on a `strictExpected` receive) sits last in normal flow while `.scan-foot` is `position: fixed` at the bottom, so they overlap at any viewport height. Worth a look if anyone audits the receive screen. The preview avoids that state rather than shipping a card that shows the overlap.

## Re-sync risks

- **The five competing design directions in `docs/UI-design/` are unresolved.** If Anand settles on one of them and the app is restyled, this sync's tokens go stale in one commit. Check which direction the app ships before trusting a carried-forward grade.
- The `source-kit.mjs` fork is the fragile part: it is a copy of an upstream file and will silently miss upstream fixes. Diff it every sync.
- Preview content is hand-written realistic KDPS data (brands, stores, voucher numbers). It does not track master data and will not break if that data changes — but it will look dated if naming conventions change.
- The self-link and the `node_modules` symlink are both outside git. A fresh clone needs both recreated before the converter runs.
