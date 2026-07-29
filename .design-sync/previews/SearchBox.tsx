import { SearchBox, SkuLine } from "kdps-frontend";

// Controlled: `value` is the *committed* term the screen is querying with, not
// the keystrokes. These cells pin it, so each card shows one settled state.
const noop = () => {};

/** Resting state — the placeholder says what this box searches, because the top
 *  bar searches the whole system and this one only narrows the list you are on. */
export const Empty = () => (
  <div className="card" style={{ padding: 18, maxWidth: 480 }}>
    <p className="eyebrow" style={{ marginBottom: 10 }}>Deoghar · stock on hand</p>
    <SearchBox
      value=""
      onChange={noop}
      placeholder="Search style, barcode or brand"
      label="Search stock"
      testId="stock-search"
    />
  </div>
);

/** A typed term. Typing is debounced, so the box only hands a term up once the
 *  person stops; the clear button appears as soon as there is anything to clear. */
export const Typed = () => (
  <div className="card" style={{ padding: 18, maxWidth: 480 }}>
    <p className="eyebrow" style={{ marginBottom: 10 }}>Deoghar · stock on hand</p>
    <SearchBox
      value="MUFTI"
      onChange={noop}
      placeholder="Search style, barcode or brand"
      label="Search stock"
      testId="stock-search"
    />
  </div>
);

/** The wedge scanner: a whole barcode typed at machine speed and an Enter. Enter
 *  commits immediately and drops the pending debounce, so the scan runs once. */
export const Scanned = () => (
  <div className="card" style={{ padding: 18, maxWidth: 480 }}>
    <p className="eyebrow" style={{ marginBottom: 10 }}>Ranchi warehouse · scanned</p>
    <SearchBox
      value="8907468512234"
      onChange={noop}
      placeholder="Scan or type a barcode"
      label="Search stock"
      testId="grn-scan"
    />
  </div>
);

/** Where it actually lives — above the rows it narrows. */
export const OverAList = () => (
  <div className="card" style={{ padding: 18, maxWidth: 520 }}>
    <p className="eyebrow" style={{ marginBottom: 10 }}>Deoghar · stock on hand</p>
    <SearchBox
      value="LEVI'S"
      onChange={noop}
      placeholder="Search style, barcode or brand"
      label="Search stock"
      testId="stock-search"
    />
    <div
      style={{
        display: "grid",
        gap: 10,
        marginTop: 16,
        paddingTop: 14,
        borderTop: "1px solid var(--hairline)",
        fontSize: 13.5,
      }}
    >
      {[
        { style: "511-SLIM", color: "Indigo", size: "32", qty: 7 },
        { style: "511-SLIM", color: "Indigo", size: "34", qty: 4 },
        { style: "65504-TEE", color: "White", size: "M", qty: 12 },
      ].map((r) => (
        <div key={`${r.style}-${r.size}`} style={{ display: "flex", justifyContent: "space-between", gap: 12 }}>
          <SkuLine brand="LEVI'S" style={r.style} color={r.color} size={r.size} />
          <span className="tabular num">{r.qty}</span>
        </div>
      ))}
    </div>
  </div>
);
