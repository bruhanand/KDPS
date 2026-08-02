import { describe, expect, it } from "vitest";

import {
  INVENTORY_FOLD,
  NAV_ITEMS,
  PERSONA_LAYOUTS,
  SECTIONS,
  SELL_STRIP,
  activeStripTab,
  applyLayout,
  foldTabs,
  headingOwning,
  isActiveFold,
  isActiveItem,
  isOneLineRow,
  isStripRow,
  itemOwning,
  itemPath,
  resolveFoldTab,
  resolveLegacyPath,
  sectionTabsFor,
  sectionsIn,
  sidebarRows,
  stripLabel,
  stripOwning,
  stripTabs,
  testId,
  visibleSections,
} from "./navConfig";
import type { NavRow } from "./navConfig";

/** Does any screen in the manifest own `path` (itself or as its parent)? */
function claimed(path: string): boolean {
  return itemOwning(path) !== null;
}

/** The authenticated-user payload for a role holding `caps`, in the server's
 *  order (the catalog order). A section at `none` is simply not sent. */
function user(roleCode: string, caps: Record<string, string>) {
  return {
    role: { code: roleCode },
    is_superuser: false,
    sections: SECTIONS.filter((s) => caps[s.code]).map((s) => ({
      code: s.code,
      label: s.label,
      capability: caps[s.code],
    })),
  };
}

/** Each row named as the person reads it: a section by its label, a fold by its
 *  heading, a strip by its row label. All three draw as one row - a fold's tabs
 *  live inside its page, a strip's on the screens it links to. */
function headings(rows: NavRow[]): string[] {
  return rows.map((r) =>
    r.kind === "section" ? r.section.label : r.kind === "fold" ? r.fold.heading : r.label,
  );
}

/** The strip row for `section`, if the layout drew one. */
function stripRow(rows: NavRow[], section: string) {
  return rows.find((r) => r.kind === "strip" && r.strip.section === section);
}

describe("the thirteen sections", () => {
  it("are the operations KDPS named, in order", () => {
    expect(SECTIONS.map((s) => s.code)).toEqual([
      "home",
      "sell",
      "booking",
      "receive_goods",
      "transfer",
      "stock_count",
      "return_to_brand",
      "stock",
      "money",
      "offers_price",
      "hrms",
      "reports",
      "setup",
    ]);
  });

  it("carry none of the old layer vocabulary", () => {
    // The groups the redesign dissolved. They must not survive as a section
    // name, an item label, or a URL segment.
    const dead = /store ops|outbound|documents|master data|ledgers|controls|intelligence|edges/i;
    for (const s of SECTIONS) {
      expect(s.label).not.toMatch(dead);
      for (const i of s.items) {
        expect(i.label).not.toMatch(dead);
        expect(itemPath(i)).not.toMatch(dead);
      }
    }
  });

  it("give every screen exactly one URL", () => {
    const owned = NAV_ITEMS.filter((i) => !i.deepLink).map(itemPath);
    expect(new Set(owned).size).toBe(owned.length);
  });

  it("point every deep link at a screen another section owns", () => {
    for (const i of NAV_ITEMS.filter((d) => d.deepLink)) {
      expect(claimed(itemPath(i))).toBe(true);
    }
  });

  it("name the receive screen plainly, and offer no second door to it", () => {
    // #228. "Receive (GRN)" put the document's name in the menu line; GRN stays
    // where it belongs, on the number and the table column. And "Upload Bill" is
    // gone for every role - the bill goes up inside "New receipt", so a separate
    // entry was a promise the built screen already keeps.
    const receive = NAV_ITEMS.filter((i) => itemPath(i) === "/receive");
    expect(receive.map((i) => i.label)).toEqual(["Receive"]);
    expect(NAV_ITEMS.map((i) => i.label)).not.toContain("Upload Bill");
    expect(NAV_ITEMS.map(itemPath)).not.toContain("/receive/upload-bill");
  });

  it("list the approvals inbox once, inside Home", () => {
    const approvals = NAV_ITEMS.filter((i) => itemPath(i) === "/approvals");
    expect(approvals).toHaveLength(1);
    expect(approvals[0].section).toBe("home");
  });

  it("keep V-flip as an action inside Stock, not a menu item", () => {
    const vflip = NAV_ITEMS.find((i) => itemPath(i) === "/stock/vflips");
    expect(vflip?.section).toBe("stock");
    expect(vflip?.action).toBe(true);
  });

  it("publishes counter settings with the Sell permission its API requires", () => {
    const settings = itemOwning("/setup/settings");
    expect(settings).toMatchObject({ section: "sell", minCapability: "manage" });
  });
});

