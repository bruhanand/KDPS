# KDPS — Meeting Output Report

**Date:** 5 June 2026
**Source:** `5-6-2026-deal-3-month-details.pdf` (`5-6-2026-deal-3-month.m4a`)
**Participants:** Anand (developer) · Priyo ji (client-side, presents to Bhaiya)
**Purpose:** Lock the first-phase deliverables, the build approach, the commercials, and tonight's action items before the pitch to Bhaiya.

> Scope note: This report covers only what was decided for the first 3 months. Nothing beyond that scope is included.

---

## 1. Commercials (decided)

- **Last month:** ₹10,000 (usage / plan setup that Anand already covered)
- **This month onward:** ₹70,000 / month
  - ₹60,000 — development / implementation
  - ₹10,000 — AI cost (capped)
- **Duration:** this structure holds for the next **3 months only**

---

## 2. The 5 finalized tracks (first 3 months)

These five are locked. They are the entire scope of this phase.

1. **Daily Cash / Payment Audit**
   - Reconcile **Cash + UPI + Card** collected at each store vs **actual bank deposits**
   - Runs daily, ~11:00 AM (after bank statement is available)
   - This is **Bhaiya's biggest pain point** (cash leakage / financial tracking)

2. **Stock Aging Module**
   - Auto-detect stock **age** and **collection** (e.g. 2023, Summer-Spring, Autumn-Winter) from **inward / received dates**
   - Store-wise inventory data download as the input

3. **PT File Mapper** — two types:
   - **Type 1 — brand provides PT file:** company PT Excel data → **KDPS PT file format**
   - **Type 2 — brands / non-brand without PT file:** Invoice / PDF → **KDPS PT file format**

4. **Report Maker**
   - From **POS data → brand report**

5. **Centralized Sales Dashboard**
   - All stores' daily sales in **one view**
   - **Not yet confirmed** — proceeds only if the client decides to include it

---

## 3. Build approach (decided)

- Build the system **module by module**, combining at every step — each module joins the others as it lands
- A **connect system** with login-based access: **different login → different user → different data**

### User types in scope (3 roles)

| User | Access |
|---|---|
| **User 1** | Daily Cash / Payment Audit |
| **User 2** | Stock Aging Module |
| **User 3** | PT File Mapper + Report Maker |

**Open item:** can the Centralized Sales Dashboard also be built **per store**? (to decide)

---

## 4. Questions the Plan of Action must answer (per track)

1. **What is needed from the client** (e.g. POS API, bank statement API)
2. **After the client provides it, how we proceed**
3. **How much time it will take**

---

## 5. What is needed from the client

- **POS software provider API** — API documentation + access rights (client to check with provider — meeting tomorrow)
- **Bank statement API** — for live transaction sync
  - **Fallback if no API:** manual bank-statement download on a fixed schedule, **by 11:00 AM daily**, to run the reconciliation script

---

## 6. AI subscriptions (settled — no further discussion)

- **Priyo ji** → buys a **$20 Claude subscription** (personal / learning use)
- **Anand** → manages his **own AI subscription**

---

## 7. Sequencing rule (decided)

- **Requirements and process are decided first.**
- **Only then** is the cloud platform for the application chosen.

---

## 8. Action items

| # | Action | Owner | Deadline |
|---|---|---|---|
| 1 | Integrate the **Cash Audit** workflow into the existing system map | Anand | Tonight |
| 2 | Submit the finalized **Phase 1 Plan of Action** draft | Anand | Tonight, by 7:00 PM |
| 3 | Review PoA and present the implementation-milestone pitch to **Bhaiya** | Priyo ji | Tonight, 8:00–9:00 PM |
| 4 | Check **POS provider** for API documentation + access rights | Priyo ji | Tomorrow |
| 5 | Verify **bank statement API** availability for live data sync | Priyo ji | Tomorrow |

---

## 9. Target

- Demonstrate **80–90%** of the above scope within **25 days** (this month's remaining runway) — enough to show real progress to Bhaiya.
