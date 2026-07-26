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
//   · the route guards     (auth/routeAccess — URL → the screen that owns it)
//   · the routes           (routes.tsx: planned screens are generated from it)
//   · the planned pages    (pages/plannedPages — what each unbuilt screen promises)
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

/** Does this user reach at least `minimum` on `section`? The client's mirror of
 *  `accounts.permissions.user_can`, break-glass branch included: a superuser
 *  resolves to `manage` everywhere server-side, so a screen must not hide what
 *  the API would let them do.
 *
 *  One home for the rule, because it is easy to write four times and forget the
 *  superuser branch in one of them. Typed structurally rather than against
 *  `User`, so the navigation manifest keeps no dependency on the auth module. */
export function userCan(
  user: { is_superuser?: boolean; capabilities?: Record<string, string> } | null | undefined,
  section: string,
  minimum: Capability,
): boolean {
  if (!user) return false;
  if (user.is_superuser) return true;
  return meetsCapability(user.capabilities?.[section], minimum);
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
  /** Not built yet — routed to the planned page, which says what will live here.
   *  The promise itself is in `pages/plannedPages.ts` (#89), keyed by this
   *  item's path: navigation says what a section contains, that manifest says
   *  what we have told the client it will do. */
  planned?: true;
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
      { label: "Alerts", to: "/alerts", planned: true },
    ],
  },
  {
    code: "sell",
    label: "Sell",
    icon: ShoppingCart,
    layer: "store",
    items: [
      { label: "Billing", to: "/sell", planned: true },
      { label: "Return & Exchange", to: "/sell/returns", planned: true },
      { label: "Customers", to: "/sell/customers", planned: true },
    ],
  },
  {
    code: "booking",
    label: "Booking",
    icon: ClipboardList,
    layer: "documents",
    items: [
      { label: "Bookings", to: "/booking" },
      // A store holds `booking: view` (#130) - the list and the document, never
      // the create. The server refuses the POST at `operate`, so offering the
      // form here would walk them into a 403.
      { label: "New Booking", to: "/booking/new", minCapability: "operate" },
    ],
  },
  {
    code: "receive_goods",
    label: "Receive Goods",
    icon: PackagePlus,
    layer: "store",
    items: [
      { label: "Receive (GRN)", to: "/receive" },
      { label: "Upload Bill", to: "/receive/upload-bill", planned: true },
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
      { label: "Stock Request", to: "/transfer/requests", planned: true },
      { label: "Distribution", to: "/transfer/distribution", planned: true },
      { label: "In-Transit", to: "/transfer/in-transit" },
    ],
  },
  {
    code: "stock_count",
    label: "Stock Count",
    icon: ClipboardCheck,
    layer: "controls",
    items: [
      { label: "Count Sessions", to: "/stock-count" },
      // Corrections live where they are caused: a count is what produces them.
      // Both are writes gated on `stock_count: operate` server-side, so the
      // link must not open for a role the API will refuse (#94).
      { label: "Adjustments", to: "/stock-count/adjustments", minCapability: "operate" },
      { label: "Write-offs", to: "/stock-count/writeoffs", minCapability: "operate" },
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
      // Relabelling who owns stock is `stock: manage` on the server (#94).
      { label: "V-Flip", to: "/stock/vflips", action: true, minCapability: "manage" },
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
      { label: "Payments", to: "/money/payments", planned: true, minCapability: "manage" },
      { label: "Vendor Ledger", to: "/money/vendor", minCapability: "manage" },
      { label: "Cash", to: "/money/cash", minCapability: "manage" },
      { label: "Bank", to: "/money/bank", planned: true, minCapability: "manage" },
      { label: "Collections", to: "/money/collections", planned: true, minCapability: "manage" },
      { label: "Expenses", to: "/money/expenses", planned: true },
      { label: "Tally", to: "/money/tally", planned: true, minCapability: "manage" },
    ],
  },
  {
    code: "offers_price",
    label: "Offers & Price",
    icon: Tag,
    layer: "intelligence",
    items: [
      { label: "Price List", to: "/offers/price-list", planned: true },
      { label: "Offers", to: "/offers", planned: true },
      { label: "Discounts", to: "/offers/discounts", planned: true },
      { label: "EOSS Planning", to: "/offers/eoss", planned: true },
    ],
  },
  {
    code: "staff",
    label: "Staff",
    icon: Users,
    layer: "edges",
    items: [
      { label: "Attendance", to: "/staff/attendance", planned: true },
      // A cashier holds Staff for their *own* attendance ("Own attendance
      // (derived)"), so employee records and salary stay off their menu. A store
      // *manager* holds `staff: manage` for their own store — the sketch makes
      // managing the store's members their job — so Members appears for them and
      // not for the cashier, from the same server-sent capability.
      { label: "Members", to: "/staff/members", minCapability: "manage", planned: true },
      { label: "Payroll", to: "/staff/payroll", roles: PAYROLL_ROLES, planned: true },
    ],
  },
  {
    code: "reports",
    label: "Reports",
    icon: BarChart3,
    layer: "intelligence",
    items: [
      { label: "Sales Reports", to: "/reports/sales", planned: true },
      { label: "Stock Reports", to: "/reports/stock", planned: true },
      { label: "Profit", to: "/reports/profit", planned: true },
      { label: "Daily Summary", to: "/reports/daily", planned: true },
      { label: "Report Maker", to: "/reports/maker", planned: true },
    ],
  },
  {
    code: "setup",
    label: "Setup",
    icon: Settings,
    layer: "master",
    items: [
      { label: "Products", to: "/setup/products", planned: true },
      { label: "Stores", to: "/setup/stores" },
      { label: "Brands", to: "/setup/brands" },
      // The vendor master had no screen at all: vendors could only be created
      // through the API, and never corrected. Bookings, GRNs and every payable
      // hang off this row, so it belongs beside Brands (one vendor, many brands).
      { label: "Vendors", to: "/setup/vendors" },
      { label: "Seasons", to: "/setup/seasons" },
      { label: "GSTINs", to: "/setup/gstins" },
      { label: "Users & Roles", to: "/setup/users", minCapability: "manage" },
      { label: "Audit Log", to: "/setup/audit", planned: true },
      { label: "Settings", to: "/setup/settings", planned: true },
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
  ["/masters/vendors", "/setup/vendors"],
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

/** One pathname shape for everything that keys on a path. Lowercase, because
 *  React Router matches paths case-insensitively and a bookmarked
 *  `/Ledgers/Vendor` must behave like `/ledgers/vendor`; trailing slashes
 *  dropped, because `/money/vendor/` is the same screen as `/money/vendor`. */
export function normalizePath(pathname: string): string {
  return pathname.toLowerCase().replace(/\/+$/, "") || "/";
}

/** The new home of an old URL, or null if `pathname` is not a legacy path. */
export function resolveLegacyPath(pathname: string): string | null {
  const normalized = normalizePath(pathname);
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

/** The deepest eligible item whose path `pathname` sits at or under. Longest
 *  wins, so `/receive/pt` is PT Files and not Receive (GRN), while `/booking/12`
 *  — a document with no line of its own — still resolves to Bookings. */
function deepestUnder(
  pathname: string,
  eligible: (item: NavItem) => boolean,
): (NavItem & { section: string }) | null {
  const normalized = normalizePath(pathname);
  let best: (NavItem & { section: string }) | null = null;
  for (const item of NAV_ITEMS) {
    if (!eligible(item)) continue;
    const path = itemPath(item);
    if (!underPrefix(normalized, path)) continue;
    if (!best || path.length > itemPath(best).length) best = item;
  }
  return best;
}

/** The one screen a URL belongs to — what the route guard gates on. A deep link
 *  owns no URL (the section hosting the screen keeps it), but an `action` screen
 *  does own one and carries its own gate, so it counts here. */
export function itemOwning(pathname: string): (NavItem & { section: string }) | null {
  return deepestUnder(pathname, (i) => !i.deepLink);
}

/** Does this menu line get the highlight at `pathname`? Exactly one line does.
 *
 *  Pass the item, not its path: "Damage / Quarantine" *is* `/stock` once its
 *  `?view=` is dropped, so comparing paths alone would light it alongside Stock
 *  on Hand in another section. Screens with no line of their own fall back to
 *  the nearest one that has — a V-flip keeps Stock on Hand lit, the same way a
 *  booking document keeps Bookings lit — so the sidebar never goes dark under
 *  you. Letting React Router answer this instead lit every ancestor too. */
export function isActiveItem(item: NavItem, pathname: string): boolean {
  if (item.deepLink || item.action) return false;
  const lit = deepestUnder(pathname, (i) => !i.deepLink && !i.action);
  return !!lit && itemPath(item) === itemPath(lit);
}

/** Is this item on the menu for a caller holding `held` on the item's section?
 *  The sidebar gates the menu line and `routeAccess` gates the URL, reading two
 *  different halves of the same login payload — so the rule itself lives here
 *  once and the two cannot drift into hiding a link the URL still opens. */
export function itemVisible(
  item: NavItem,
  held: string | undefined,
  roleCode: string,
  isSuperuser: boolean,
): boolean {
  if (isSuperuser) return true;
  if (item.minCapability && !meetsCapability(held, item.minCapability)) return false;
  if (item.roles && !item.roles.includes(roleCode)) return false;
  return true;
}
