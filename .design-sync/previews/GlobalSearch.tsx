import { useEffect, useRef } from "react";
import type { ReactNode } from "react";
import { GlobalSearch } from "kdps-frontend";

/**
 * GlobalSearch is the top bar's type-or-scan box: it asks the server on every
 * keystroke and paints exactly what it is sent. There is no server in a preview,
 * so each card serves the answer from a blob URL instead — the real axios call,
 * the real debounce, the real panel, only the bytes are canned. The empty box in
 * `TopBar` is the untouched component with nothing typed.
 */

type Hit = {
  kind: "item" | "brand" | "document";
  title: string;
  subtitle: string;
  meta: string;
  to: string;
  exact: boolean;
  mrp_paise?: number | null;
};

type Body = {
  query: string;
  groups: { key: string; label: string; results: Hit[]; truncated: boolean }[];
  total: number;
  notes: string[];
};

let served: Body | null = null;
let patched = false;

/** Answer `/api/search?q=…` from memory, leaving every other request alone. */
function serve(body: Body) {
  served = body;
  if (patched) return;
  patched = true;
  const open = XMLHttpRequest.prototype.open;
  XMLHttpRequest.prototype.open = function (
    this: XMLHttpRequest,
    method: string,
    url: string | URL,
    ...rest: unknown[]
  ) {
    if (typeof url === "string" && url.includes("/search?q=")) {
      const blob = new Blob([JSON.stringify(served)], { type: "application/json" });
      return (open as (...a: unknown[]) => void).call(
        this,
        "GET",
        URL.createObjectURL(blob),
        ...rest,
      );
    }
    return (open as (...a: unknown[]) => void).call(this, method, url, ...rest);
  } as typeof XMLHttpRequest.prototype.open;
}

/** Type a query into the live box the way a person (or a wedge scanner) does. */
function useTyped(root: React.RefObject<HTMLDivElement | null>, query: string, body: Body) {
  serve(body);
  useEffect(() => {
    const input = root.current?.querySelector(
      '[data-testid="global-search"]',
    ) as HTMLInputElement | null;
    if (!input) return;
    served = body;
    const setter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value")?.set;
    setter?.call(input, query);
    input.dispatchEvent(new Event("input", { bubbles: true }));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);
}

/** The strip the box actually lives in — unit on the left, person on the right. */
function TopBarStrip({ children }: { children: ReactNode }) {
  return (
    <header
      className="topbar"
      style={{ border: "1px solid var(--hairline)", borderRadius: "var(--radius)" }}
    >
      <div className="switcher-btn locked">
        <span className="switcher-label">Deoghar (DEO)</span>
        <span className="chip chip-navy">BIHAR</span>
      </div>
      {children}
      <div className="topbar-right">
        <span className="avatar">SK</span>
      </div>
    </header>
  );
}

function Card({
  eyebrow,
  reserve,
  children,
}: {
  eyebrow: string;
  reserve: number;
  children: ReactNode;
}) {
  return (
    <div style={{ width: 860 }}>
      <p className="eyebrow" style={{ margin: "0 0 8px" }}>
        {eyebrow}
      </p>
      <TopBarStrip>{children}</TopBarStrip>
      <div style={{ height: reserve }} />
    </div>
  );
}

// ---------------------------------------------------------------------------

const styleSearch: Body = {
  query: "MFK-4471",
  groups: [
    {
      key: "items",
      label: "Items",
      truncated: true,
      results: [
        {
          kind: "item",
          title: "MUFTI · MFK-4471 · Indigo · 40",
          subtitle: "Barcode 8901234512347 · Deoghar",
          meta: "6 in stock",
          to: "/stock-on-hand?barcode=8901234512347",
          exact: false,
          mrp_paise: 299900,
        },
        {
          kind: "item",
          title: "MUFTI · MFK-4471 · Indigo · 42",
          subtitle: "Barcode 8901234512354 · Deoghar",
          meta: "4 in stock",
          to: "/stock-on-hand?barcode=8901234512354",
          exact: false,
          mrp_paise: 299900,
        },
        {
          kind: "item",
          title: "MUFTI · MFK-4471 · Black · 38",
          subtitle: "Barcode 8901234512392 · JSL",
          meta: "nil at Deoghar",
          to: "/stock-on-hand?barcode=8901234512392",
          exact: false,
          mrp_paise: 274900,
        },
      ],
    },
    {
      key: "brands",
      label: "Brands",
      truncated: false,
      results: [
        {
          kind: "brand",
          title: "MUFTI",
          subtitle: "Credo Brands Marketing · SOR, 90-day return",
          meta: "1,284 pieces",
          to: "/brands/mufti",
          exact: false,
        },
      ],
    },
    {
      key: "documents",
      label: "Documents",
      truncated: false,
      results: [
        {
          kind: "document",
          title: "26-27/RAN-WH/TRF/118",
          subtitle: "Transfer · RAN-WH → Deoghar · 18 pieces",
          meta: "In transit",
          to: "/transfers/118",
          exact: false,
        },
        {
          kind: "document",
          title: "26-27/DEO/SAL/74",
          subtitle: "Sale · Deoghar · 3 pieces",
          meta: "Posted 27 Jul",
          to: "/sales/74",
          exact: false,
        },
      ],
    },
  ],
  total: 6,
  notes: ["Deoghar and JSL only — the stores you work in."],
};

const scanned: Body = {
  query: "8902117744319",
  groups: [
    {
      key: "items",
      label: "Scanned barcode",
      truncated: false,
      results: [
        {
          kind: "item",
          title: "Levi's · 511-2847 · Stone Wash · 32",
          subtitle: "Barcode 8902117744319 · Deoghar · outright",
          meta: "7 in stock",
          to: "/stock-on-hand?barcode=8902117744319",
          exact: true,
          mrp_paise: 419900,
        },
      ],
    },
  ],
  total: 1,
  notes: ["One exact match — Enter opens it without touching the mouse."],
};

const nothing: Body = {
  query: "8908844220017",
  groups: [],
  total: 0,
  notes: [
    "Nothing matches 8908844220017 at Deoghar.",
    "Check the tag, or search the style code instead.",
  ],
};

/** The resting state: one pill in the top bar, waiting for a keystroke or a scan. */
export const TopBar = () => (
  <Card eyebrow="Top bar · Deoghar" reserve={24}>
    <GlobalSearch />
  </Card>
);

/** Someone typing a style code — one grouped answer across items, brands and
 *  documents, with MRP on the right where a store person looks for it. */
export const GroupedResults = () => {
  const root = useRef<HTMLDivElement>(null);
  useTyped(root, "MFK-4471", styleSearch);
  return (
    <div ref={root}>
      <Card eyebrow="Typed · style code" reserve={420}>
        <GlobalSearch />
      </Card>
    </div>
  );
};

/** A tag scanned at the counter that this store has never carried — the panel
 *  says so in words instead of showing an empty list. */
export const NothingFound = () => {
  const root = useRef<HTMLDivElement>(null);
  useTyped(root, "8908844220017", nothing);
  return (
    <div ref={root}>
      <Card eyebrow="Scanned · no match" reserve={140}>
        <GlobalSearch />
      </Card>
    </div>
  );
};

/** A scanned barcode that resolves to exactly one piece of stock. */
export const ScannedBarcode = () => {
  const root = useRef<HTMLDivElement>(null);
  useTyped(root, "8902117744319", scanned);
  return (
    <div ref={root}>
      <Card eyebrow="Scanned · one exact match" reserve={200}>
        <GlobalSearch />
      </Card>
    </div>
  );
};
