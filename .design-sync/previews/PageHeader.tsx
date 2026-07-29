import { Money, PageHeader, Stat, StatusChip } from "kdps-frontend";

// PageHeader reads the router. The preview provider mounts every cell at "/",
// so the crumb the header derives is Home's — the screen-level crumb link only
// appears when a document sits *under* its list screen, which no preview can
// stage without a second router. These cells therefore stay honest Home screens.

/** The default: no `title` at all. The heading and the crumb both come from the
 *  navigation manifest, so the page is captioned the way the sidebar addresses
 *  it and the two cannot tell different stories. */
export const FromTheManifest = () => (
  <div className="card" style={{ padding: 18, maxWidth: 640 }}>
    <PageHeader />
    <div style={{ display: "flex", gap: 36, borderTop: "1px solid var(--hairline)", paddingTop: 14 }}>
      <Stat label="Stores reporting" value="6 of 6" />
      <Stat label="Net sales today" value={<Money paise={4182650000} short />} />
      <Stat label="Bills" value="311" />
    </div>
  </div>
);

/** A title of its own, plus the `lead` line — one sentence saying what the
 *  screen is for, in the words a store person would use. */
export const WithLead = () => (
  <div className="card" style={{ padding: 18, maxWidth: 640 }}>
    <PageHeader
      title="Approvals"
      lead="Everything waiting on you — transfers out of Ranchi warehouse, stock adjustments and returns to brand."
    />
    <div style={{ display: "flex", gap: 36, borderTop: "1px solid var(--hairline)", paddingTop: 14 }}>
      <Stat label="Waiting" value="9" />
      <Stat label="Oldest" value="4 days" />
      <Stat label="Value held" value={<Money paise={68420000} short />} />
    </div>
  </div>
);

/** `actions` are pushed to the right of the header row by the toolbar's spacer,
 *  so the buttons sit level with the heading however long the title runs. */
export const WithActions = () => (
  <div className="card" style={{ padding: 18, maxWidth: 640 }}>
    <PageHeader
      title="Approvals"
      lead="Deoghar · Jamshedpur · Ranchi warehouse"
      actions={
        <>
          <button className="btn">Export</button>
          <button className="btn btn-primary">Approve all</button>
        </>
      }
    />
    <div style={{ display: "flex", gap: 36, borderTop: "1px solid var(--hairline)", paddingTop: 14 }}>
      <Stat label="Transfers" value="5" />
      <Stat label="Adjustments" value="3" />
      <Stat label="Returns to brand" value="1" />
    </div>
  </div>
);

/** `lead` is a ReactNode, not a string — a document screen puts its number,
 *  state and value on that line instead of a sentence. */
export const RichLead = () => (
  <div className="card" style={{ padding: 18, maxWidth: 640 }}>
    <PageHeader
      title="Alerts"
      lead={
        <span style={{ display: "inline-flex", alignItems: "center", gap: 9, flexWrap: "wrap" }}>
          <span className="mono">26-27/RAN-WH/GRN/311</span>
          <StatusChip status="Overdue" />
          <span>MUFTI · 14 pieces short</span>
          <Money paise={1284500} />
        </span>
      }
    />
    <p className="lead" style={{ borderTop: "1px solid var(--hairline)", paddingTop: 14, margin: 0 }}>
      Three brands are past their return window at Deoghar. Levi's closes in 6 days.
    </p>
  </div>
);
