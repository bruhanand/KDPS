# KDPS Roadmap / Backlog

Prioritized backlog. See `CHANGELOG.md` for what shipped and when, `PRD.md` for
the problem statement and current architecture.

## P0
None open. The two P0s from the 4 Aug 2026 session (Distribution grid, Partner
store flag + configurable billing) are both shipped and tested.

## P1
- **AI PT-file chat assistant** (Emergent Universal Key) — explicitly deferred
  by the user this session ("we can do it later"). Not started.
- **Q1–Q4, Q7, Q8 from the booking/price consultation** need Anand's ruling: who
  owns the ticket for own goods; whether a store may run a local offer; per-role
  vs per-store counter caps; the promo user's writ; booking value at cost or
  MRP; booking band. See `CHANGELOG.md`'s booking/price entry.
- **Open-to-buy at booking time** — needs trustworthy sell-through history first.
- Real printer integration for the tag-printing screen (currently an explicit
  frontend-only mock — see 4 Aug 2026 changelog entry).

## P2
- Value-banded countersignature on a re-ticket; tender/bank offers + payments;
  store acknowledgement of a published offer.
- True bin/location tracking for physical warehouse storage.
- HRMS & Attendance module.
- Minor, non-blocking (found by testing agent, iteration_29): the login
  payload's granted-sections list for `it_admin` omits `money` even though a
  direct `userCan(user, "money", "view")` check returns true for that role —
  a serialization/seed mismatch worth reconciling, not a live bug for any
  tested role today.
- Carried over, not yet started: the written operations audit and the 18-issue
  fix pass referenced in `docs/../github_issues_audit.md`.

## Known, accepted, not a bug
- `/setup/settings` (Counter Settings) is fully blocked at the route level for
  Owner (`sell: manage` only, Owner holds `sell: view`) — pre-existing, not
  touched this session. Do not "fix" without a product decision on who should
  hold `sell: manage`.
- 36 `src/till/*` vitest failures (`navigator is not defined`) are a jsdom
  environment gap in this pod, unrelated to any shipped code.
