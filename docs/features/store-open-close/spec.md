# Store open/close - spec

Phase 1 of the dev process (`docs/agents/phases/spec.md`).
Issue #296. 11 August 2026.
**Money slice: yes.** Phase 2 (`design`) is mandatory and must carry every posting with both legs.

---

## Source

- Issue **#296**, "Store open/close: design and build via the full dev-process chain".
- `docs/agents/improvement-plan.md` §1.4, which lists this as Phase 1 missing-module work.
- `CONTEXT.md`: the 12 rules, the kernel contracts, the locked money decisions.
- The code, which is the truth for what exists: `storefront/day.py`, `storefront/cash_summary.py`, `storefront/dashboard.py`, `sell/services/register.py`, `sell/services/daily_check.py`, `finledger/models.py`, `finledger/posting.py`, `core/gl.py`, `accounts/rbac_matrix.py`, `app/frontend/src/shell/navConfig.ts`, `app/frontend/src/till/held.ts`.
- The design corpus as background only: `10-pos/store-front-design.html`, `consolidation/integration-contracts.html` (the D4 bank edge), `consolidation/erp-coverage-and-completeness.html`.
- The grill: `grill-decisions.md` beside this file, 20 decisions, all ruled by Anand as "go with your recommendation".

## Problem

A store person finishes trading at nine in the evening, counts the notes in the drawer, and has nowhere to put the number.

The system can already tell them what the day *should* have come to.
`/money/day-summary` reads the day by tender off the bills themselves, and its own code says out loud that it stops there: "There is no 'confirm the day' button and there deliberately cannot be one."
So the count happens on paper, or in somebody's head, and the difference between what the drawer holds and what the bills say is never written down anywhere.

Three consequences run from that one hole.

**Nobody ever answers for a short drawer.** A missing ₹2,000 leaves no record, so it is not a loss anybody investigates, it is a conversation that may or may not happen.

**Cash out of the drawer is invisible.** When a store hands notes to the bank, or pays for something out of the till, the system does not know, so even the honest count cannot be compared to anything.

**Held bills expire on a timer.** `till/held.ts` throws them away at local midnight and its comment admits this is a stopgap "until I3 defines day close properly".
The design corpus promised the opposite: at day close the store chooses keep or expire, and nothing expires silently.

And there is no morning either.
Nothing records the float a counter starts with, so "the drawer is ₹300 light" cannot be told apart from "the drawer started ₹300 light".

## Blast radius

Confirmed with Anand before the grill.
One correction since: the build order below no longer starts with the period lock, because D2 ruled that the close does not lock anything.

### Backend

| App | What changes | Why |
|---|---|---|
| **`storefront`** (new models) | Gains `models.py` and its first migration: the day-open, day-close and store-cash-out documents. | It is already the store-day app (`day.py`, `cash_summary.py`, `dashboard.py`) but is read-only today with zero models. The documents belong beside the arithmetic that feeds them. Phase 2 may rule for a new app instead; the spec does not force it. |
| **`core`** | Two new `GLAccount` codes: `CASH_SHORT_OVER`, `CASH_IN_TRANSIT`. Three new doc types in the naming series: `DOP`, `DCL`, `CSO`. | The variance and the deposit have no account to post to. `doc_type` must be in the rendered key for it to stay unique. |
| **`finledger`** | `CashLedgerEntry` gains a nullable `store` FK. A posting helper for the drawer variance and the store cash-out. | The cash ledger is store-less today, so a store's drawer cannot be read from it at all. |
| **`sell`** | `ContinuityFlag` gains four kinds. `sell_daily_check` gains the unclosed-day escalation. The accept pipeline auto-opens a day and detects a late bill on a closed one. | The day's exceptions already live on this model and this nightly run; a second exception list would drift from the first. |
| **`masters`** | `Store` gains `opening_float_paise`. | Rule 12: the float is a per-store number a trained admin edits, not a constant. |
| **`approvals`** | One new `ApprovalRoute` for a variance at or above the threshold. | The generic route framework already exists; this is a row, not a mechanism. |

**Not touched:** `inbound`, `ptmapper`, `vendors`, `stockledger`, `outbound`, `offers`, `files`, `mail`, `search`, `aiagents`, `alerts`.

### Frontend