describe("the highlighted menu line", () => {
  // One screen has one URL (#87), so one URL lights one line. React Router's
  // own NavLink matching is prefix-based and lit every ancestor too: on
  // /receive/pt both "Receive" and "PT Files" were rust, and on
  // /stock/history a *third* line lit in another section — Return to Brand's
  // "Damage / Quarantine", whose /stock?view=quarantine matches on path alone.

  it("is the deepest screen the URL sits under, never its parent as well", () => {
    // Each pair is a child URL and the single item that must own it.
    const cases: [url: string, owner: string][] = [
      ["/receive/pt", "/receive/pt"],
      ["/receive", "/receive"],
      ["/sell/returns", "/sell/returns"],
      ["/booking/new", "/booking/new"],
      ["/transfer/in-transit", "/transfer/in-transit"],
      ["/stock-count/writeoffs", "/stock-count/writeoffs"],
      ["/return-to-brand/new", "/return-to-brand/new"],
      ["/stock/history", "/stock/history"],
      ["/offers/discounts", "/offers/discounts"],
    ];
    for (const [url, owner] of cases) {
      const it = itemOwning(url);
      expect(it && itemPath(it), url).toBe(owner);
    }
  });

  it("stays on the list screen for a document under it", () => {
    // /booking/12 has no menu line of its own, so Bookings keeps the highlight.
    expect(itemOwning("/booking/12") && itemPath(itemOwning("/booking/12")!)).toBe("/booking");
    expect(itemOwning("/receive/pt/review") && itemPath(itemOwning("/receive/pt/review")!)).toBe(
      "/receive/pt",
    );
  });

  it("keeps Stock on Hand lit on V-flip, which has no line of its own", () => {
    // V-flip is an action reached from Stock on Hand, not a menu item — the
    // sidebar must not go dark while you are on it.
    const lit = NAV_ITEMS.filter((i) => isActiveItem(i, "/stock/vflips"));
    expect(lit.map((i) => i.label)).toEqual(["Stock on Hand"]);
    // The guard still resolves that URL to V-flip's own rule, not Stock's.
    expect(itemOwning("/stock/vflips") && itemPath(itemOwning("/stock/vflips")!)).toBe(
      "/stock/vflips",
    );
  });

  it("never lets a deep link claim the URL its host section owns", () => {
    // "Damage / Quarantine" points at /stock?view=quarantine, whose path *is*
    // /stock — so it used to light in Return to Brand on every /stock* URL,
    // alongside Stock's own line in another section.
    for (const url of ["/stock", "/stock/history", "/stock/vflips"]) {
      expect(itemOwning(url)?.section, url).toBe("stock");
      const quarantine = NAV_ITEMS.find((i) => i.deepLink)!;
      expect(isActiveItem(quarantine, url), url).toBe(false);
    }
  });

  it("is exactly one line for every URL in the manifest", () => {
    const menu = NAV_ITEMS.filter((i) => !i.action);
    const urls = [...new Set(menu.map(itemPath))];
    for (const url of urls) {
      const lit = menu.filter((i) => isActiveItem(i, url)).map((i) => `${i.section}:${i.label}`);
      expect(lit.length, `${url} → ${lit.join(" + ")}`).toBe(1);
    }
  });

  it("keeps Home's dashboard off every other screen", () => {
    expect(itemOwning("/") && itemPath(itemOwning("/")!)).toBe("/");
    for (const url of ["/booking", "/stock", "/setup/stores"]) {
      expect(itemOwning(url) && itemPath(itemOwning(url)!), url).not.toBe("/");
    }
  });

  it("lights nothing at an address no screen claims", () => {
    expect(itemOwning("/something-nobody-built")).toBeNull();
  });

  it("answers the same for a mixed-case or trailing-slash URL", () => {
    expect(itemOwning("/Receive/PT") && itemPath(itemOwning("/Receive/PT")!)).toBe("/receive/pt");
    expect(itemOwning("/receive/pt/") && itemPath(itemOwning("/receive/pt/")!)).toBe("/receive/pt");
  });
});

