// The sidebar, as one manifest (issue #87).
//
// KDPS navigates by *operation* — what actually happens to goods and money —
// not by the architecture's own layers. The old groups ("Documents", "Ledgers",
// "Controls", "Intelligence", "Edges & Admin") were design vocabulary no store
// person in Deoghar thinks in; the thirteen sections below are the words KDPS
// uses. Vocabulary is shared across roles: a role sees a *subset* of these
// sections, never a differently-named regrouping — so the store and the
// warehouse on the phone to each other both say "Transfer".
//
// This file is the single source of truth for navigation. Derived from it:
//   · the sidebar          (AppShell, intersected with the server's sections)
//   · the route guards     (auth/routeAccess — prefix → section)
//   · the routes           (App.tsx: planned pages are generated from `state`)
//   · the "coming soon" copy (pages/ModulePage)
//   · the legacy redirects (every pre-#87 URL, below)
//
// Which sections a person actually gets is *not* decided here — the server
// sends it (SIDEBAR RBAC contract, #85), and `section` codes below match the
// server's codes exactly. This manifest only says what a section contains.
import {
  BarChart3,
  Boxes,
  ClipboardCheck,
  ClipboardList,
  LayoutDashboard,
  PackagePlus,
  Settings,
  ShoppingCart,
  Tag,
  Truck,
  Undo2,
  Users,
  Wallet,
} from "lucide-react";
import type { LucideIcon } from "lucide-react";

// The capability ladder, mirroring `accounts/sections.py`. Ordinal: a higher
// rung includes the powers of the lower ones.
export const CAPABILITY_ORDER = ["none", "view", "operate", "approve", "manage"] as const;
export type Capability = (typeof CAPABILITY_ORDER)[number];

/** Does the capability `held` on a section reach at least `minimum`? Fail-closed:
 *  anything unrecognised (or absent) counts as `none`. */
export function meetsCapability(held: string | undefined, minimum: Capability): boolean {
  const rank = CAPABILITY_ORDER.indexOf((held ?? "none") as Capability);
  return rank >= 0 && rank >= CAPABILITY_ORDER.indexOf(minimum);
}

// Payroll is the one gate the ladder cannot express: Accounts must see it on
// `staff: view` ("payroll inputs") while a store person must not, and the store
// person sits *higher* on the ladder at `staff: operate` ("own attendance").
// An ordinal threshold can't separate them, so this stays an explicit role list.
export const PAYROLL_ROLES = ["owner", "it_admin", "accounts"];

export interface NavItem {
  label: string;
  /** The one canonical URL for this screen. There is exactly one per screen. */
  to: string;
  /** Finer gate than the section: only these role codes see the item. Use only
   *  where the capability ladder genuinely cannot express the rule (Payroll) —
   *  otherwise prefer `minCapability`, which reads the same server-sent data the
   *  API gates on and so cannot drift from it. */
  roles?: string[];
  /** Finer gate than the section: the rung the caller must hold *on this item's
   *  section* to see it. Mirrors a backend permission tighter than the section
   *  itself — e.g. the ledgers are `money: manage`, the rung only Owner and
   *  Accounts hold, so "Expenses only" roles keep the section but not the books. */
  minCapability?: Capability;
  /** Not built yet — App.tsx routes it to the "coming soon" page, and `intent`
   *  is what that page promises. (#89 aligns the wording with the client
   *  report; this slice only keeps the existing honesty.) */
  intent?: string;
  /** Reachable and routed, but not a menu item — an action reached from inside
   *  another screen. V-flip is the case: a rare ownership correction that lives
   *  as a button on Stock, not as a line in the sidebar. */
  action?: true;
  /** A menu entry into *another* section's screen. It owns no route and no
   *  access rule — the section that hosts the screen keeps both, so one screen
   *  still has exactly one URL and one gate. */
  deepLink?: true;
}

export interface NavSectionDef {
  /** Section code from the server's RBAC contract (#85). */
  code: string;
  /** Fallback label; the server's label for the section wins when present. */
  label: string;
  icon: LucideIcon;
  /** CSS `--layer-*` token suffix (index.css). Sections share the nine tokens. */
  layer: string;
  items: NavItem[];
}

