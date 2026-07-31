// What each unbuilt screen honestly promises (issue #89).
//
// KDPS management has a build-status report (21 July 2026, "Build Status Report
// — Module-wise"). A demo of the sidebar and that report must tell one story, so
// the copy below quotes the report's own module names and promises rather than
// paraphrasing them, and places each screen where the report places it. Where the
// stores wrote a requirement down in their own words (the 25 July Store Ops
// notes), those words are used instead of ours.
//
// The rule for this file: a planned page may not flatter. If a screen is waiting
// on hardware, on a decision nobody has taken, or on data that will not exist
// until billing is live, it says so in `notes`. A placeholder that reads as
// "almost ready" is the exact failure #89 exists to prevent.
//
// Paired with the section manifest: every nav item marked `planned` must have an
// entry here, and nothing else may (asserted in plannedPages.test.ts).

/** When this screen arrives, in the report's own vocabulary. Three of the four
 *  are its sequence positions (next → then → later); `unscheduled` is its third
 *  column, "Planned" — the module may already be live or in test, but this part
 *  of it has not been started, so there is no position to quote. */
export type Stage = "next" | "then" | "later" | "unscheduled";

export interface ReportModule {
  /** The module's name in the client report, quoted exactly. */
  name: string;
  stage: Stage;
}

/** How each stage is worded to a reader. Plain words, no dates — the report
 *  deliberately gives no delivery dates and neither does the product. */
export const STAGE_LABEL: Record<Stage, string> = {
  next: "Next to be built",
  then: "After billing",
  later: "Later",
  unscheduled: "Planned",
};

/** Chip tone per stage, matching the report's own badge colours. Bare tones,
 *  rendered as `chip-${tone}` — the shape PtMapper's STAGE_TONE already uses. */
export const STAGE_TONE: Record<Stage, string> = {
  next: "blue",
  then: "blue",
  later: "navy",
  unscheduled: "navy",
};

const GOODS_RECEIPT: ReportModule = { name: "Goods Receipt", stage: "unscheduled" };
const TRANSFERS: ReportModule = { name: "Transfers & Returns", stage: "unscheduled" };
const POS: ReportModule = { name: "POS & Billing", stage: "next" };
const ACCOUNTS: ReportModule = { name: "Accounts & Payments", stage: "then" };
const INVENTORY: ReportModule = { name: "Inventory Management", stage: "unscheduled" };
const ADMINISTRATION: ReportModule = { name: "Administration", stage: "unscheduled" };
const PROMOTIONS: ReportModule = { name: "Promotions & EOSS", stage: "later" };
const HRMS: ReportModule = { name: "HRMS & Payroll", stage: "later" };
const ANALYTICS: ReportModule = { name: "Reports & Analytics", stage: "later" };

/**
 * The client report's own module strip, whole.
 *
 * Listed rather than derived from `PLANNED_PAGES`, because a module does not
 * leave the report when its last screen is built: POS & Billing is on the strip
 * and has nothing planned under it since #184 landed the last of Sell's four
 * screens. Deriving the strip from what is unbuilt would quietly drop a module
 * from the client's report the moment we finished it, which is the opposite of
 * what finishing it should do.
 */
export const REPORT_MODULES: ReportModule[] = [
  GOODS_RECEIPT,
  TRANSFERS,
  POS,
  ACCOUNTS,
  INVENTORY,
  ADMINISTRATION,
  PROMOTIONS,
  HRMS,
  ANALYTICS,
];

export interface PlannedScreen {
  /** One line: what the screen is for, in the words its user would use. */
  summary: string;
  /** What will live here. The report's promises where the report makes one. */
  contains: string[];
  /** The honest caveats — what this waits on, and where the ask came from.
   *  Anything a client would be annoyed to discover later belongs here. */
  notes?: string[];
  /** The module of the client report this screen belongs to. */
  module: ReportModule;
}