describe("a persona's sidebar shape (#96, folded by #170)", () => {
  // What the server sends today, from `accounts/rbac_matrix.py`: the sheet's
  // "Store Person" row, plus #97's `hrms: manage` for a manager. Written out
  // here rather than imported because the point of these tests is that the
  // *arrangement* obeys whatever the server says - including values an admin
  // retunes later, which is why several tests below change them.
  const STORE_CAPS: Record<string, string> = {
    home: "view",
    sell: "operate",
    booking: "view",
    receive_goods: "operate",
    transfer: "operate",
    stock_count: "operate",
    return_to_brand: "operate",
    stock: "view",
    money: "operate",
    offers_price: "view",
    hrms: "operate",
    reports: "view",
  };
  const MANAGER_CAPS = { ...STORE_CAPS, hrms: "manage" };
  const WAREHOUSE_CAPS: Record<string, string> = {
    home: "view",
    booking: "operate",
    receive_goods: "operate",
    transfer: "operate",
    stock_count: "operate",
    return_to_brand: "operate",
    stock: "manage",
    money: "operate",
    offers_price: "view",
    hrms: "operate",
    reports: "view",
    setup: "operate",
  };

  const rowsFor = (roleCode: string, caps: Record<string, string>) =>
    sidebarRows(user(roleCode, caps));

  // D10's ten, in D10's order (#229: every row but Sell and Inventory becomes a
  // strip; Home and HRMS take the store persona's two renames).
  const TEN = [
    "Dashboard",
    "Sell",
    "Inventory",
    "Receive Goods",
    "Transfer",
    "Booking",
    "Money",
    "Offers & Price",
    "Reports",
    "Attendance",
  ];

  it("gives a store cashier the ten flat sections D10 decided", () => {
    expect(headings(rowsFor("store_staff", STORE_CAPS))).toEqual(TEN);
  });

  it("gives a store manager the same ten", () => {
    // The manager differs from the cashier in one cell (`hrms: manage`), but the
    // hrms strip lists only the Attendance tab (#229) - Member Details, which
    // the extra rung would otherwise add, is not one of them. Manager and
    // cashier sidebars are therefore identical, not merely the same ten labels.
    const managerRows = rowsFor("store_manager", MANAGER_CAPS);
    const staffRows = rowsFor("store_staff", STORE_CAPS);
    expect(headings(managerRows)).toEqual(TEN);
    expect(managerRows).toEqual(staffRows);
    const hrmsStrip = stripRow(managerRows, "hrms");
    expect(hrmsStrip?.kind === "strip" && hrmsStrip.tabs.map((t) => t.label)).toEqual(["Attendance"]);
  });

  it("nests no section under another - no subsections in the sidebar, ever", () => {
    // D10 §1's standing rule: anything that needs dividing divides inside the
    // page, as tabs. A row is a section, a fold or a strip; the last two draw
    // one link each.
    for (const rows of [rowsFor("store_staff", STORE_CAPS), rowsFor("warehouse", WAREHOUSE_CAPS)]) {
      for (const row of rows) expect(["section", "fold", "strip"]).toContain(row.kind);
    }
    // Every store row is a fold or a strip since #229 - a bare section head
    // would be exactly the subsection D10 forbids.
    expect(rowsFor("store_staff", STORE_CAPS).some((r) => r.kind === "section")).toBe(false);
  });

  it("folds Stock, Stock Count and Return to Brand into Inventory's four tabs", () => {
    const rows = rowsFor("store_staff", STORE_CAPS);
    // The three heads are gone from the sidebar...
    for (const gone of ["Stock", "Stock Count", "Return to Brand"]) {
      expect(headings(rows)).not.toContain(gone);
    }
    // ...and their screens are the tabs of one page instead.
    const fold = rows.find((r) => r.kind === "fold");
    expect(fold?.kind === "fold" && fold.fold.to).toBe("/inventory");
    expect(fold?.kind === "fold" && fold.tabs.map((t) => t.label)).toEqual([
      "Stock on Hand",
      // Cross-store availability (#175) is Stock's tab, and the fold is a store
      // person's whole Stock section - leaving it off would put the screen out
      // of reach of the very people it was built for.
      "Search Across Stores",
      "Damage & Quarantine",
      "Count & Adjust",
      "Return to Brand",
    ]);
  });

  it("shows a store no tab it does not hold the section for", () => {
    // The acceptance criterion of #170: tabs stay gated by their original
    // codes, so revoking one takes its tab and nothing else.
    const { stock_count: _noCount, ...withoutCount } = STORE_CAPS;
    expect(foldTabs(INVENTORY_FOLD, visibleSections(user("store_staff", withoutCount)))
      .map((t) => t.label)).toEqual([
        "Stock on Hand",
        "Search Across Stores",
        "Damage & Quarantine",
        "Return to Brand",
      ]);

    const { return_to_brand: _noRtv, ...withoutRtv } = STORE_CAPS;
    expect(foldTabs(INVENTORY_FOLD, visibleSections(user("store_staff", withoutRtv)))
      .map((t) => t.label)).toEqual(["Stock on Hand", "Search Across Stores", "Count & Adjust"]);

    // Damage & Quarantine is Return to Brand's line onto Stock's screen, so it
    // needs both - the same pair clicking the line and landing on the URL needs.
    // Holding one half must not open by a tab what the URL bar refuses.
    const { stock: _noStock, ...withoutStock } = STORE_CAPS;
    expect(foldTabs(INVENTORY_FOLD, visibleSections(user("store_staff", withoutStock)))
      .map((t) => t.label)).toEqual(["Count & Adjust", "Return to Brand"]);

    // No folded section at all ⇒ no Inventory row: an empty page is not a page.
    const rows = sidebarRows(user("store_staff", { home: "view", sell: "operate" }));
    expect(headings(rows)).toEqual(["Dashboard", "Sell"]);
  });

  it("falls back to the first tab this person can see", () => {
    // A slug that is unknown, or one whose tab they are not shown, must not
    // leave them on a page with nothing on it.
    const tabs = foldTabs(INVENTORY_FOLD, visibleSections(user("store_staff", STORE_CAPS)));
    expect(resolveFoldTab(tabs, "count")?.slug).toBe("count");
    expect(resolveFoldTab(tabs, "nonsense")?.slug).toBe("stock");
    expect(resolveFoldTab(tabs, null)?.slug).toBe("stock");
    expect(resolveFoldTab([], "stock")).toBeNull();
  });

  it("folds without renaming, except the two amendments Anand made", () => {
    // Folding may move a section onto a page; it may not give this persona a
    // private word for one - except Home and HRMS, consciously renamed for the
    // store persona alone (#229, #84 as amended). Every other section still
    // standing keeps the word the warehouse and HO use for it.
    const rows = rowsFor("store_staff", STORE_CAPS);
    const byCode = new Map(SECTIONS.map((s) => [s.code, s.label]));
    for (const row of rows) {
      if (row.kind === "section") {
        expect(row.section.label, row.key).toBe(byCode.get(row.key));
      } else if (row.kind === "strip" && row.strip.section !== "home" && row.strip.section !== "hrms") {
        expect(row.label, row.strip.section).toBe(byCode.get(row.strip.section));
      }
    }
    expect(headings(rows)).toContain("Transfer");
    // The mirror: a persona with no layout - the warehouse, the owner - still
    // reads the two words the store amends.
    for (const role of ["warehouse", "owner"]) {
      const flatHeadings = headings(rowsFor(role, WAREHOUSE_CAPS));
      expect(flatHeadings, role).toContain("Home");
      expect(flatHeadings, role).toContain("HRMS");
    }
  });

  it("keeps the fold out of the section catalog, and its tabs inside it", () => {
    // A fold owns a URL but no section code and no server counterpart; every
    // section it stands for, and every entry it draws, is a real one.
    const codes = new Set(SECTIONS.map((s) => s.code));
    const entries = new Set(NAV_ITEMS.map((i) => i.to));
    for (const layout of Object.values(PERSONA_LAYOUTS)) {
      for (const row of layout) {
        if (typeof row === "string") continue;
        if (isStripRow(row)) {
          // A strip names its own section's entries by their `to`, and the two
          // can drift apart in silence: rename an entry and its tab quietly
          // disappears, rename them all and the row vanishes from the sidebar
          // with the whole suite still green. A strip may list *fewer* entries
          // than its section holds (an action-shaped screen reached from inside
          // another one is nobody's tab), never one that does not exist.
          expect(codes.has(row.section), row.section).toBe(true);
          const own = new Set(
            NAV_ITEMS.filter((i) => i.section === row.section && !i.action).map((i) => i.to),
          );
          for (const to of row.tabs) expect(own.has(to), `${row.section}: ${to}`).toBe(true);
          expect(new Set(row.tabs).size).toBe(row.tabs.length);
          continue;
        }
        expect(codes.has(row.heading.toLowerCase())).toBe(false);
        expect(claimed(row.to), row.to).toBe(false);
        for (const code of row.sections) expect(codes.has(code), code).toBe(true);
        for (const tab of row.tabs) expect(entries.has(tab.entry), tab.entry).toBe(true);
      }
    }
  });

  it("says which row a screen is drawn under, folded or not", () => {
    // The sidebar must be able to show where you are - including when the
    // screen has been folded onto a page under a different name.
    expect(headingOwning("/inventory", "store_staff")).toBe("fold:/inventory");
    expect(headingOwning("/stock", "store_staff")).toBe("fold:/inventory");
    expect(headingOwning("/stock-count/adjustments", "store_staff")).toBe("fold:/inventory");
    expect(headingOwning("/stock", "warehouse")).toBe("stock");
    // PT Files is not one of the Receive Goods strip's tabs, but its own
    // section still lights the row (#229 dropped stripOwning's tabs.includes
    // clause) - the strip just draws no tab row there.
    expect(headingOwning("/receive/pt", "store_staff")).toBe("strip:receive_goods");
    expect(headingOwning("/staff/attendance", "store_staff")).toBe("strip:hrms");
    expect(headingOwning("/nobody-built-this", "store_staff")).toBeNull();
  });

  it("lights the Inventory row on the screens it folded", () => {
    // A store person who lands on /stock from the global search still sees
    // which row they are on, even though no line points there any more.
    for (const url of ["/inventory", "/stock", "/stock/history", "/return-to-brand/3"]) {
      expect(isActiveFold(INVENTORY_FOLD, url), url).toBe(true);
    }
    for (const url of ["/receive", "/transfer", "/"]) {
      expect(isActiveFold(INVENTORY_FOLD, url), url).toBe(false);
    }
  });

  it("gives every line on a store person's sidebar its own test handle", () => {
    const handles = sectionsIn(rowsFor("store_manager", MANAGER_CAPS)).flatMap((s) =>
      s.items.map((i) => testId(s.def.code, i)),
    );
    expect(new Set(handles).size).toBe(handles.length);
  });

  // #267 leaves Sell with its two published destinations. Return and customer
  // lookup keep guarded routes while the counter absorbs their UI.
  describe("Sell, as a strip", () => {
    const sellTabs = (caps: Record<string, string>) =>
      stripTabs(SELL_STRIP, visibleSections(user("store_staff", caps))).map((i) => i.label);

    it("draws one row landing on Billing, with the published pair as its tabs", () => {
      const rows = rowsFor("store_staff", STORE_CAPS);
      // Scoped to Sell: #229 gives the store persona nine other strips, so
      // "the first strip row" is no longer a safe way to find this one.
      const sell = stripRow(rows, "sell");
      expect(sell?.kind === "strip" && sell.strip.section).toBe("sell");
      expect(sell?.kind === "strip" && sell.label).toBe("Sell");
      expect(sell?.kind === "strip" && sell.tabs.map((i) => i.to)).toEqual([
        "/sell",
        "/sell/till",
      ]);
      expect(sell?.kind === "strip" && sell.tabs.map((i) => i.label)).toEqual([
        "Billing",
        "Till & Sync",
      ]);
      // The row goes nowhere new: its link is the first tab's own canonical URL.
      expect(sell?.kind === "strip" && sell.tabs[0].to).toBe("/sell");
    });

    it("shows no published Sell tab to a view-only person", () => {
      // The find-bill route remains protected at `sell: view`, but it is a door
      // inside the counter rather than a second public section destination.
      expect(sellTabs({ ...STORE_CAPS, sell: "view" })).toEqual([]);
      // And with no Sell section at all there is no row to draw.
      const { sell: _noSell, ...withoutSell } = STORE_CAPS;
      expect(sellTabs(withoutSell)).toEqual([]);
      expect(headings(rowsFor("store_staff", withoutSell))).not.toContain("Sell");
    });

    it("does not draw a Sell row with no published destination", () => {
      const rows = rowsFor("store_staff", { ...STORE_CAPS, sell: "view" });
      const sell = stripRow(rows, "sell");
      expect(sell).toBeUndefined();
      expect(headings(rows)).not.toContain("Sell");
    });

    it("belongs to the store persona alone - nobody else gets a second menu", () => {
      // An owner's sidebar still expands Sell, so a tab row there would be a
      // redundant copy of what they are already looking at.
      for (const role of ["owner", "warehouse", "accounts", "it_admin", ""]) {
        expect(stripOwning("/sell", role), role).toBeNull();
      }
      expect(stripOwning("/sell", "store_staff")).toBe(SELL_STRIP);
      expect(stripOwning("/sell", "store_manager")).toBe(SELL_STRIP);
    });

    it("claims the URLs its section owns, and nothing else", () => {
      // Including a bill under Billing: the row stays lit on a document, the
      // same way the sidebar's own highlight does.
      for (const url of ["/sell", "/sell/returns", "/sell/customers", "/sell/till", "/sell/9"]) {
        expect(stripOwning(url, "store_staff"), url).toBe(SELL_STRIP);
      }
      // "/" and "/receive" now belong to strips of their own (#229's Dashboard
      // and Receive Goods rows) - Sell must not answer for them either.
      expect(stripOwning("/", "store_staff")?.section).toBe("home");
      expect(stripOwning("/receive", "store_staff")?.section).toBe("receive_goods");
      for (const url of ["/inventory", "/stock", "/selling-elsewhere"]) {
        expect(stripOwning(url, "store_staff"), url).toBeNull();
      }
    });

    it("takes this persona's name for the row when the layout gives it one", () => {
      // #229 renames two rows for the store persona alone (Home ⇒ "Dashboard",
      // HRMS ⇒ "Attendance"); the override lives on the layout row, never in
      // SECTIONS, so no other persona's sidebar can change word.
      const sections = visibleSections(user("store_staff", STORE_CAPS));
      expect(stripLabel(SELL_STRIP, sections)).toBe("Sell");
      expect(stripLabel({ ...SELL_STRIP, label: "Counter" }, sections)).toBe("Counter");
      // A section the server did not send falls back to the manifest's label.
      expect(stripLabel(SELL_STRIP, [])).toBe("Sell");
    });

    it("lights the tab the URL is under, child URLs included", () => {
      const tabs = stripTabs(SELL_STRIP, visibleSections(user("store_staff", STORE_CAPS)));
      const lit = (url: string) => activeStripTab(tabs, url)?.to;
      expect(lit("/sell")).toBe("/sell");
      // The transitional routes are not tabs, so the visible Billing door stays
      // lit if a bookmark or the counter's lookup opens one.
      expect(lit("/sell/returns")).toBe("/sell");
      expect(lit("/sell/returns/12")).toBe("/sell");
      expect(lit("/sell/customers/4")).toBe("/sell");
      // A bill under Billing itself, and a mixed-case bookmark.
      expect(lit("/sell/9")).toBe("/sell");
      expect(lit("/Sell/Till/")).toBe("/sell/till");
      expect(lit("/receive")).toBeUndefined();
    });

    it("hands the screens a row only where one is worth drawing", () => {
      // What the shell renders, decided here so the shell only draws it.
      const row = (url: string, caps: Record<string, string>, role = "store_staff") =>
        sectionTabsFor(url, user(role, caps));

      const billing = row("/sell", STORE_CAPS)!;
      expect(billing.crumb).toBe("Sell");
      expect(billing.title).toBe("Billing");
      expect(billing.active.to).toBe("/sell");
      expect(billing.tabs.map((t) => t.label)).toEqual([
        "Billing",
        "Till & Sync",
      ]);
      expect(row("/sell/till", STORE_CAPS)!.title).toBe("Till & Sync");

      // No row: a persona whose sidebar still expands Sell...
      expect(row("/sell", WAREHOUSE_CAPS, "owner")).toBeNull();
      // ...a single-tab strip, whose row lights but draws no tabs (#229)...
      expect(row("/receive", STORE_CAPS)).toBeNull();
      // ...a screen outside every strip (a fold's own URL)...
      expect(row("/inventory", STORE_CAPS)).toBeNull();
      // ...a strip access has cut to one tab...
      expect(row("/sell/customers", { ...STORE_CAPS, sell: "view" })).toBeNull();
      // ...and nobody signed in.
      expect(sectionTabsFor("/sell", null)).toBeNull();
    });

    it("says a store person on a Sell screen is standing under the Sell row", () => {
      expect(headingOwning("/sell", "store_staff")).toBe("strip:sell");
      expect(headingOwning("/sell/till", "store_staff")).toBe("strip:sell");
      // Every other persona still reads it as the plain section it always was.
      expect(headingOwning("/sell", "owner")).toBe("sell");
    });
  });

  // #229 - the store persona's remaining eight rows become strips too, so the
  // sidebar is exactly ten one-line links and nothing expands.
  describe("the store's other rows, as strips", () => {
    const rowsForStaff = (caps: Record<string, string> = STORE_CAPS) => rowsFor("store_staff", caps);

    it("draws the four single-tab rows with a link and no tab row", () => {
      // Dashboard, Receive Goods, Booking and Attendance each list exactly one
      // tab - a strip of one is not a choice, so the row is a bare link.
      const rows = rowsForStaff();
      for (const [section, tab] of [
        ["home", "/"],
        ["receive_goods", "/receive"],
        ["booking", "/booking"],
        ["hrms", "/staff/attendance"],
      ] as const) {
        const row = stripRow(rows, section);
        expect(row?.kind === "strip" && row.tabs.map((t) => t.to), section).toEqual([tab]);
        expect(sectionTabsFor(tab, user("store_staff", STORE_CAPS)), tab).toBeNull();
      }
    });

    it("links every row to its first visible tab", () => {
      const rows = rowsForStaff();
      const firstTab: [string, string][] = [
        ["home", "/"],
        ["receive_goods", "/receive"],
        ["transfer", "/transfer"],
        ["booking", "/booking"],
        ["money", "/money/day-summary"],
        ["offers_price", "/offers/price-list"],
        ["reports", "/reports/sales"],
        ["hrms", "/staff/attendance"],
      ];
      for (const [section, to] of firstTab) {
        const row = stripRow(rows, section);
        expect(row?.kind === "strip" && row.tabs[0].to, section).toBe(to);
      }
    });

    it("gives Transfer, Money, Offers & Price and Reports the tab sets #229 names", () => {
      const rows = rowsForStaff();
      const tabLabels = (section: string) => {
        const row = stripRow(rows, section);
        return row?.kind === "strip" ? row.tabs.map((t) => t.label) : null;
      };
      expect(tabLabels("transfer")).toEqual(["Transfers", "Stock Request", "In-Transit"]);
      expect(tabLabels("money")).toEqual(["Day Summary", "Store Targets", "Expenses"]);
      expect(tabLabels("offers_price")).toEqual(["Price List", "Offers", "Discounts", "EOSS Planning"]);
      expect(tabLabels("reports")).toEqual([
        "Sales Reports",
        "Stock Reports",
        "Profit",
        "Daily Summary",
        "Report Maker",
      ]);
    });

    it("draws no row at all where the section is not held - subtract only", () => {
      const { transfer: _noTransfer, ...withoutTransfer } = STORE_CAPS;
      expect(stripRow(rowsForStaff(withoutTransfer), "transfer")).toBeUndefined();
      const { money: _noMoney, ...withoutMoney } = STORE_CAPS;
      expect(stripRow(rowsForStaff(withoutMoney), "money")).toBeUndefined();
    });

    it("lights the Transfer row and the Transfer tab on Send Stock, a screen the strip lists no tab for", () => {
      // /transfer/new is Send Stock, deliberately left off the strip's tabs (it
      // stays the CTA inside the Transfers screen) - but it is still a URL of
      // the transfer section, so the row lights and the deepest-prefix tab
      // (Transfers) is what lights with it.
      expect(stripOwning("/transfer/new", "store_staff")?.section).toBe("transfer");
      const tabs = sectionTabsFor("/transfer/new", user("store_staff", STORE_CAPS));
      expect(tabs?.active.to).toBe("/transfer");
      expect(tabs?.title).toBe("Transfers");
      expect(headingOwning("/transfer/new", "store_staff")).toBe("strip:transfer");
    });

    it("relabels Dashboard and Attendance for the store persona only", () => {
      const staffHeadings = headings(rowsForStaff());
      expect(staffHeadings).toContain("Dashboard");
      expect(staffHeadings).toContain("Attendance");
      expect(staffHeadings).not.toContain("Home");
      expect(staffHeadings).not.toContain("HRMS");
      // Approvals and Alerts are Home's items, not one of Dashboard's tabs, so
      // they stay off this row and reachable only by URL or the bell.
      const dashboard = stripRow(rowsForStaff(), "home");
      expect(dashboard?.kind === "strip" && dashboard.tabs.map((t) => t.to)).toEqual(["/"]);
    });
  });

  it("leaves every other persona's sidebar flat and untouched", () => {
    for (const role of ["owner", "warehouse", "accounts", "it_admin", "brand_manager", "ho_ops"]) {
      const sections = visibleSections(user(role, WAREHOUSE_CAPS));
      expect(applyLayout(sections, role), role).toEqual(
        sections.map((s) => ({ kind: "section", key: s.def.code, section: s })),
      );
    }
  });
});

