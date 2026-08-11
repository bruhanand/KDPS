# Store open/close - grill decisions

Issue #296. Phase 1 (`spec`), 11 August 2026.

Anand confirmed the blast radius and then ruled: take the recommended answer on every question.
So each decision below is the recommendation, with the reason it was recommended, recorded as the ruling.
Where a decision is one somebody else has to confirm later (a store, the CA, or Anand on a second look), it says so and it is repeated in the spec's open questions.

---

## D1 - The scope is the trading day, not shutting a store down

The issue calls this "the one true gap the June completeness audit found".
That is not quite true, and the drift matters enough to record.

The audit's gap was **store closure**: permanently shutting a shop, which the audit itself said "folds into D9 migration".
The issue body then describes something else entirely: opening the till, the float, closing the day, cash reconciliation.

**Ruled: this feature is the trading day.**
Permanently closing a store stays where the audit put it, in D9 migration, and is still an open hole.

## D2 - Closing the day does not lock the day

The till is offline-first by design.
A counter can print a bill on Tuesday night and only sync it on Wednesday morning.
If the store's close locked Tuesday, that real printed bill would arrive at a shut door, and a bill the books never get is the worst outcome the system has.

**Ruled: the close is a cash-control document, not a period lock.**
Late bills still land on a closed day; what they do is raise a flag and post a correcting variance (D14).
The period lock stays a separate, month-level act that Accounts performs, and it is not built here (D13).

This reverses the build-order line in the confirmed blast radius, which said the period lock had to come first.
Once the close stopped locking anything, it stopped needing one.

## D3 - There is a day-open document, and it counts the drawer

The alternative was no open at all: let the first bill start the day and carry the float forward silently.

**Ruled: an explicit day open, with a counted figure.**
Without a counted opening the closing variance is unmeasurable, because "what should be in the drawer" has no starting point.
Counting at both ends is also the only way to tell "money went missing overnight" apart from "the cashier was short today", and those two facts get answered by different people.

## D4 - A day nobody opened is opened by the first bill

Rule 5 is flag, never block, and a shop that opens at 10:30 with a queue at the counter must be able to bill.

**Ruled: the first accepted bill of a day auto-opens that day** at the *expected* opening figure (the previous close's counted cash, or the store's float when there is no previous close), and raises a flag that the day was opened without a count.
Nobody's morning is blocked, and the missing count is visible rather than invented quietly.

## D5 - The float is a per-store master number, default ₹5,000

Rule 12: business differences are data.

**Ruled: `Store.opening_float_paise`, an admin-editable master field, seeded at ₹5,00,000 paise (₹5,000).**
₹5,000 is a working change-float for a fashion counter whose bills run ₹1,000 to ₹3,000.
**The stores must confirm the real number** - this is a seed value, not a finding.

## D6 - Day open posts nothing unless the count disagrees

The float is not new money.
It is cash that stayed in the drawer overnight, so declaring it is not a money event and must not write a ledger.

**Ruled: day open posts only the overnight variance,** when the counted opening differs from the expected opening.
A day open that agrees posts nothing at all.

## D7 - The close counts cash only

Card and UPI are not in the drawer.
They sit in `CARD_CLEARING` and `UPI_CLEARING` precisely so the drawer can be counted against `CASH` alone, and `core/gl.py` already says this out loud.

**Ruled: one counted number, and it is cash.**
Card, UPI and credit-note totals are shown on the close screen read-only, so the store can eyeball them, and they reconcile against the bank later in the D4 bank edge, which is already designed and not this feature's job.

## D8 - The variance is always posted, never suppressed

A short drawer is a real loss and an over drawer is real money nobody can explain.

**Ruled: every non-zero variance posts, at both ends of the day, with no tolerance band that swallows it.**
There is no "close enough" amount that vanishes.
The threshold in D9 decides who has to *answer* for a variance, never whether it is booked.

## D9 - A variance of ₹500 or more goes to Accounts, and never blocks the close

**Ruled: absolute threshold ₹500 (₹50,000 paise), on the absolute value of the variance.**
On a day taking ₹50,000 to ₹2,00,000 that is roughly a quarter to one percent, which is the honest line between a counting slip and something worth a person's attention.
A percentage would be harder for a store person to hold in their head and would move the bar on a quiet day, which is exactly the day a variance means most.

At or above ₹500 the store must type a reason of **at least 10 characters** and an approval is raised.
The close still completes either way (Rule 5).

**The approval goes to Accounts, not the Operations Head.**
This is forced by the ratified matrix, not chosen: `ho_ops` holds `money: none`, and `accounts` and `owner` are the only seats holding `money: manage`.
A cash variance is an accounting matter anyway.

## D10 - Anyone at the store holding `money: operate` may close the day

`store_manager` and `store_staff` both map to the same matrix row, `store_person`, which holds `sell: operate` and `money: operate` ("Expenses only (create)").
The ladder therefore cannot express "the manager but not the cashier".

**Ruled: the close is gated at `money: operate` + the store in scope, and a cashier can perform it.**
Carving the cashier out in code is exactly the override the RBAC rules forbid, and the ratified sheet gave both seats the same rung deliberately.
The real controls are the ₹500 approval to Accounts and an actor on every close.
**If KDPS wants the cashier out, that is an access change two administrators make in the editor, live on the next request, not a code edit.**
Flagged for Anand.