export const SECTIONS: NavSectionDef[] = [
  {
    code: "home",
    label: "Home",
    icon: LayoutDashboard,
    layer: "home",
    items: [
      { label: "Dashboard", to: "/" },
      // The one approvals inbox for the whole system, listed once. It used to
      // appear in two groups; Home is the group every role has, so it lives here.
      { label: "Approvals", to: "/approvals" },
      {
        label: "Alerts",
        to: "/alerts",
        intent:
          "This page will surface what needs attention — stock stuck in transit, return windows closing, and the exceptions the old exception inbox collected.",
      },
    ],
  },
  {
    code: "sell",
    label: "Sell",
    icon: ShoppingCart,
    layer: "store",
    items: [
      {
        label: "Billing",
        to: "/sell",
        intent:
          "This page will handle barcode-scan billing, GST invoices, counter discounts and live stock deduction — including EOSS bulk billing during a season sale.",
      },
      {
        label: "Return & Exchange",
        to: "/sell/returns",
        intent:
          "This page will handle customer returns and exchanges against the original bill.",
      },
      {
        label: "Customers",
        to: "/sell/customers",
        intent:
          "This page will find a customer by name, phone or bill number and reprint the bill — reprint only, never edit.",
      },
    ],
  },
  {
    code: "booking",
    label: "Booking",
    icon: ClipboardList,
    layer: "documents",
    items: [
      { label: "Bookings", to: "/booking" },
      { label: "New Booking", to: "/booking/new" },
    ],
  },
  {
    code: "receive_goods",
    label: "Receive Goods",
    icon: PackagePlus,
    layer: "store",
    items: [
      { label: "Receive (GRN)", to: "/receive" },
      {
        label: "Upload Bill",
        to: "/receive/upload-bill",
        intent:
          "This page will take the brand's invoice/bill (e.g. Madura) as an upload, which then feeds PT making.",
      },
      { label: "PT Files", to: "/receive/pt" },
    ],
  },
  {
    code: "transfer",
    label: "Transfer",
    icon: Truck,
    layer: "outbound",
    items: [
      { label: "Transfers", to: "/transfer" },
      { label: "Send Stock", to: "/transfer/new" },
      {
        label: "Stock Request",
        to: "/transfer/requests",
        intent:
          "This page will let a store ask the warehouse or another store for stock, through approval, with honest status all the way.",
      },
      {
        label: "Distribution",
        to: "/transfer/distribution",
        intent:
          "This page will plan the split of newly received stock across stores — a suggested split, hand-adjustable, with a buffer held back.",
      },
      {
        label: "In-Transit",
        to: "/transfer/in-transit",
        intent:
          "This page will show stock currently between locations, and the gaps (sent ≠ received) that only a senior may close with a reason.",
      },
    ],
  },
  {
    code: "stock_count",
    label: "Stock Count",
    icon: ClipboardCheck,
    layer: "controls",
    items: [
      {
        label: "Count Sessions",
        to: "/stock-count",
        intent:
          "This page will run counting sessions — a whole store, one brand or one section — counted blind, with variance reports and recounts.",
      },
      // Corrections live where they are caused: a count is what produces them.
      { label: "Adjustments", to: "/stock-count/adjustments" },
      { label: "Write-offs", to: "/stock-count/writeoffs" },
    ],
  },
  {
    code: "return_to_brand",
    label: "Return to Brand",
    icon: Undo2,
    layer: "outbound",
    items: [
      { label: "Returns", to: "/return-to-brand" },
      { label: "New Return", to: "/return-to-brand/new" },
      // Quarantine is built — it is a tab on Stock, reached here by deep link.
      { label: "Damage / Quarantine", to: "/stock?view=quarantine", deepLink: true },
    ],
  },
  {
    code: "stock",
    label: "Stock",
    icon: Boxes,
    layer: "ledgers",
    items: [
      { label: "Stock on Hand", to: "/stock" },
      { label: "Movement History", to: "/stock/history" },
      // Not a menu item — an ownership action reached from Stock on Hand.
      { label: "V-Flip", to: "/stock/vflips", action: true },
    ],
  },
  {
    code: "money",
    label: "Money",
    icon: Wallet,
    layer: "controls",
    // The sheet gives store and warehouse "Expenses only (create)" while
    // Accounts and Owner get the whole section. Capability can't say that — both
    // hold `operate` — so the books themselves carry the finance gate they
    // already have on the server, and Money collapses to one Expenses line for
    // everyone else.
    items: [
      {
        label: "Payments",
        to: "/money/payments",
        intent:
          "This page will record vendor payments with their approval steps, including the 3-way check (bill vs GRN vs PT) before paying.",
        minCapability: "manage",
      },
      { label: "Vendor Ledger", to: "/money/vendor", minCapability: "manage" },
      { label: "Cash", to: "/money/cash", minCapability: "manage" },
      {
        label: "Bank",
        to: "/money/bank",
        intent: "This page will reconcile the bank statement against what the books say.",
        minCapability: "manage",
      },
      {
        label: "Collections",
        to: "/money/collections",
        intent: "This page will track money collected against money banked, store by store.",
        minCapability: "manage",
      },
      {
        label: "Expenses",
        to: "/money/expenses",
        intent: "This page will take store and warehouse expense entries.",
      },
      {
        label: "Tally",
        to: "/money/tally",
        intent:
          "This page will show what has gone to Tally and what is still pending — Tally stays the statutory book of record.",
        minCapability: "manage",
      },
    ],
  },
  {
    code: "offers_price",
    label: "Offers & Price",
    icon: Tag,
    layer: "intelligence",
    items: [
      {
        label: "Price List",
        to: "/offers/price-list",
        intent: "This page will hold prices and markdowns, date-effective.",
      },
      {
        label: "Offers",
        to: "/offers",
        intent:
          "This page will hold brand schemes — value slabs, buy-2-get-1, gifts — per store, with start and end dates.",
      },
      {
        label: "Discounts",
        to: "/offers/discounts",
        intent:
          "This page will set the discount limit per role and route anything beyond it for approval.",
      },
      {
        label: "EOSS Planning",
        to: "/offers/eoss",
        intent:
          "This page will plan the season sale — markdown plans, which stock, which stores. Schemes are defined here and applied in Sell.",
      },
    ],
  },
  {
    code: "staff",
    label: "Staff",
    icon: Users,
    layer: "edges",
    items: [
      {
        label: "Attendance",
        to: "/staff/attendance",
        intent:
          "This page will take biometric check-in/out at the store, show your own leaves and delays, and send the day's attendance.",
      },
      // A cashier holds Staff for their *own* attendance ("Own attendance
      // (derived)"), so employee records and salary stay off their menu. A store
      // *manager* holds `staff: manage` for their own store — the sketch makes
      // managing the store's members their job — so Members appears for them and
      // not for the cashier, from the same server-sent capability.
      {
        label: "Members",
        to: "/staff/members",
        minCapability: "manage",
        intent:
          "This page will hold the store's own people — add and remove members, keep contact and bank details, and track each member's monthly target against achievement with growth/de-growth on a pie. “Members” means staff, not loyalty customers (settled 25 Jul 2026 from the hand-drawn Store Ops screen); the POS still owns the customer.",
      },
      {
        label: "Payroll",
        to: "/staff/payroll",
        roles: PAYROLL_ROLES,
        intent: "This page will take salary inputs and sales incentives. Later.",
      },
    ],
  },
  {
    code: "reports",
    label: "Reports",
    icon: BarChart3,
    layer: "intelligence",
    items: [
      {
        label: "Sales Reports",
        to: "/reports/sales",
        intent:
          "This page will report sales by date range, store, brand, item and member.",
      },
      {
        label: "Stock Reports",
        to: "/reports/stock",
        intent: "This page will report stock position, ageing and dead stock.",
      },
      {
        label: "Profit",
        to: "/reports/profit",
        intent:
          "This page will show brand-wise and store-wise profit, derived from cost-in and sale-out — never hand-entered.",
      },
      {
        label: "Daily Summary",
        to: "/reports/daily",
        intent: "This page will put the day's business on one page, sent on WhatsApp.",
      },
      {
        label: "Report Maker",
        to: "/reports/maker",
        intent: "This page will let you build your own report from approved measures and save the format.",
      },
    ],
  },
  {
    code: "setup",
    label: "Setup",
    icon: Settings,
    layer: "master",
    items: [
      {
        label: "Products",
        to: "/setup/products",
        intent: "This page will hold the item master — styles, sizes, colours, barcodes, HSN.",
      },
      { label: "Stores", to: "/setup/stores" },
      { label: "Brands", to: "/setup/brands" },
      { label: "Seasons", to: "/setup/seasons" },
      { label: "GSTINs", to: "/setup/gstins" },
      { label: "Users & Roles", to: "/setup/users", minCapability: "manage" },
      {
        label: "Audit Log",
        to: "/setup/audit",
        intent: "This page will show who did what, when — forever.",
      },
      {
        label: "Settings",
        to: "/setup/settings",
        intent:
          "This page will manage numbering, approval limits, tolerances, alerts and integrations (including the POS sources the old Edges group held).",
      },
    ],
  },
];