describe("isOneLineRow - does a row navigate, or open a flyout? (#230)", () => {
  // The store persona's ten rows are all folds or strips (#229). The icon
  // rail's own trap: drawing a flyout for any one of them is D10 §1's "no
  // subsections in the sidebar, ever" breaking, on the rail rather than the
  // expanded sidebar.
  const STORE_CAPS: Record<string, string> = {
    home: "view",
    sell: "operate",
    booking: "view",
    receive_goods: "operate",
    transfer: "operate",
    stock_count: "operate",
    return_to_brand: "operate",
    stock: "view",
    money: "operate",
    offers_price: "view",
    hrms: "operate",
    reports: "view",
  };

  it("is true for a strip row and for the Inventory fold", () => {
    const rows = sidebarRows(user("store_staff", STORE_CAPS));
    const sell = stripRow(rows, "sell");
    expect(sell).toBeDefined();
    expect(isOneLineRow(sell!)).toBe(true);
    const inventory = rows.find((r) => r.kind === "fold");
    expect(inventory).toBeDefined();
    expect(isOneLineRow(inventory!)).toBe(true);
  });

  it("is true for a section access has cut to exactly one visible item", () => {
    // No persona layout for this role code, so Booking draws as a bare
    // section - and at `view` only "Bookings" survives; "New Booking" needs
    // `operate` (#130).
    const rows = sidebarRows(user("area_manager", { booking: "view" }));
    const booking = rows.find((r) => r.kind === "section" && r.section.def.code === "booking");
    expect(booking).toBeDefined();
    expect(booking?.kind === "section" && booking.section.items).toHaveLength(1);
    expect(isOneLineRow(booking!)).toBe(true);
  });

  it("is false for a section with two or more visible items", () => {
    const rows = sidebarRows(user("area_manager", { setup: "operate" }));
    const setup = rows.find((r) => r.kind === "section" && r.section.def.code === "setup");
    expect(setup).toBeDefined();
    expect(setup?.kind === "section" && setup.section.items.length).toBeGreaterThan(1);
    expect(isOneLineRow(setup!)).toBe(false);
  });

  it("is true for every one of the store persona's ten rows", () => {
    // So the rail never draws a flyout for a store login - see the trap noted
    // above.
    const rows = sidebarRows(user("store_staff", STORE_CAPS));
    expect(rows).toHaveLength(10);
    for (const row of rows) expect(isOneLineRow(row), row.key).toBe(true);
  });
});

