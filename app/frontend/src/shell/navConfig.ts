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
  Warehouse,
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
// `hrms: view` ("payroll inputs") while a store person must not, and the store
// person sits *higher* on the ladder at `hrms: operate` ("own attendance").
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
  /** Gate for a URL strictly *under* this item's own path, when it differs from
   *  `minCapability` — a document a caller may still open even though the
   *  list/create screen that owns its URL prefix now needs a higher rung. PT
   *  making rose to `approve` (#119) while reading a PT already made stays at
   *  whatever rung holding the section at all requires — reading and making are
   *  different rights, and only making moved. Undefined ⇒ a child shares the
   *  item's own `minCapability`, the older and still-default behaviour (a
   *  booking document, for instance, has no gate of its own to differ). */
  childMinCapability?: Capability;
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
      { label: "Alerts", to: "/alerts" },
    ],
  },
  {
    code: "sell",
    label: "Sell",
    icon: ShoppingCart,
    layer: "store",
    items: [
      // The counter itself (#181). `operate` for the same reason Till & Sync
      // carries it: this screen bills, and every endpoint behind it is gated at
      // `sell: operate`.
      { label: "Billing", to: "/sell", minCapability: "operate" },
      // Taking a piece back (#184). `operate`, the same rung as billing and for
      // the same reason: an exchange *is* a bill, and `POST /api/sell/returns`
      // is gated at `sell: operate` too. The second pair of eyes on a plain
      // return is not a rung at all - it is a named manager of this store,
      // asked for on every single one.
      // The counter owns this flow now. The route remains until its direct
      // handoff retires in slice 8, but it is no longer a published tab.
      { label: "Return & Exchange", to: "/sell/returns", action: true, minCapability: "operate" },
      // Finding an old bill and printing it again (#185). `view`, not `operate`:
      // `GET /api/sell/sales` is gated at `sell: view` and this screen cannot
      // write, so an owner or an accountant reaching a customer's bill is the
      // matrix working rather than a hole in it.
      // Find-bill remains a guarded route reached from the counter (F3), not a
      // second public Sell destination.
      { label: "Customers", to: "/sell/customers", action: true, minCapability: "view" },
      // The counter's own state: what it holds offline, and what it still owes
      // head office (#180). Listed after the screens a cashier uses all day,
      // because it is the page somebody opens when something looks wrong.
      //
      // `operate`, not the section's own rung: both endpoints behind this page
      // are gated at `sell: operate` (`sell/permissions.py`), because the
      // dataset is the working copy a counter bills from rather than a report
      // about selling. Offering the entry at `view` would walk an owner or an
      // accountant into a 403.
      { label: "Till & Sync", to: "/sell/till", minCapability: "operate" },
      // The card lives at the Setup address because it is a head-office dial,
      // but it is published under Sell: its API is `sell:manage`, and a user
      // who holds that permission need not hold Setup at all.
      { label: "Counter Settings", to: "/setup/settings", minCapability: "manage" },
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
      // "Receive", not "Receive (GRN)" (#228). GRN stays in the working
      // vocabulary where it names the document - the number, the table column -
      // but the menu line and the page title are the plain verb.
      //
      // There is no "Upload Bill" line beside it: the bill upload already lives
      // inside "New receipt", so a second entry promised a screen that would
      // only have sent people back here.
      { label: "Receive", to: "/receive" },
      // PT making moved to the warehouse's rung (#119): this line - the
      // Mapper-upload and from-GRN authoring workspace - needs
      // `receive_goods: approve`, so it drops off the store's sidebar on its
      // own. A PT already made stays open to read (`/receive/pt/:id`, reached
      // from its GRN) at whatever rung holding the section requires.
      { label: "PT Files", to: "/receive/pt", minCapability: "approve", childMinCapability: "view" },
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
      { label: "Stock Request", to: "/transfer/requests" },
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
      // The counter's question, not the back office's: "who has this in L?"
      // (#175). It reads every store deliberately — a registered scoping
      // exception — and carries quantities only, so it sits at the same `view`
      // rung a store person already holds on this section.
      { label: "Search Across Stores", to: "/stock/search" },
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
      // What the counter took today, by tender, and what the day left open
      // (#188). No `minCapability`, so it sits at the section's own `view` rung:
      // the ratified sheet gives both store seats `money: operate` ("Expenses
      // only (create)"), and a store reading its own day back is the whole point
      // of the screen. The exceptions underneath are cleared at `operate`, which
      // is the same seat - so nothing here shows a person a button the API
      // refuses (#85).
      { label: "Day Summary", to: "/money/day-summary" },
      { label: "Payments", to: "/money/payments", planned: true, minCapability: "manage" },
      // The store × month rupee target the Dashboard is measured against (#171).
      // It is a master, so Setup is where a reader might look for it - but the
      // gate it answers to is `money: manage`, and a nav item's gate *is* its
      // section's (routeAccess derives one from the other). Filed under Setup it
      // would show the Data Steward a screen the API refuses them, which is the
      // sidebar-lies-about-the-API failure #85 exists to prevent. Reading it
      // needs only the Money section, so the item carries no `minCapability`:
      // a store person sees their own store's number and the cells are text.
      { label: "Store Targets", to: "/money/store-targets" },
      { label: "Vendor Ledger", to: "/money/vendor", minCapability: "manage" },
      { label: "Cash", to: "/money/cash", minCapability: "manage" },
      // The B2B bills head office still owes an e-invoice reference (#187).
      //
      // Filed under Money rather than Sell, and that is the gate deciding the
      // filing rather than the other way round. Raising an IRN is a statutory
      // duty of the people who file the returns; `sell: operate` is the *store*,
      // which would put it on a cashier's sidebar, and `sell: manage` is the IT
      // administrator alone, who holds no money on the ratified sheet. The
      // endpoint behind it is gated at `money: manage` for the same reason, so
      // the sidebar and the API agree (#85).
      { label: "IRN Queue", to: "/money/irn-queue", minCapability: "manage" },
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
      { label: "Offers", to: "/offers" },
      { label: "Discounts", to: "/offers/discounts", planned: true },
      { label: "EOSS Planning", to: "/offers/eoss", planned: true },
    ],
  },
  {
    code: "hrms",
    label: "HRMS",
    icon: Users,
    layer: "edges",
    items: [
      { label: "Attendance", to: "/staff/attendance", planned: true },
      // A cashier holds HRMS for their *own* attendance ("Own attendance
      // (derived)"), so employee records and salary stay off their menu. A store
      // *manager* holds `hrms: manage` for their own store — the sketch makes
      // managing the store's members their job — so Member Details appears for
      // them and not for the cashier, from the same server-sent capability.
      {
        label: "Member Details",
        to: "/staff/members",
        minCapability: "manage",
        planned: true,
      },
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
      // The access matrix as its own screen (#173): Users & Roles edits one role
      // at a time, this compares all nine at once and is where the money floors
      // are visible. Same rung - reading who may do what is Setup's top rung.
      { label: "Access", to: "/setup/access", minCapability: "manage" },
      { label: "Audit Log", to: "/setup/audit", planned: true },
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
  // The Upload Bill stub, deleted in #228 - the bill goes up inside "New
  // receipt". Anyone holding the old link lands on Receive.
  ["/receive/upload-bill", "/receive"],
  // The Distribution stub, deleted in #229 - the stub is gone for every role,
  // and distribution returns later as a rare-case feature of a transfer.
  ["/transfer/distribution", "/transfer"],
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

/** Every address the manifest has moved away from. The route table reads it to
 *  spot the one that a dynamic route would otherwise claim (see routes.tsx),
 *  so which paths are legacy is stated once, here. */
export const LEGACY_PATHS: string[] = LEGACY_PREFIXES.map(([from]) => from);

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

// ---------------------------------------------------------------------------
// Persona layouts (#96, reshaped by #170) - how one persona's sidebar is
// *arranged*.
//
// The sections above are shared vocabulary and the server decides which of them
// a person gets. Neither changes here. What changes is the order they are drawn
// in, and whether several of them are drawn as one *folded* page.
//
// D10 settled the store login's shape: ten flat sections, and no subsections in
// the sidebar, ever - anything that needs dividing divides inside the page, as
// tabs. So #96's grouping heading (a label with three section heads nested
// under it) is gone, and in its place is a fold: one link, one URL, and the
// folded sections' screens drawn on that page as tabs.
//
// Three rules this must not break, all of them tested below in navConfig.test:
//   · Arranging runs *after* access, over whatever the server's section list
//     leaves standing. It can only ever draw less, never more.
//   · A tab's gate is the gate of the menu entry it draws. Folding is
//     presentation, so a tab can never open a screen the sidebar would have
//     hidden - a role without count rights simply sees no Count & Adjust tab.
//   · Names never change, with two conscious exceptions Anand made for the
//     store persona alone (#84 as amended, #229): Home reads "Dashboard" and
//     HRMS reads "Attendance" there. Every other section keeps the word the
//     warehouse and HO use for it - a store person and the warehouse both
//     say "Transfer".
//
// A role with no layout gets the flat list, which is what keeps every other
// persona byte-identical to before this file grew this section.

/** One tab of a folded page. */
export interface FoldTab {
  /** The `?tab=` value. Stable, because it ends up in people's URLs. */
  slug: string;
  label: string;
  /** The manifest entry whose screen this tab draws, by its `to`. Naming the
   *  entry rather than restating a section code is what keeps the tab's gate
   *  and the screen's standalone URL in one place. */
  entry: string;
}

/** Several sections drawn as one link, their screens recomposed as tabs on one
 *  page. Unlike a section head it owns a URL - but it owns no section code and
 *  no capability, because every tab keeps the gate of the entry it draws. */
export interface NavFoldDef {
  heading: string;
  icon: LucideIcon;
  /** CSS `--layer-*` token suffix, as on a section. */
  layer: string;
  /** The one URL. Its tabs are `?tab=<slug>` under it. */
  to: string;
  /** Section codes this fold stands in for; their heads leave the sidebar. */
  sections: string[];
  tabs: FoldTab[];
}

/** One section drawn as a single sidebar link, its own screens recomposed as a
 *  horizontal tab row on those screens themselves (#227).
 *
 *  A fold merges several sections onto one new URL it owns. A strip owns no URL
 *  at all: its tabs are the section's existing canonical routes, and the tab row
 *  is plain navigation between them (grill decision 1). So no screen is edited
 *  to gain tabs, no route is added, and a bookmark keeps working - the strip is
 *  presentation laid over URLs that already exist.
 *
 *  It owns no capability either: every tab is a menu entry of `section`, and
 *  keeps that entry's gate. Folding a section can only ever subtract. */
export interface NavStripDef {
  /** The section code this row stands for. Its head leaves the sidebar. */
  section: string;
  /** This persona's name for the row. Absent ⇒ the section's own label. */
  label?: string;
  /** The entries drawn as tabs, by their `to`, in display order. */
  tabs: string[];
}

/** One row of a persona's sidebar: a section code, a fold, or a strip. */
export type LayoutRow = string | NavFoldDef | NavStripDef;

/** Is this layout row a strip? A fold names several `sections`; a strip names
 *  the one `section` it is. The two predicates are each other's complement over
 *  the non-string rows, and every place that has to tell the shapes apart calls
 *  one of them rather than re-writing the test. */
export function isStripRow(row: LayoutRow): row is NavStripDef {
  return typeof row !== "string" && "section" in row;
}

/** Is this layout row a fold? */
export function isFoldRow(row: LayoutRow): row is NavFoldDef {
  return typeof row !== "string" && !isStripRow(row);
}

/** The rows, top to bottom. A section held but named nowhere here is still
 *  drawn - appended after these rows - so retuning somebody's access can never
 *  silently lose them a section. */
export type PersonaLayout = LayoutRow[];

// Inventory (D10 §1): Stock, Stock Count and Return to Brand fold into one
// page. Four tabs over three section codes - Damage & Quarantine and Return to
// Brand are both Return to Brand's, which is where a store's "mark damage only"
// right already lives.
export const INVENTORY_FOLD: NavFoldDef = {
  heading: "Inventory",
  icon: Warehouse,
  layer: "store",
  to: "/inventory",
  sections: ["stock", "stock_count", "return_to_brand"],
  tabs: [
    { slug: "stock", label: "Stock on Hand", entry: "/stock" },
    // The store persona's only way to this screen until the Dashboard's
    // quick-actions row lands (#174): the fold *is* their Stock section, so a
    // tab left off it is unreachable for exactly the people it was built for.
    { slug: "search", label: "Search Across Stores", entry: "/stock/search" },
    { slug: "damage", label: "Damage & Quarantine", entry: "/stock?view=quarantine" },
    { slug: "count", label: "Count & Adjust", entry: "/stock-count" },
    { slug: "returns", label: "Return to Brand", entry: "/return-to-brand" },
  ],
};

// Sell's published pair after the counter absorbed Return & Exchange and
// Customers (#267). The hidden routes above retain their guard while slice 8
// moves the real flow; they are deliberately not navigation tabs.
export const SELL_STRIP: NavStripDef = {
  section: "sell",
  tabs: ["/sell", "/sell/till"],
};

// The store's own screen, as D10 decided it on 30 July 2026: ten sections, in
// this order, one row each, and no subsections ever - anything a section needs
// to divide does it inside the page, as tabs (#229). Sell and Inventory proved
// the two mechanisms first (#227, #170); this slice turns the rest into strips.
// Home becomes "Dashboard" - the store dashboard that carries approvals and
// alerts as cards (#174) - and HRMS becomes "Attendance", both consciously
// renamed for the store persona alone (see the amendment above). Approvals and
// Alerts stay in the manifest as Home's own items; they are simply not one of
// Dashboard's tabs, so they stay reachable by URL and from the bell, never from
// this row.
const STORE_LAYOUT: PersonaLayout = [
  { section: "home", label: "Dashboard", tabs: ["/"] },
  SELL_STRIP,
  INVENTORY_FOLD,
  { section: "receive_goods", tabs: ["/receive"] },
  { section: "transfer", tabs: ["/transfer", "/transfer/requests", "/transfer/in-transit"] },
  { section: "booking", tabs: ["/booking"] },
  { section: "money", tabs: ["/money/day-summary", "/money/store-targets", "/money/expenses"] },
  {
    section: "offers_price",
    tabs: ["/offers/price-list", "/offers", "/offers/discounts", "/offers/eoss"],
  },
  {
    section: "reports",
    tabs: ["/reports/sales", "/reports/stock", "/reports/profit", "/reports/daily", "/reports/maker"],
  },
  // Member Details and Payroll are not tabs here - a store manager's extra
  // `hrms: manage` rung would otherwise add Member Details, and D10 §10 keeps
  // this row to the one built screen (Attendance is a placeholder; the grill
  // rules the manager loses nothing real today).
  { section: "hrms", label: "Attendance", tabs: ["/staff/attendance"] },
];

/** Role code → its sidebar arrangement. Absent ⇒ the flat list. Both store role
 *  codes share the store's screen: a manager and a cashier differ only in what
 *  the server grants them, and the layout does not need to know about that. */
export const PERSONA_LAYOUTS: Record<string, PersonaLayout> = {
  store_manager: STORE_LAYOUT,
  store_staff: STORE_LAYOUT,
};

/** Every fold any persona is drawn, once. */
const FOLDS: NavFoldDef[] = [
  ...new Set(
    Object.values(PERSONA_LAYOUTS)
      .flat()
      .filter(isFoldRow),
  ),
];

/** A fold's key, in the same namespace as a section code - which is why it is
 *  prefixed rather than being the bare heading. */
export function foldKey(fold: NavFoldDef): string {
  return `fold:${fold.to}`;
}

/** The folded page a URL *is*, or null. A fold owns its URL outright: no menu
 *  entry points at `/inventory`, so `itemOwning` cannot answer for it and the
 *  route guard would default-allow it.
 *
 *  Exact, not by prefix: a fold's gate is "any one of my tabs", which is the
 *  loosest gate in the manifest. A screen routed under `/inventory/...` later
 *  must carry its own, not inherit this one by sitting beneath it. */
export function foldOwning(pathname: string): NavFoldDef | null {
  const normalized = normalizePath(pathname);
  return FOLDS.find((f) => normalized === f.to) ?? null;
}

/** A section the signed-in user actually gets, with its visible items. The
 *  server decides *which* sections (#85); the manifest says what is in one; an
 *  item gate can still hide an individual line. */
export interface VisibleSection {
  def: NavSectionDef;
  label: string;
  items: NavItem[];
}

const SECTION_DEFS = new Map(SECTIONS.map((s) => [s.code, s]));

/** The sections this person gets, with their visible items - the one access
 *  filter, and the only authority on what may be drawn. Everything below it
 *  (arranging, grouping, collapsing) consumes its output and can only subtract.
 *
 *  Typed structurally rather than against `User`, so the manifest keeps no
 *  dependency on the auth module. */
export function visibleSections(user: {
  role?: { code?: string } | null;
  is_superuser: boolean;
  sections?: { code: string; label?: string; capability: string }[];
}): VisibleSection[] {
  const roleCode = user.role?.code ?? "";
  const out: VisibleSection[] = [];
  // Server order, not manifest order - the payload is the authority on both
  // which sections and in what order. Fail-closed: no payload ⇒ no sidebar.
  for (const granted of user.sections ?? []) {
    const def = SECTION_DEFS.get(granted.code);
    if (!def) continue; // a section the server knows and this build doesn't
    // Item gates are finer than the section: the rung held on *this* section
    // (`minCapability`) or, where the ladder can't express it, a role list. The
    // break-glass superuser passes both.
    const items = def.items.filter(
      (i) => !i.action && itemVisible(i, granted.capability, roleCode, user.is_superuser),
    );
    // Every item gated away ⇒ nothing to navigate to; don't show an empty head.
    if (items.length) out.push({ def, label: granted.label || def.label, items });
  }
  return out;
}

/** A row of the rendered sidebar. */
export type NavRow =
  | { kind: "section"; key: string; section: VisibleSection }
  | { kind: "fold"; key: string; fold: NavFoldDef; tabs: FoldTab[] }
  | {
      kind: "strip";
      key: string;
      strip: NavStripDef;
      /** The section the strip stands for - its icon, layer and fallback label.
       *  Resolved here because a row only exists where the section does. */
      def: NavSectionDef;
      label: string;
      /** Never empty: a strip with no visible tab is not drawn at all. */
      tabs: NavItem[];
    };

/** A strip's key, in the same namespace as a section code and a fold's key. */
export function stripKey(strip: NavStripDef): string {
  return `strip:${strip.section}`;
}

/** The tabs of `fold` this person may see, in the fold's own order.
 *
 *  Reads the *output* of the access filter, so a tab exists only where the menu
 *  entry behind it survived that filter: folding four screens onto one page can
 *  never show one of them to somebody the sidebar would have refused it to.
 *
 *  A deep-link entry needs both halves. "Damage / Quarantine" is Return to
 *  Brand's line onto Stock's screen, and the two carry different gates - the
 *  line answers to Return to Brand, the URL to Stock - so a tab drawing it must
 *  clear the pair, exactly as clicking the line and landing on the screen does. */
export function foldTabs(fold: NavFoldDef, sections: VisibleSection[]): FoldTab[] {
  const passed = new Set(sections.flatMap((s) => s.items.map((i) => i.to)));
  return fold.tabs.filter((t) => {
    if (!passed.has(t.entry)) return false;
    const host = itemOwning(t.entry.split("?")[0]);
    return !host || passed.has(host.to);
  });
}

/** The tabs of `fold` one signed-in person may see. The guard and the page both
 *  ask this, so what the URL opens and what the page draws cannot disagree. */
export function foldTabsFor(
  fold: NavFoldDef,
  user: Parameters<typeof visibleSections>[0] | null | undefined,
): FoldTab[] {
  return user ? foldTabs(fold, visibleSections(user)) : [];
}

/** The tabs of `strip` this person may see, in the strip's own order.
 *
 *  Reads the *output* of the access filter, exactly as `foldTabs` does: a tab
 *  exists only where the menu entry behind it survived that filter, so a strip
 *  can never show a screen the sidebar would have hidden. An entry the section
 *  no longer carries at all simply has no tab. */
export function stripTabs(strip: NavStripDef, sections: VisibleSection[]): NavItem[] {
  const section = sections.find((s) => s.def.code === strip.section);
  if (!section) return [];
  const byPath = new Map(section.items.map((i) => [i.to, i]));
  return strip.tabs.flatMap((to) => {
    const item = byPath.get(to);
    return item ? [item] : [];
  });
}

/** This persona's name for a strip row: its own override, else whatever the
 *  server called the section, else the manifest's label. */
export function stripLabel(strip: NavStripDef, sections: VisibleSection[]): string {
  const section = sections.find((s) => s.def.code === strip.section);
  return strip.label ?? section?.label ?? SECTION_DEFS.get(strip.section)?.label ?? strip.section;
}

/** The strip whose section owns this URL for this persona, or null.
 *
 *  Per persona, because a strip is an arrangement: an owner whose sidebar still
 *  expands Sell gets no strip and so no redundant second copy of their own menu.
 *  Asked of `itemOwning`'s *section*, not its tab list (#229): a screen the
 *  strip lists no tab for - `/transfer/new`, `/receive/pt/12`, `/approvals`
 *  under the Home strip - still belongs to a section this persona's sidebar
 *  strips, so the row still lights. Whether a *tab row* is worth drawing there
 *  is `sectionTabsFor`'s question, not this one. */
export function stripOwning(pathname: string, roleCode: string): NavStripDef | null {
  // Asked of `itemOwning` rather than walked again here: which screen a URL
  // belongs to is already the manifest's one rule, and a second walk beside it
  // is a second answer waiting to disagree with the route guard.
  const owner = itemOwning(pathname);
  if (!owner) return null;
  const strips = (PERSONA_LAYOUTS[roleCode] ?? []).filter(isStripRow);
  return strips.find((s) => s.section === owner.section) ?? null;
}

/** The tab lit at `pathname`: the one whose path is the deepest prefix of it, so
 *  a child URL keeps its parent tab lit (`/sell/returns/12` lights Return &
 *  Exchange, a bill under `/sell/9` lights Billing). Null when this person holds
 *  no tab covering where they are standing. */
export function activeStripTab(tabs: NavItem[], pathname: string): NavItem | null {
  const normalized = normalizePath(pathname);
  let best: NavItem | null = null;
  for (const tab of tabs) {
    const path = itemPath(tab);
    if (!underPrefix(normalized, path)) continue;
    if (!best || path.length > itemPath(best).length) best = tab;
  }
  return best;
}

/** The tab row a stripped section puts on its own screens, or null for no row.
 *
 *  The whole decision in one place, because the shell only draws it: which strip
 *  owns this URL for this persona, which of its tabs access left standing, which
 *  one is lit, and what the header calls the row. Null - draw nothing - covers
 *  the three cases the grill named: a persona whose sidebar still expands the
 *  section, a strip access has cut to a single tab (a strip of one is not a
 *  choice), and a URL none of the surviving tabs covers. */
export interface SectionTabs {
  /** The eyebrow: the strip's row name. */
  crumb: string;
  /** The lit tab's name, which is this screen's title. */
  title: string;
  tabs: NavItem[];
  active: NavItem;
}

export function sectionTabsFor(
  pathname: string,
  user: Parameters<typeof visibleSections>[0] | null | undefined,
): SectionTabs | null {
  if (!user) return null;
  const strip = stripOwning(pathname, user.role?.code ?? "");
  if (!strip) return null;
  const sections = visibleSections(user);
  const tabs = stripTabs(strip, sections);
  if (tabs.length < 2) return null;
  const active = activeStripTab(tabs, pathname);
  if (!active) return null;
  return { crumb: stripLabel(strip, sections), title: active.label, tabs, active };
}

/** The tab `slug` names, or the first one this person can see. An unknown slug,
 *  or one whose tab this person is not shown, falls back rather than leaving
 *  them on a page with nothing on it. */
export function resolveFoldTab(tabs: FoldTab[], slug: string | null): FoldTab | null {
  return tabs.find((t) => t.slug === slug) ?? tabs[0] ?? null;
}

/** Arrange the sections this person holds into their persona's rows.
 *
 *  Takes the *output* of the access filter and only ever reorders, folds or
 *  drops what is already in it - so no arrangement can put a section in front
 *  of somebody the server did not send it to. */
export function applyLayout(sections: VisibleSection[], roleCode: string): NavRow[] {
  const layout = PERSONA_LAYOUTS[roleCode];
  if (!layout) {
    return sections.map((s) => ({ kind: "section", key: s.def.code, section: s }));
  }

  const byCode = new Map(sections.map((s) => [s.def.code, s]));
  const rows: NavRow[] = [];
  const spokenFor = new Set<string>();
  for (const row of layout) {
    if (typeof row === "string") {
      spokenFor.add(row);
      const s = byCode.get(row);
      if (s?.items.length) rows.push({ kind: "section", key: row, section: s });
      continue;
    }
    if (isStripRow(row)) {
      // A strip speaks for its section whether or not any tab survives: the
      // head is gone from this persona's sidebar either way.
      spokenFor.add(row.section);
      const section = byCode.get(row.section);
      const tabs = stripTabs(row, sections);
      // No tab this person can see ⇒ nowhere for the row to land; don't draw it.
      if (section && tabs.length) {
        rows.push({
          kind: "strip",
          key: stripKey(row),
          strip: row,
          def: section.def,
          label: stripLabel(row, sections),
          tabs,
        });
      }
      continue;
    }
    // A fold speaks for its sections whether or not it draws a tab for each of
    // them: the heads are gone from this persona's sidebar either way, and the
    // page is where those screens now live.
    for (const code of row.sections) spokenFor.add(code);
    const tabs = foldTabs(row, sections);
    // No tab this person can see ⇒ nothing on the page; don't draw the link.
    if (tabs.length) rows.push({ kind: "fold", key: foldKey(row), fold: row, tabs });
  }

  // Held, but named nowhere in the layout - an admin can retune access, so this
  // is a real case and not a defect. Appended in the server's order rather than
  // dropped: a sidebar that quietly loses a section somebody was just granted is
  // worse than one whose last row is in an unexpected place.
  for (const s of sections) {
    if (spokenFor.has(s.def.code) || !s.items.length) continue;
    rows.push({ kind: "section", key: s.def.code, section: s });
  }
  return rows;
}

/** The whole sidebar for one signed-in person: what they may see, arranged the
 *  way their persona reads it. One call, so the two steps can only happen in
 *  that order - access first, arrangement second. */
export function sidebarRows(user: {
  role?: { code?: string } | null;
  is_superuser: boolean;
  sections?: { code: string; label?: string; capability: string }[];
}): NavRow[] {
  return applyLayout(visibleSections(user), user.role?.code ?? "");
}

/** The test handle for a menu line, as `nav-<section>-<screen>`. A deep link
 *  keeps its `?view=`, because its path alone is the host section's own screen:
 *  drawn under Stock, "Damage / Quarantine" would otherwise answer to the same
 *  handle as "Stock on Hand". */
export function testId(sectionCode: string, item: NavItem): string {
  const tail = itemPath(item).split("/").pop() || "home";
  const view = item.to.split("?view=")[1];
  return `nav-${sectionCode}-${tail}${view ? `-${view}` : ""}`;
}

/** Every section drawn as its own head in `rows`. A fold draws no section head
 *  - its sections are tabs on one page - so it contributes none. */
export function sectionsIn(rows: NavRow[]): VisibleSection[] {
  return rows.flatMap((r) => (r.kind === "section" ? [r.section] : []));
}

/** Does `row` draw as a single line - a link straight to a screen, rather than
 *  a head with several items under it? True for a fold and a strip, whose
 *  whole point is to be one line, and for a section access has cut to exactly
 *  one visible item. This is the same question the sidebar's own
 *  `renderSection` already answers to decide whether a section draws as
 *  `oneLineRow` or as a toggle over `.nav-items` (#96) - and, since #230, the
 *  question the icon rail asks to decide "navigate on click" versus "open a
 *  flyout". One predicate, so the two can never draw a different answer for
 *  the same row. */
export function isOneLineRow(row: NavRow): boolean {
  return row.kind !== "section" || row.section.items.length === 1;
}

/** Is the folded page where this person is standing? True on the fold's own URL
 *  and on any standalone screen it folds - so a store person who lands on
 *  `/stock` from the global search still sees which row they are on. */
export function isActiveFold(fold: NavFoldDef, pathname: string): boolean {
  if (underPrefix(normalizePath(pathname), fold.to)) return true;
  const owner = itemOwning(pathname);
  return !!owner && fold.sections.includes(owner.section);
}

/** The key of the sidebar row this person's screen is drawn under - a section
 *  code, or a fold's key. What the sidebar has to unfold to show where you are;
 *  a folded page draws as one link and so has nothing to unfold. */
export function headingOwning(pathname: string, roleCode: string): string | null {
  const layout = PERSONA_LAYOUTS[roleCode] ?? [];
  const folds = layout.filter(isFoldRow);
  const here = folds.find((f) => isActiveFold(f, pathname));
  if (here) return foldKey(here);
  const strip = stripOwning(pathname, roleCode);
  if (strip) return stripKey(strip);
  for (const section of SECTIONS) {
    if (section.items.some((i) => isActiveItem(i, pathname))) return section.code;
  }
  return null;
}
