# ADR-0002 — Repo layout & module seams

**Status:** Accepted 2026-06-25

## Context

The system is a modular monolith (architecture: one codebase, one database). "Modular" only holds
if the seams are enforced mechanically — under a solo dev + AI agents, seams kept by convention
erode fast. We must settle the physical repo shape, where cross-cutting machinery lives, and how
boundaries are kept honest.

This ADR salvages the (distrusted) old ADR-0002 reasoning — researched against current Django
modular-monolith practice — and ratifies it under the now-confirmed stack (ADR-0001). The
decision is unchanged in substance; what changed is that the stack it sits on is now locked.

## Decision

**Monorepo, under an `app/` parent:**

```
app/
  backend/      Django project (the engine — Python/Django, ADR-0001)
  frontend/     React + TypeScript PWA (consumes the generated typed client)
code/pdf-to-pt/ stays for now (folds into the inbound module later)
docs/  + the ADR chain
```

**One Django app per design module**, plus a thin shared kernel:

- `core` — the **shared kernel** (kept small, frozen and stable): the money type (integer paise),
  the append-only posting/ledger engine (the central `post_entries`, ADR-0006), the base audited /
  append-only model (actor + timestamps + audit), scoping primitives (ADR-0003), shared value
  objects (GSTIN, barcode+season key). This is where the architecture rules are encoded once.
- `masters` (D8), `vendors` (D1), `inbound` (D2), `outbound` (D3), `payments` (D4),
  `offers` (D5), `tally` (D6), `analytics` (D7) — one domain each.
- `integrations` — the edge adapters (POS, Tally/TaxOne, bank, WhatsApp), each behind a swappable
  interface (anti-corruption layer). Ten Software POS and the KDPS-built POS are concurrent
  sources behind one POS adapter.

**The seam rules:**

- Each module's **database is private**. Peer domain modules **do not foreign-key or import each
  other's models** — they reference by ID and call the other module's **published service
  functions** (a `public.py` / `services.py` of use-case functions + dataclasses); the rest is
  internal.
- **Pragmatic exception:** downward foreign keys to `core` and `masters` are allowed — the shared
  kernel and master data are the stable foundation every module legitimately depends on (and
  documents snapshot masters anyway, per architecture Rule 3).
- Dependencies are **unidirectional** (no cycles): domain modules → `masters` → `core`.
- React mirrors the same module names as feature folders, consuming the generated TS API client.

**Enforcement — `import-linter` contracts in CI** (salvaged from the old ADR's import-linter
seams): a layered contract (core < masters < domain), forbidden contracts (no peer-to-peer model
imports), independence between peers. A violation **fails the build, not a code review**. The
`import-linter` config is a reviewed artifact: changing an allowed dependency is a conscious edit.

**Scaffold only what the current slice needs.** Create `core` + `masters` + `vendors` + `inbound`
for the foundation / first slices; add the remaining module apps as their slices land. No
speculative empty apps; the `import-linter` contract grows with the modules.

**API-client toolchain pinned:** `drf-spectacular` (Django → OpenAPI schema) →
`openapi-typescript` (schema → typed TS client). The "client-in-sync" typecheck (ADR-0005) checks
this generated output is not stale.

## Consequences

- The per-module apps map 1:1 to the eight locked designs (D1–D8); `core` is the one place the
  architecture rules — including the frozen kernel of Rule 12 — get encoded.
- "No cross-module FK" means some integrity is enforced in service code, not the DB — accepted for
  peer modules; the `core`/`masters` FK exception keeps ledger/document integrity hard where it
  matters most.
- `import-linter` makes the modular boundary a CI gate, so the monolith does not silently
  congeal into a big ball of mud under fast AI-assisted edits.

## Alternatives rejected

- **Microservices / service-per-module:** rejected by the architecture (one codebase, one
  database); enormous operational tax for a solo build, and it breaks the all-or-nothing ledger
  transaction that must span modules.
- **Convention-only seams (no import-linter):** seams kept by discipline alone erode under
  solo + AI velocity; the linter makes the boundary mechanical.

## Sources

- Makimo, *Modular Monolith in Django* — private module DB, IDs over FKs, public-interface
  use-case functions, dataclasses for transfer.
- Finn Andersen (ITNEXT), *How to Scale a Monolithic Django Project Without Microservices*.
- DDD *shared kernel* (kept small/stable); HackSoft-style `apps/` + `common/` + service/selector
  layers.
- `import-linter` (Seddon) — layered / forbidden / independence contracts; `django-modulith`.