/** Every pre-#87 URL → its new home, longest prefix first. A path under an old
 *  prefix keeps its tail: `/documents/bookings/12` → `/booking/12`. */
const LEGACY_PREFIXES: [from: string, to: string][] = [
  ["/documents/pt-mapper", "/receive/pt"],
  ["/documents/bookings", "/booking"],
  ["/documents/inbound", "/receive"],
  ["/documents/transfers", "/transfer"],
  // The old "Returns" stub covered both halves; customer returns are Sell's.
  ["/documents/returns", "/sell/returns"],
  ["/documents/sales", "/sell"],
  ["/documents/payments", "/money/payments"],
  ["/inbound", "/receive"],
  ["/outbound/transfers", "/transfer"],
  ["/outbound/rtvs", "/return-to-brand"],
  ["/outbound/adjustments", "/stock-count/adjustments"],
  ["/outbound/writeoffs", "/stock-count/writeoffs"],
  ["/outbound/vflips", "/stock/vflips"],
  ["/ledgers/stock-on-hand", "/stock"],
  ["/ledgers/stock", "/stock/history"],
  ["/ledgers/vendor", "/money/vendor"],
  ["/ledgers/cash", "/money/cash"],
  ["/masters/stores", "/setup/stores"],
  ["/masters/brands", "/setup/brands"],
  ["/masters/seasons", "/setup/seasons"],
  ["/masters/gstins", "/setup/gstins"],
  ["/masters/users", "/setup/users"],
  ["/store/sell", "/sell"],
  ["/store/receive", "/receive"],
  ["/store/count", "/stock-count"],
  ["/store/transfer", "/transfer"],
  ["/controls/exceptions", "/alerts"],
  ["/controls/approvals", "/approvals"],
  ["/controls/audit", "/setup/audit"],
  // Reconciliation is parked until Money is designed; bank rec is its nearest
  // named home, so the old link lands somewhere honest rather than nowhere.
  ["/controls/recon", "/money/bank"],
  ["/intel/dashboards", "/reports/sales"],
  ["/intel/profitability", "/reports/profit"],
  ["/intel/dead-stock", "/reports/stock"],
  ["/intel/forecast", "/reports/stock"],
  ["/intel/reports", "/reports/maker"],
  ["/edges/rbac", "/setup/users"],
  ["/edges/tally", "/money/tally"],
  ["/edges/integrations", "/setup/settings"],
  ["/edges/pos", "/setup/settings"],
  ["/edges/config", "/setup/settings"],
].sort((a, b) => b[0].length - a[0].length) as [string, string][];

/** Does `pathname` sit at or under `prefix`? (`/stock` ≠ `/stock-count`.) */
export function underPrefix(pathname: string, prefix: string): boolean {
  return pathname === prefix || pathname.startsWith(prefix + "/");
}

/** The new home of an old URL, or null if `pathname` is not a legacy path.
 *  Case-insensitive: React Router matches paths case-insensitively, so a
 *  bookmarked `/Ledgers/Vendor` must redirect too. */
export function resolveLegacyPath(pathname: string): string | null {
  const normalized = pathname.toLowerCase().replace(/\/+$/, "") || "/";
  for (const [from, to] of LEGACY_PREFIXES) {
    if (underPrefix(normalized, from)) return to + normalized.slice(from.length);
  }
  return null;
}

/** Flat list of every item in the manifest, tagged with its owning section. */
export const NAV_ITEMS: (NavItem & { section: string })[] = SECTIONS.flatMap((s) =>
  s.items.map((i) => ({ ...i, section: s.code })),
);

/** The path part of an item's `to` (drops the `?view=quarantine` deep link). */
export function itemPath(item: NavItem): string {
  return item.to.split("?")[0];
}
