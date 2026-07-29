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

// ---------------------------------------------------------------------------
// Persona layouts (#96) - how one persona's sidebar is *arranged*.
//
// The sections above are shared vocabulary and the server decides which of them
// a person gets. Neither changes here. What changes is the order they are drawn
// in and which heading they sit under, because a store person asked - twice, a
// month apart - for their own screen: Home, Sell, one "Inventory" heading over
// the goods work, Reports, Staff, Stock Count, Money, Offers & Price.
//
// Three rules this must not break, all of them tested below in navConfig.test:
//   · Grouping runs *after* access, over whatever the server's section list
//     leaves standing. It can only ever draw less, never more.
//   · An entry's gate travels with the entry. Attendance drawn under Home is
//     still Staff's entry with Staff's gate; moving it changes nobody's access.
//   · Names never change. Grouping is allowed, renaming is not (#84 as amended)
//     - a store person and the warehouse both say "Transfer" on the phone.
//
// A role with no layout gets the flat list, which is what keeps every other
// persona byte-identical to before this file grew this section.

/** A heading with sections nested under it. It owns no route, no section code,
 *  no capability and no server counterpart - it is a label and an order. */
export interface NavGroupDef {
  heading: string;
  icon: LucideIcon;
  /** CSS `--layer-*` token suffix, as on a section. */
  layer: string;
  /** Section codes drawn under this heading, in this order. */
  sections: string[];
}

/** One row of a persona's sidebar: a section code, or a grouping heading. */
export type LayoutRow = string | NavGroupDef;

export interface PersonaLayout {
  /** The rows, top to bottom. A section held but named nowhere here is still
   *  drawn - appended after these rows - so retuning somebody's access can
   *  never silently lose them a section. */
  rows: LayoutRow[];
  /** Sections this persona does not get a heading for. The capability is
   *  untouched and the URL still opens; only the menu line goes. Use it with an
   *  entry in `relocate` for anything that must stay one click away. */
  hide: string[];
  /** Entries drawn under a heading other than their own section's, keyed by the
   *  entry's `to`. `after` places it directly below that entry in the host, else
   *  it goes last. If the host section is not held, the entry stays where it is
   *  - the move is presentation, so it can never be the reason something goes
   *  missing. */
  relocate: Record<string, { under: string; after?: string }>;
}

// The store's own screen, from the 30 June and 25 July store notes.
//
// Two entries move, and both moves are named by Anand's ruling of 26 July:
// Attendance is drawn under Home ("Home only"), and Damage / Quarantine is
// drawn under Stock, which is the section that already owns that screen. That
// second move is what lets Return to Brand leave the sidebar without anything
// becoming unreachable - a store person keeps "mark damage only" and reaches it
// in one click, they just no longer see a Returns heading they cannot use.
const STORE_LAYOUT: PersonaLayout = {
  rows: [
    "home",
    "sell",
    {
      heading: "Inventory",
      icon: Warehouse,
      layer: "store",
      sections: ["receive_goods", "transfer", "stock"],
    },
    "reports",
    // Reads "HRMS" (#118 renamed it from "Staff"); with Attendance moved to
    // Home it holds one visible item (Member Details, for a manager) and so
    // draws as one line.
    "hrms",
    "stock_count",
    "money",
    "offers_price",
  ],
  hide: ["return_to_brand"],
  relocate: {
    "/staff/attendance": { under: "home", after: "/" },
    "/stock?view=quarantine": { under: "stock" },
  },
};

/** Role code → its sidebar arrangement. Absent ⇒ the flat list. Both store role
 *  codes share the store's screen: a manager and a cashier differ only in what
 *  the server grants them, and the layout does not need to know about that. */
export const PERSONA_LAYOUTS: Record<string, PersonaLayout> = {
  store_manager: STORE_LAYOUT,
  store_staff: STORE_LAYOUT,
};

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
  | { kind: "group"; key: string; group: NavGroupDef; sections: VisibleSection[] };