describe("arranging a sidebar can never widen it", () => {
  // The invariant the whole of #96 rests on, and #170 inherits: arranging
  // consumes the output of the access filter, so it can reorder, fold or drop -
  // never add.
  const ROLES = ["store_staff", "store_manager", "warehouse", "owner"];

  function shuffleCaps(seed: number): Record<string, string> {
    const rungs = ["view", "operate", "manage"];
    return Object.fromEntries(
      SECTIONS.map((s, i) => [s.code, rungs[(i + seed) % rungs.length]]).filter(
        (_, i) => (i + seed) % 4 !== 0, // a different section revoked each pass
      ),
    );
  }

  it("draws no section the server did not send, and no item access hid", () => {
    for (const role of ROLES) {
      for (let seed = 0; seed < 8; seed++) {
        const caps = shuffleCaps(seed);
        const granted = visibleSections(user(role, caps));
        const allowed = new Map(granted.map((s) => [s.def.code, new Set(s.items.map((i) => i.to))]));
        const rows = applyLayout(granted, role);
        const drawn = sectionsIn(rows);

        expect(new Set(drawn.map((s) => s.def.code)).size, `${role}/${seed}`).toBe(drawn.length);
        for (const s of drawn) {
          expect(allowed.has(s.def.code), `${role}/${seed}: ${s.def.code}`).toBe(true);
          for (const item of s.items) {
            expect(allowed.get(s.def.code)!.has(item.to), `${role}/${seed}: ${item.to}`).toBe(true);
          }
        }
        // A tab is a menu entry drawn somewhere else, so it answers to the same
        // filter: no tab may show a screen the sidebar would have hidden.
        for (const row of rows) {
          if (row.kind === "fold") {
            for (const tab of row.tabs) {
              const passed = [...allowed.values()].some((set) => set.has(tab.entry));
              expect(passed, `${role}/${seed}: ${tab.entry}`).toBe(true);
            }
          }
          if (row.kind === "strip") {
            for (const tab of row.tabs) {
              expect(allowed.get(row.strip.section)?.has(tab.to), `${role}/${seed}: ${tab.to}`).toBe(
                true,
              );
            }
          }
        }
      }
    }
  });

  it("draws no Inventory row for somebody holding none of its sections", () => {
    const rows = sidebarRows(user("store_staff", { home: "view", sell: "operate" }));
    expect(rows.some((r) => r.kind === "fold")).toBe(false);
  });

  it("survives a retune in either direction", () => {
    const base: Record<string, string> = {
      home: "view",
      sell: "operate",
      receive_goods: "operate",
      transfer: "operate",
      stock: "view",
      reports: "view",
    };
    const shape = (caps: Record<string, string>) => headings(sidebarRows(user("store_staff", caps)));
    expect(shape(base)).toEqual([
      "Dashboard",
      "Sell",
      "Inventory",
      "Receive Goods",
      "Transfer",
      "Reports",
    ]);
    // Revoked: Transfer goes, Inventory stays on the one section it still holds.
    const { transfer: _dropped, ...withoutTransfer } = base;
    expect(shape(withoutTransfer)).toEqual([
      "Dashboard",
      "Sell",
      "Inventory",
      "Receive Goods",
      "Reports",
    ]);
    // Revoked to nothing behind the fold: the fold goes with them.
    const { stock: _noStock, ...withoutStock } = base;
    expect(shape(withoutStock)).toEqual(["Dashboard", "Sell", "Receive Goods", "Transfer", "Reports"]);
    // Newly granted and named nowhere in the layout: appended, not dropped.
    expect(shape({ ...base, setup: "operate" })).toEqual([
      "Dashboard",
      "Sell",
      "Inventory",
      "Receive Goods",
      "Transfer",
      "Reports",
      "Setup",
    ]);
  });
});