| Screen | What changes | Why |
|---|---|---|
| **Open / Close Day** (new) | The whole feature's screen: the morning count, the evening count, the expected figures, the held-bill answers. | Nothing like it exists anywhere in the nav. |
| **`navConfig.ts`** | One new item under **Sell**, beneath "Till & Sync". A deep link to it from **Money**. | The person whose day it is lives in Sell; Money is where HO reads it. Both gates stay the section's own. |
| **Store Dashboard** | `manager.day_close.state` stops being hard-coded `"not_built"`. | The contract already reserved the key's shape for exactly this. |
| **Day Summary** (`/money/day-summary`) | Gains a read-only line saying whether the day is closed and what the variance was. Still no confirm button. | The confirm belongs on the close screen; duplicating it would give one day two front doors. |
| **`till/held.ts` + Dexie** | Keep-or-expire moves from the midnight timer to the close. A `kept_count` field, so a new **Dexie version**. | The corpus rule the stopgap was standing in for. Any new till field is a new Dexie version (known trap). |

**Not touched:** the billing screen and cart, offers, receive, transfer, stock, setup, customers.

### Rules and ledgers in play

Rule 1 (both the open and the close are documents), Rule 2 (the fix for a wrong variance is a reversal, never an edit), Rule 5 (a drawer that will not agree must not stop tomorrow's trade), Rule 6 (the variance is computed, never typed), Rule 10 (every close names its actor), Rule 11 (an unclosed day is a deadline, not a memory), Rule 12 (the float and the reason codes are data).

Ledgers touched: the **GL** (`core_gl_entry`, which already carries a store) and the **cash subledger** (`finledger_cash_entry`, which does not yet).
Stock and vendor ledgers are untouched.

## Money slice

**Yes.**

The drawer variance is a real posting with two legs, the deposit moves money out of the drawer, and the correction for a late bill is a reversal against a document that has already posted.
Every one of those is the ledger, so the money rules in `docs/agents/dev-process.md` are on: phase 2 is mandatory, it must carry both legs of every posting, and every money finding goes back to Anand.

It is **not** a GST slice.
Nothing here touches output tax, valuation, or the commercial model, and no CA-gated item in `CONTEXT.md` blocks it.

## Functional requirements

### The morning

**FR1.** A store records its trading day open as a document of type `DOP`, keyed `(store, date)`, numbered `{FY}/{store}/DOP/{seq}`, carrying one counted cash figure in paise and its actor.

**FR2.** Expected opening cash is the previous close's counted figure.
Where the store has no previous close, it is `Store.opening_float_paise`.

**FR3.** Where the counted opening differs from the expected opening by `X` paise, the open posts, and where it agrees it posts nothing:

- counted **below** expected: `Dr CASH_SHORT_OVER X` / `Cr CASH X`, both legs carrying the store.
- counted **above** expected: `Dr CASH X` / `Cr CASH_SHORT_OVER X`.
- the cash subledger mirrors it with one `CashLedgerEntry` row carrying the store, the day's `DOP` number, and reason `overnight`.

**FR4.** The first accepted bill of a day for which no `DOP` exists opens that day automatically at the expected figure, and raises a `day_opened_without_count` flag.
The bill is never refused and the counter is never blocked.

**FR5.** A second `DOP` for the same `(store, date)` is refused.

### During the day

**FR6.** A store records cash leaving the drawer as a document of type `CSO`, carrying an amount, a reason of `bank_deposit` or `other`, and its actor.
`other` demands free text of at least 10 characters.

**FR7.** A `CSO` posts on the day it is made:

- `bank_deposit`: `Dr CASH_IN_TRANSIT X` / `Cr CASH X`.
- `other`: `Dr SUSPENSE X` / `Cr CASH X`, held there until the Expenses slice classifies it.
- both mirror into the cash subledger as one `PAYMENT` row of `-X` on account `CASH`, carrying the store.

**FR8.** `CashLedgerEntry` carries a nullable `store`.
Every row this feature writes sets it.
No existing row is backfilled, and a row with `store IS NULL` reads as "unattributed (pre-Aug 2026)".

### The evening

**FR9.** Expected closing cash is the counted opening, plus the day's cash tenders, minus the day's cash-out.
The cash-tender figure is read through the existing `storefront.day.money_for`, never recomputed, so the close and the Day Summary cannot disagree.

**FR10.** A store closes its day as a document of type `DCL`, keyed `(store, date)`, carrying one counted cash figure, its actor, and the variance.
The variance posts on the same legs and in the same shape as FR3, with reason `day_close`.

**FR11.** The close screen shows the day's card, UPI and credit-note totals read-only.
None of them can be counted, corrected or confirmed here; they settle against the bank in the D4 bank edge.

**FR12.** A variance whose absolute value reaches **₹500 (50,000 paise)** demands a typed reason of at least 10 characters and raises an approval to a holder of `money: manage`.
The close completes either way, and the approval never gates it.

**FR13.** The close lists every open held bill for the store and will not complete until each is answered keep or expire.
A kept hold carries to the next day and increments `kept_count`.
A hold reaching `kept_count = 3` may only be expired or converted to a Booking at the next close.

**FR14.** A second `DCL` for the same `(store, date)` is refused.

**FR15.** A day up to **7 days** old may be closed at `money: operate`.
Older than 7 days, the close needs `money: manage` and a typed reason.

**FR16.** No day ever closes by itself, on any schedule, for any reason.

### After the close

**FR17.** A bill accepted whose `billed_at` day already has a `DCL` posts a correcting variance, dated today, reason `late_bill_after_close`, linked to that `DCL`, on the same legs as FR3.
It raises a `day_moved_after_close` flag carrying the day, the old variance and the new one.
The closed day is not reopened, and no second `DCL` is created.

**FR18.** A day with no `DCL` shows on that store's own dashboard from the following day.
From **2 days** unclosed, `sell_daily_check` raises a `day_not_closed` flag visible to HO.

**FR19.** `manager.day_close.state` on `GET /api/store/dashboard` reports the real state of today's day instead of the literal `"not_built"`.

### Access and audit

**FR20.** The screen is gated `sell: operate` for the store in scope; opening, closing and cash-out are gated `money: operate` at that store; the back-close beyond 7 days and the variance approval are gated `money: manage`.
The nav item's declared section and rung match the server's, as the one-gate contract requires.

**FR21.** Every open, close, cash-out, keep-or-expire answer and late-bill correction carries its actor, its timestamp and its typed reason **on the document row itself**, in the pattern `RegisterHandover` and `AccessChange` already use.

There is deliberately no write to a central audit table, because **no such table exists**.
`CONTEXT.md` names an `audit_log` (who/why/when, AI-suggestion vs human-decision) among the kernel's audit primitives and the codebase has nothing of the kind; the sidebar's "Audit Log" is a `planned: true` stub.
This feature does not invent one, and the drift is recorded in the open questions.

## Non-functional requirements

**NFR1.** The close screen's expected-cash figure is computed in **5 database queries or fewer**, and the screen paints in **under 2 seconds** on a store's 4G connection.
It is read at the end of every trading day at every store, on the phone in somebody's hand.

**NFR2.** Day open and day close are **online-only**.
A close computed against a partial local view would post sync lag as a real loss.
An offline store's close waits, which is safe because FR18 makes an unclosed day visible rather than silent, and FR4 keeps the counter billing regardless.

**NFR3.** Every posting goes through `post_entries` and is balanced-or-fail.
No row of any ledger is edited or deleted by any path in this feature.

**NFR4.** Opening, closing and cash-out are idempotent on retry: a repeated submission of the same document returns the same document, and never a second posting.

**NFR5.** Documents and their postings are retained indefinitely; they are the record a variance is investigated from years later.

**NFR6.** The day-close arithmetic is covered by a golden-file test over at least **20 constructed store-days** spanning: agree, short, over, no opening count, a cash-out, a late bill, and a back-close.

**NFR7.** No new query in this feature reads across stores without a scope; an unscoped read errors, per ADR-0003.

## Edge cases

1. **A day with no bills at all.** A shop that opened and sold nothing still opens and closes, and its expected closing equals its counted opening. A shop that never opened has no day at all, and that is not a flag.
2. **A store's very first day on the system.** No previous close exists, so expected opening is the store's float (FR2). If the drawer genuinely holds something else, the difference posts as an overnight variance on day one, which is correct: it is money the books had not heard of.
3. **A bill cancelled after the close.** The cancellation reverses the sale's own postings and reduces the day's cash tenders, which makes the closed day's expected figure move exactly as a late bill does. It takes the same FR17 correction.
4. **A negative counted figure.** Refused. A drawer cannot hold minus ₹300.
5. **A counted figure far larger than any plausible day.** Not refused, because a real store could bank a week of takings at once, but a variance above the threshold takes the FR12 reason and approval like any other.
6. **The day rolls over mid-close.** The close is against a named date, never "now", so a close begun at 23:58 and submitted at 00:01 still closes the day it named.
7. **A held bill whose store closed while it was held.** Answered at the next close of that store, and it keeps its `kept_count`.
8. **Two people close the same day at once.** FR14's key refuses the second, and the second person is told the day is already closed and by whom, not shown an error.
9. **A cash-out recorded on a day already closed.** Refused; the money left the drawer on a day somebody has already counted, so it is a correction and takes the same reversal path as FR17.
10. **The IST day.** Every date in this feature is the store's IST day, through `tillToday()` on the till side, never the UTC day (known trap).

## Out of scope

- **The period lock.** Not needed once D2 ruled the close does not lock. Filed as its own ticket, and the `CONTEXT.md` drift is recorded below.
- **Permanently closing a store.** The June audit's actual gap, which it filed under D9 migration. Still open, still unbuilt, and not this feature.
- **Expenses.** `other` on a cash-out holds against `SUSPENSE` until the Expenses slice classifies it.
- **Bank reconciliation.** `CASH_IN_TRANSIT` is cleared by the D4 bank edge when the credit lands, not here.
- **Card and UPI settlement.** Shown, never counted (FR11).
- **Multiple counters in one store.** One drawer, one close (D15).
- **Shift handover within a day.** A different act from a day close, and no store has asked for it.
- **Staff attendance at open.** HRMS.
- **Remapping `CashLedgerEntry.Account.BANK`.** Recorded as a finding below, deliberately not fixed here.

## Build order

1. **`core`: the two GL accounts and the three doc types.** No dependencies. Everything else posts through them.
2. **`masters`: `Store.opening_float_paise`.** No dependencies. FR2 needs it before any day can be opened.
3. **`finledger`: the nullable `store` on `CashLedgerEntry`, plus the variance and cash-out posting helpers.** Depends on 1. Migration adds the column only; no backfill, because the table refuses UPDATE by trigger and by REVOKE.
4. **`storefront`: the `DOP` document and its posting.** Depends on 1, 2, 3. FR1 to FR3, FR5.
5. **`storefront`: the `CSO` document.** Depends on 3, 4. FR6 to FR8.
6. **`storefront`: the `DCL` document, its variance and its approval route.** Depends on 4, 5. FR9 to FR12, FR14, FR15, FR20, FR21.
7. **`sell`: the auto-open on first bill, and the late-bill correction.** Depends on 4 and 6, because it can only correct a close that exists. FR4, FR17.
8. **`sell`: the new flag kinds and the `sell_daily_check` escalation.** Depends on 7. FR18.
9. **Frontend: the Open / Close Day screen, the nav item, the Dashboard key, the Day Summary line.** Depends on 4 to 6. FR19, and the screen half of FR1 to FR15.
10. **Till: held bills move from the midnight timer to the close, with `kept_count` and a new Dexie version.** Depends on 6 and 9. FR13.
11. **The golden-file suite over the 20 constructed store-days.** Depends on everything above. NFR6.

## Open questions

Each of these needs a named human, and none of them blocks starting phase 2.

**For the stores** (via Anand):

1. **What is the real opening float?** ₹5,000 is a seeded working number, not a finding (D5).
2. **Does any store run two drawers?** The whole design assumes one counter per store (D15).
3. **Who should be allowed to close the day?** The ratified matrix gives the manager and the cashier the same rung, so as specified a cashier can close (D10). If KDPS wants the manager only, that is an access change two administrators make in the editor, not a code change.
4. **Is ₹500 the right line for "somebody must explain this"?** (D9.)

**For Anand:**

5. **Where do the day documents live?** This spec puts them in `storefront`, which has never had a model. Phase 2 may rule for a new app.
6. **The `CONTEXT.md` period-lock drift.** `CONTEXT.md` names a period lock as a kernel contract and the code has none. This feature no longer needs it (D2), but the contract is still claiming something untrue, and it should be either built or struck.
7. **The `BANK` to `CASH` mapping.** `CASH_CONTROL_ACCOUNTS` sends `CashLedgerEntry.Account.BANK` to `GLAccount.CASH`, so a drawer-to-bank move would post `Dr CASH / Cr CASH` and say nothing. This feature routes round it with `CASH_IN_TRANSIT` rather than remapping, because remapping would break the per-account books-health tie. It is pre-existing drift that wants its own decision.

8. **The `CONTEXT.md` audit-log drift.** `CONTEXT.md` lists an `audit_log` among the kernel's audit primitives, and no such table exists anywhere in the backend; actor and reason are carried per document instead, and the "Audit Log" screen is a stub. That is the third contract in the same file claiming something the code does not do, alongside the period lock and the `BANK` mapping, and the pattern itself is worth a decision.

**For the CA:** nothing.
No GST, valuation or commercial-model question arises here, and no `CONTEXT.md` CA-gated item touches this feature.

---

Phase 1 ends here.
Phase 2 is `design`, and Anand starts it.