/** Arrange the sections this person holds into their persona's rows.
 *
 *  Takes the *output* of the access filter and only ever reorders, nests or
 *  drops what is already in it - so no arrangement can put a section in front
 *  of somebody the server did not send it to. */
export function applyLayout(sections: VisibleSection[], roleCode: string): NavRow[] {
  const layout = PERSONA_LAYOUTS[roleCode];
  if (!layout) {
    return sections.map((s) => ({ kind: "section", key: s.def.code, section: s }));
  }

  // Copy before moving anything: the caller's list is derived from the login
  // payload and other screens read it.
  const byCode = new Map(sections.map((s) => [s.def.code, { ...s, items: [...s.items] }]));

  for (const [to, target] of Object.entries(layout.relocate)) {
    const host = byCode.get(target.under);
    if (!host) continue;
    for (const source of byCode.values()) {
      if (source === host) continue;
      const at = source.items.findIndex((i) => i.to === to);
      if (at < 0) continue;
      const [entry] = source.items.splice(at, 1);
      const after = target.after ? host.items.findIndex((i) => i.to === target.after) : -1;
      host.items.splice(after < 0 ? host.items.length : after + 1, 0, entry);
    }
  }

  /** The section, if this person holds it and it still has a line to show.
   *  Relocation can empty a section (a cashier's Staff is Attendance and
   *  nothing else), and an empty heading is a dead end. */
  function drawable(code: string): VisibleSection | null {
    const s = byCode.get(code);
    return s && s.items.length ? s : null;
  }

  // A hidden section is only safe to hide once the entries the layout moves out
  // of it have actually landed. Return to Brand leaves the store's sidebar
  // *because* Damage / Quarantine is drawn under Stock - so if a retune ever
  // leaves somebody holding Return to Brand without Stock, the heading comes
  // back rather than taking the only entry they can use down with it.
  const stranded = (s: VisibleSection) => s.items.some((i) => i.to in layout.relocate);
  const hidden = layout.hide.filter((code) => {
    const s = byCode.get(code);
    return !s || !stranded(s);
  });

  const rows: NavRow[] = [];
  const spokenFor = new Set<string>(hidden);
  for (const row of layout.rows) {
    if (typeof row === "string") {
      spokenFor.add(row);
      const s = drawable(row);
      if (s) rows.push({ kind: "section", key: row, section: s });
      continue;
    }
    const inner: VisibleSection[] = [];
    for (const code of row.sections) {
      spokenFor.add(code);
      const s = drawable(code);
      if (s) inner.push(s);
    }
    if (inner.length) rows.push({ kind: "group", key: `group:${row.heading}`, group: row, sections: inner });
  }

  // Held, but named nowhere in the layout - an admin can retune access, so this
  // is a real case and not a defect. Appended in the server's order rather than
  // dropped: a sidebar that quietly loses a section somebody was just granted is
  // worse than one whose last row is in an unexpected place.
  for (const s of sections) {
    if (spokenFor.has(s.def.code)) continue;
    const d = drawable(s.def.code);
    if (d) rows.push({ kind: "section", key: s.def.code, section: d });
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

/** Every section drawn in `rows`, group members included. */
export function sectionsIn(rows: NavRow[]): VisibleSection[] {
  return rows.flatMap((r) => (r.kind === "section" ? [r.section] : r.sections));
}

/** The code of the section whose head this person's sidebar draws `pathname`
 *  under - the section that owns the screen, unless their layout relocates that
 *  entry to another heading. What the sidebar has to unfold to show where you
 *  are: a store person standing on Attendance is under Home, not under Staff. */
export function headingOwning(pathname: string, roleCode: string): string | null {
  for (const section of SECTIONS) {
    const entry = section.items.find((i) => isActiveItem(i, pathname));
    if (!entry) continue;
    return PERSONA_LAYOUTS[roleCode]?.relocate[entry.to]?.under ?? section.code;
  }
  return null;
}
