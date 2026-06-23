# Coding Standards

The reviewer agent loads this during code review via `@.sandcastle/CODING_STANDARDS.md`.
Stack: React (TypeScript) PWA front end + Python/Django back end + PostgreSQL.

## Style
- TypeScript: camelCase for variables/functions, PascalCase for components/types. Prefer named exports.
- Python: follow PEP 8; snake_case for functions/variables, PascalCase for classes.
- No commented-out code or stray TODOs in committed code.

## Testing
- Every new behaviour gets a test (pytest for Django, the JS test runner for React).
- Ledger/posting logic must be covered: a posting either fully succeeds or fully rolls back — test the all-or-nothing path.
- Use descriptive test names that state the expected behaviour.

## Architecture (KDPS domain rules — never violate)
- **SKU = Style × Size × Color.** Size×color must survive end-to-end; never collapse stock to style level.
- **Documents write ledgers; ledgers are append-only.** Never mutate a posted ledger row — reverse and repost.
- **Snapshot masters** onto documents at write time (price, tax, vendor terms) — don't read live masters for historical documents.
- **GST is data, not code** — slab/date-effective tax tables, two GSTINs (Bihar / Jharkhand). Tally stays the book of record.
- **Profitability is derived** (cost from PT/invoice, revenue from POS) — never hand-entered.
- **AI at the edges only** — the intelligence layer reads ledgers; it never writes them.
- Keep modules single-responsibility; prefer composition over inheritance.
- Money in INR; format with Lakh/Crore grouping (`₹28,50,000`).