## D11 - Cash leaving the drawer during the day is in scope, with exactly two reasons

The moment anyone takes a note out of the drawer, expected cash is wrong and the whole close is theatre.
But building Expenses here would be a different feature (`/money/expenses` is already a planned nav stub).

**Ruled: build the mechanism, seed two reason codes.**
A store cash-out document carries `bank_deposit` or `other`, and `other` demands free text.
The Expenses slice later replaces `other` with real categories without touching this document (Rule 12).

## D12 - `CashLedgerEntry` gains a nullable `store`, and history is never backfilled

`finledger_cash_entry` has no store column, so "what is in Deoghar's drawer" cannot be read from the cash ledger at all today.

It is also append-only in earnest: a `BEFORE UPDATE` trigger plus a `REVOKE`.
A backfill migration is an UPDATE, which is the thing the table exists to refuse.

**Ruled: add `store` nullable; new rows set it; existing rows stay NULL forever and read as "unattributed (pre-Aug 2026)".**
The append-only guarantee is worth more than tidy history, and the alpha's rows are seed data.
The day's cash-in side does not depend on this anyway: it reads sale tenders through the existing `storefront/day.py`, which already carries the store and the till's own clock.
Only the new cash-out rows need the column, and all of those are new.

## D13 - The period lock is out of scope, and filed as its own ticket

`CONTEXT.md` names a period lock as a kernel contract.
Grep finds no such mechanism anywhere in `core`.

**Ruled: not built here, because D2 removed this feature's need for it, and a kernel contract deserves its own slice rather than arriving as a side effect of a store screen.**
The drift is recorded loudly in the spec so it is not lost a second time.

## D14 - A late bill on a closed day posts a correcting variance automatically

Tuesday's cash was physically in the drawer when it was counted on Tuesday night.
So when Tuesday's bill turns up on Wednesday, the *count* was right and the *expected* was wrong, which means the variance already posted on Tuesday is wrong by that bill's cash amount.

**Ruled: the system posts a reversing correction, dated today, with reason `late_bill_after_close`, linked to the original close,** and raises a flag so a human sees the day moved.
It is arithmetic, not judgment, and Rule 6 says calculated numbers are not typed by hand.
The closed day is not reopened and there is no second close document; correct-by-reversal is the kernel's only fix path.

## D15 - One drawer per store, one close per store per day

`sell/services/register.py` already treats the counter as singular: "the till owns its store's gap-free counter".

**Ruled: the day document's key is (store, date).**
Multiple counters in one store is out of scope.
**The stores must confirm** no shop runs two drawers.

## D16 - A store may back-close up to 7 days; older than that, HO closes it

**Ruled: 7 days.**
A shop that forgot Friday should be able to fix it on Monday without a phone call.
A month-old day is not something a store person can honestly count, so beyond 7 days the close needs `money: manage` and a reason.

## D17 - Nothing ever auto-closes; two days unclosed escalates

**Ruled: no auto-close, ever.**
Auto-closing invents a count nobody made, and an invented number is an invisible wrong answer, which is the same principle that refuses a zero-cost posting.

**Ruled: yesterday unclosed shows on the store's own dashboard; two days unclosed raises it to HO** through the nightly `sell_daily_check`.

## D18 - Held bills must be answered at the close, and a hold may be kept 3 times

The design corpus already promised this: "At day close they are flagged and the store chooses: keep or expire. Nothing expires silently."
`till/held.ts` currently expires at local midnight as an admitted stopgap "until I3 defines day close properly".

**Ruled: the close screen lists every open hold and will not complete until each is answered.**
That blocks the close, which is a deliberate act, and never the counter, which is Rule 5's actual concern.

**Ruled: a hold may be kept at 3 closes; on the fourth it must expire or become a Booking.**
A hold that lives forever is a Booking wearing the wrong name, which the glossary already says.

## D19 - The close is online-only

Closing against a partial local view would produce a variance that is nothing but sync lag, and then post it as a real loss.

**Ruled: day close requires the server.**
If the store is offline at 9pm the close waits, which is safe because D17 means an unclosed day is a visible to-do rather than a silent gap.
The morning is protected by D4's auto-open, so an offline counter never stops billing.

## D20 - Two new GL accounts, and no remap of the existing ones

`CASH_SHORT_OVER` books the drawer variance at both ends of the day.
`CASH_IN_TRANSIT` holds a bank deposit between the drawer and the bank credit, which is exactly the "expected / in-transit until the money lands" the D4 bank edge already describes.

**Ruled: no change to `CASH_CONTROL_ACCOUNTS`.**
`CashLedgerEntry.Account.BANK` currently maps to `GLAccount.CASH`, so a drawer-to-bank move would post `Dr CASH / Cr CASH` and mean nothing.
Remapping it would break the per-account books-health tie against a GL account with no history.
Using `CASH_IN_TRANSIT` gets a correct deposit posting without touching the mapping.
**The BANK-maps-to-CASH mapping is pre-existing drift and is recorded as a finding, not fixed here.**
