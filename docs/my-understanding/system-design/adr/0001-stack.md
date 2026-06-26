# ADR-0001 — The stack

**Status:** Accepted 2026-06-25

## Context

KDPS is a money-critical, GST-bound, multi-brand retail operating system, built as a modular
monolith over one relational database (architecture rule: one codebase, one database). It is
built by one developer working with AI agents, and it must hold ledgers, GST, payments,
back-office admin and a read-only analytics/AI layer.

Two earlier notes conflicted, and the most recent design-of-record drifted from both: a 21-Jun
note locked "TypeScript end-to-end", the 23-Jun stack brief recommended a Python (Django) engine
with a React front, and the untracked consolidated design-of-record still said "TypeScript
end-to-end" (line 571) and "PostgreSQL row-level security" (line 561). This is the F4 / F19
documentation-drift finding from the 24-Jun review: a recommendation pending confirmation, never
consciously ratified, presented in two places as the opposite of itself.

The review Q&A of 25 June settled it. **Q11 — LOCKED: Option A — Python/Django engine + React/TS
screens.** A dedicated ERPNext engineering study (25 Jun) resolved the Frappe-vs-Django
sub-question: the platform is not adopted; only its *contracts* are borrowed. The old (distrusted)
ADR-0001 reasoning is salvaged here; the decision is now ratified rather than inherited.

Existing investments steer the choice: the `code/pdf-to-pt` invoice→PT pipeline is Python, and
the planned analytics/AI/ML layer is Python. Hosting (cloud provider and region) is deferred — to
be decided later.

## Decision

- **Backend / engine: Python + Django.** Gives login, user-roles, back-office admin and
  all-or-nothing DB transactions out of the box; same language as `pdf-to-pt` and the
  analytics/AI layer (one toolbox, not three); proven for data-heavy money systems. This is the
  one writer of every ledger and GST posting.
- **Frontend: React + TypeScript**, delivered as a browser PWA on the store computer (browser
  PWA, no app install).
- **Database: PostgreSQL.** The single writer of every ledger/GST posting is the server.
- **Hosting: deferred — cloud provider and region to be decided later.** The read-only AI edges use
  a hosted top model (AI platform to be decided later).
- **Typed at both ends + a generated typed client at the API seam.** "TypeScript end-to-end" is
  dead. The contract is: a typed PWA (TypeScript), a typed Django (mypy + django-stubs, pydantic
  at the boundaries), and a generated typed TS API client at the HTTP seam
  (`drf-spectacular` Django→OpenAPI, then `openapi-typescript` schema→TS client). Types do not
  flow automatically across the language boundary; they are made to flow by generation.
- **NOT Frappe — re-implement ERPNext's *contracts* as plain Django** (Q11). Borrow ERPNext's
  models / migrations / GST data model as plain Django code; do **not** adopt the Frappe DocType
  meta-runtime. The meta-runtime violates Rule 12 ("variation is data, not code"): it makes
  customisation a matter of mutating a large runtime kernel, where KDPS wants config rows over a
  small frozen kernel.
- **No backend-as-a-service.** Supabase rejected: weak all-or-nothing ledger transactions,
  tangled permissions at ERP scale, lock-in.

## Consequences

- Two languages across the HTTP boundary (Python back, TS front), so the **generated typed client
  is load-bearing** — a foundation task, and a CI staleness check (ADR-0005) keeps it honest.
- The PWA is a fast client but never the writer of money: every rupee commits server-side, and
  any queued offline write carries an idempotency key (ADR-0004) so retries cannot double-post.
- Django's batteries (admin, auth, migrations, transactions) become load-bearing — chosen on
  purpose to shrink solo-build surface area.
- Borrowing ERPNext contracts as plain Django costs an up-front re-implementation but keeps the
  kernel small, frozen and ours — the precondition for Rule 12 and for the append-only,
  documents-write-ledgers core (ADR-0004, ADR-0006).

## Alternatives rejected

- **TypeScript end-to-end (Node/Nest or Next.js):** one language + native end-to-end type flow,
  but you build admin/auth/roles by hand and rewrite the Python pipeline. The free batteries and
  one-language-with-analytics outweighed native type flow for a solo + AI build; the generated
  client recovers most of the type-flow benefit anyway.
- **Adopt Frappe / ERPNext as the platform:** fastest to GST, but the DocType meta-runtime fights
  the documents-write-ledgers design, the "Tally is the statutory book" rule, and Rule 12. Borrow
  its GST data model and contracts; do not run on its kernel.
- **Supabase / BaaS:** rejected for weak all-or-nothing ledger transactions, complex permissions
  at ERP scale, and lock-in.