describe("legacy URLs", () => {
  // Every route that existed before the redesign, with the screen it opened.
  const OLD_PATHS = [
    "/documents/bookings",
    "/documents/bookings/new",
    "/documents/bookings/12",
    "/documents/inbound",
    "/documents/inbound/new",
    "/documents/inbound/12",
    "/documents/pt-mapper",
    "/documents/pt-mapper/review",
    "/documents/pt-mapper/proposals",
    "/documents/pt-mapper/12",
    "/documents/sales",
    "/documents/transfers",
    "/documents/returns",
    "/documents/payments",
    "/inbound",
    "/inbound/new",
    "/inbound/12",
    "/outbound/transfers",
    "/outbound/transfers/new",
    "/outbound/transfers/12",
    "/outbound/rtvs",
    "/outbound/rtvs/new",
    "/outbound/rtvs/12",
    "/outbound/adjustments",
    "/outbound/adjustments/new",
    "/outbound/adjustments/12",
    "/outbound/writeoffs",
    "/outbound/writeoffs/new",
    "/outbound/writeoffs/12",
    "/outbound/vflips",
    "/outbound/vflips/new",
    "/outbound/vflips/12",
    // Not a pre-#87 address but a deleted one: the Distribution stub (#229).
    "/transfer/distribution",
    "/ledgers/stock",
    "/ledgers/stock-on-hand",
    "/ledgers/vendor",
    "/ledgers/cash",
    "/masters/stores",
    "/masters/brands",
    "/masters/seasons",
    "/masters/gstins",
    "/masters/users",
    // Not a pre-#87 address but a deleted one: the Upload Bill stub (#228).
    "/receive/upload-bill",
    "/store/sell",
    "/store/receive",
    "/store/count",
    "/store/transfer",
    "/controls/exceptions",
    "/controls/recon",
    "/controls/approvals",
    "/controls/audit",
    "/intel/dashboards",
    "/intel/profitability",
    "/intel/dead-stock",
    "/intel/forecast",
    "/intel/reports",
    "/edges/integrations",
    "/edges/rbac",
    "/edges/tally",
    "/edges/pos",
    "/edges/config",
  ];

  it("all redirect to a screen that exists", () => {
    for (const old of OLD_PATHS) {
      const target = resolveLegacyPath(old);
      expect(target, old).not.toBeNull();
      expect(claimed(target!), `${old} → ${target}`).toBe(true);
    }
  });

  it("never redirect twice — a target is always a new URL", () => {
    for (const old of OLD_PATHS) {
      expect(resolveLegacyPath(resolveLegacyPath(old)!), old).toBeNull();
    }
  });

  it("keep the tail, so a bookmarked document still opens", () => {
    expect(resolveLegacyPath("/documents/bookings/12")).toBe("/booking/12");
    expect(resolveLegacyPath("/outbound/writeoffs/9")).toBe("/stock-count/writeoffs/9");
    expect(resolveLegacyPath("/documents/pt-mapper/review")).toBe("/receive/pt/review");
  });

  it("catch mixed case and trailing slashes", () => {
    expect(resolveLegacyPath("/Ledgers/Vendor")).toBe("/money/vendor");
    expect(resolveLegacyPath("/inbound/")).toBe("/receive");
  });

  it("leave new URLs alone", () => {
    for (const i of NAV_ITEMS) expect(resolveLegacyPath(itemPath(i)), i.to).toBeNull();
    expect(resolveLegacyPath("/something-nobody-built")).toBeNull();
  });
});