export const PLANNED_PAGES: Record<string, PlannedScreen> = {
  // ---- Sell ---------------------------------------------------------------
  // Nothing. Every screen under Sell is built - Billing (#181), Return &
  // Exchange (#184), Customers (#185) and Till & Sync (#180) - and a promise on
  // this list for a screen somebody can already open would be a promise nobody
  // can reach, which `plannedPages.test.ts` says out loud.
  //
  // The stores' own wording from the 25 July note about Customers, "re-print
  // only, no editing", is what shipped: there is no writer behind that screen to
  // edit with.

  // ---- Receive Goods ------------------------------------------------------
  // Nothing. "Upload Bill" was a promise the built screen already keeps: the
  // brand's invoice goes up inside "New receipt", where it is attached to the
  // receipt and read for the line match. #228 deleted the entry rather than
  // leave a menu line whose own page said "go and do it over there".

  // ---- Transfer -----------------------------------------------------------
  "/transfer/distribution": {
    summary: "The warehouse decides how newly arrived stock is split across the stores.",
    contains: [
      "A suggested split across stores, which you can change by hand",
      "A buffer held back at the warehouse",
      "Inter-store size rebalancing — moving sizes to the store that is selling them",
      "The split becomes the transfers, so nothing is typed twice",
    ],
    notes: [
      "Dispatch and receive are the transfer work in test now. This part has not been started.",
    ],
    module: TRANSFERS,
  },
  // ---- Money --------------------------------------------------------------
  "/money/payments": {
    summary: "Paying a brand, with the checks done before the money leaves.",
    contains: [
      "Vendor payments with approval workflow",
      "3-way matching before paying — invoice against goods receipt against PT",
      "What is due, what is overdue, what is on hold",
    ],
    notes: [
      "The vendor ledger and cash book are already live, so what we owe is visible today. The paying itself comes with this module.",
    ],
    module: ACCOUNTS,
  },
  "/money/bank": {
    summary: "Matching the bank statement against what the books say.",
    contains: [
      "Bank reconciliation, statement line against book entry",
      "Unmatched entries listed openly, not hidden",
    ],
    module: ACCOUNTS,
  },
  "/money/collections": {
    summary: "Money collected at the stores against money actually banked.",
    contains: [
      "Collected against banked, store by store",
      "Short deposits and late deposits visible per store",
    ],
    module: ACCOUNTS,
  },
  "/money/expenses": {
    summary: "Day-to-day spending at a store or the warehouse.",
    contains: [
      "Store and warehouse expense entries",
      "Coded so each expense lands in the right head",
      "A store person can enter an expense without being able to see the books",
    ],
    module: ACCOUNTS,
  },
  "/money/tally": {
    summary: "What has reached Tally, and what is still waiting.",
    contains: [
      "Tally integration — what has gone across and what is pending",
      "Anything that failed, with the reason, so it can be sent again",
    ],
    notes: [
      "Tally stays the statutory book of record. This system feeds Tally; it does not replace it.",
    ],
    module: ACCOUNTS,
  },

  // ---- Offers & Price -----------------------------------------------------
  "/offers/price-list": {
    summary: "What a piece is priced at, and what it was priced at on any past date.",
    contains: [
      "Prices and markdowns, date-effective",
      "Brand-wise price lists",
      "History — what the price was on the day a bill was made",
    ],
    module: PROMOTIONS,
  },
  "/offers/discounts": {
    summary: "How much each role may give away, and who approves more.",
    contains: [
      "Discount approval limits per role",
      "Anything beyond the limit goes for approval instead of being blocked",
      "Every override kept with who allowed it and why",
    ],
    module: PROMOTIONS,
  },
  "/offers/eoss": {
    summary: "Planning the season sale before it starts.",
    contains: [
      "Markdown planning — which stock, which stores, what price",
      "EOSS bulk billing (stock billed and kept in the store), set up here and run at the counter",
    ],
    module: PROMOTIONS,
  },

  // ---- Staff --------------------------------------------------------------
  "/staff/attendance": {
    summary: "The store's daily attendance screen — mark in, mark out, see the month.",
    contains: [
      "Mark check-in and check-out at the store",
      "See your own leaves and delays",
      "Send the day's attendance",
    ],
    notes: [
      "Posting attendance needs a biometric device at the store. No device is integrated yet, and hardware like this has lead time — until one is chosen and connected, attendance cannot be marked from this screen.",
      "Attendance and payroll were deferred by decision, to be revisited before go-live. The stores have now asked for attendance twice — 30 June and 25 July — so whether to pull a thin attendance-only slice forward is an open call for KDPS.",
    ],
    module: HRMS,
  },
  "/staff/members": {
    summary:
      "The store's own people — its staff. A store manager keeps their own store's members here.",
    contains: [
      "Add and remove members",
      "Contact details and bank details",
      "Each member's monthly target against their achievement",
      "Growth and de-growth against last month",
      "The store's members with their photos",
    ],
    notes: [
      "“Member” means a member of staff. It was settled on 25 July 2026 that Member Details is a staff scorecard, not a customer loyalty scheme. Loyalty is not part of this screen and stays out of scope; the POS owns the customer.",
      "Because a member record holds bank details, this screen belongs to the Attendance & Payroll module, which is deferred by decision until before go-live — it is not around the corner. Staff bank details are personal data and the screen will be built with that duty, not before it.",
      "Targets and achievement also need every bill to record who sold it. That is not decided yet and not built, so member-wise numbers cannot be shown until it is.",
      "A cashier does not see this screen. Keeping the store's people is the manager's job.",
    ],
    module: HRMS,
  },
  "/staff/payroll": {
    summary: "Salary and incentive inputs for the people the stores employ.",
    contains: [
      "Payroll inputs",
      "Sales incentive calculation",
      "Employee records and documents",
      "Employee self-service",
    ],
    notes: [
      "Payroll needs attendance first, so it comes after attendance — the last part of the deferred Attendance & Payroll module, not the first.",
    ],
    module: HRMS,
  },

  // ---- Reports ------------------------------------------------------------
  "/reports/sales": {
    summary: "What was sold — by day, by store, by brand, by item, by person.",
    contains: [
      "Sales report",
      "Member-wise report",
      "Item-wise report",
      "Date-range sales report",
    ],
    notes: [
      "These four are the stores' own words, in their own order, from the 25 July Store Ops note.",
      "All of them read sale data, which does not exist in this system until billing is built.",
      "Member-wise sales needs every bill to record who sold it. That is not decided yet and not built — it is not simply waiting on a screen.",
    ],
    module: ANALYTICS,
  },
  "/reports/stock": {
    summary: "What is lying where, how old it is, and what is not moving.",
    contains: [
      "Stock report",
      "Stock ageing",
      "Dead-stock alerts",
      "Return-deadline tracking for SOR brands",
      "Demand forecasting and auto-replenishment",
    ],
    notes: [
      "Stock position can be read from the ledger the system already keeps today — Stock on Hand and Movement History are live in the Stock section. Ageing, dead stock and deadline tracking are the parts still to be built.",
    ],
    module: INVENTORY,
  },
  "/reports/profit": {
    summary: "What each brand and each store actually earned.",
    contains: [
      "Brand-wise and store-wise profit and loss",
      "Cost taken from the PT or invoice at stock-in, revenue from the bill at sale — derived, never typed in by hand",
    ],
    notes: [
      "Cost is already captured on every goods receipt. The revenue half arrives with billing, so profit becomes real then.",
    ],
    module: ANALYTICS,
  },
  "/reports/daily": {
    summary: "The day's business on one page, sent to the phone.",
    contains: [
      "Daily business summary on WhatsApp",
      "Per person, so each role gets the numbers that are theirs",
    ],
    notes: ["The summary is mostly sale numbers, so it waits on billing."],
    module: ANALYTICS,
  },
  "/reports/maker": {
    summary: "Build the report you want, and keep the format.",
    contains: [
      "MIS dashboards",
      "Pick the measures and the columns, save the format, run it again next month",
      "The client's own sale and stock report formats as ready-made starting points",
    ],
    module: ANALYTICS,
  },

  // ---- Setup --------------------------------------------------------------
  "/setup/products": {
    summary: "The item master — every style, in every size and colour.",
    contains: [
      "Style, size, colour, barcode and HSN",
      "Barcodes as scan aliases, with stock counted under them",
      "Season and collection tags on every item",
    ],
    notes: [
      "Items already enter the system through brand PT files and PT making, which create them as goods arrive. This screen is where they will be managed directly instead.",
    ],
    module: ADMINISTRATION,
  },
  "/setup/audit": {
    summary: "Who did what, when — forever.",
    contains: [
      "Every document, every approval, every override, with the person and the time",
      "Searchable by person, by document, by date",
    ],
    notes: [
      "The trail is already being written by the system on every document. What is missing is this screen to read it.",
    ],
    module: ADMINISTRATION,
  },
  "/setup/settings": {
    summary: "The knobs the system runs on, kept as settings rather than as code.",
    contains: [
      "Document numbering series",
      "Approval limits and tolerances",
      "Alert thresholds",
      "Integrations — the POS sources and Tally",
    ],
    notes: [
      "Who may see and do what is already data, not code, so changing access never needs a software release. It is managed today under Users & Roles.",
    ],
    module: ADMINISTRATION,
  },
};
