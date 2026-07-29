import { AccessDenied } from "kdps-frontend";

/** What a signed-in user sees when their role cannot open the route they
 *  landed on - a cashier at Deoghar following a link to the vendor ledger, say.
 *  The URL is deliberately left standing so a support screenshot still shows
 *  which page was asked for; nothing is silently redirected. */
export const InsideTheShell = () => (
  <div style={{ maxWidth: 720 }}>
    <AccessDenied />
  </div>
);

/** The same screen on a store tablet, where the content column is narrow. The
 *  copy wraps, the shield keeps its size, and the way back home stays visible. */
export const OnAStoreTablet = () => (
  <div style={{ maxWidth: 380, border: "1px solid var(--hairline)", borderRadius: 12 }}>
    <AccessDenied />
  </div>
);

/** How it reads in place: the sidebar section the store user was aiming at,
 *  with the refusal beside it. Access is a control-layer answer, not an error. */
export const WhereItLands = () => (
  <div
    style={{
      display: "grid",
      gridTemplateColumns: "190px 1fr",
      gap: 0,
      maxWidth: 760,
      border: "1px solid var(--hairline)",
      borderRadius: 14,
      overflow: "hidden",
      background: "var(--surface)",
    }}
  >
    <div style={{ background: "var(--inner)", padding: "18px 14px", borderRight: "1px solid var(--hairline)" }}>
      <p className="eyebrow">Money</p>
      <p className="lead" style={{ fontSize: 13.5, margin: "8px 0" }}>Vendor ledger</p>
      <p className="lead" style={{ fontSize: 13.5, margin: "8px 0", color: "var(--muted)" }}>Cash ledger</p>
      <p className="lead" style={{ fontSize: 13.5, margin: "8px 0", color: "var(--muted)" }}>Books health</p>
      <p className="eyebrow" style={{ marginTop: 16 }}>Signed in</p>
      <p className="lead" style={{ fontSize: 13, color: "var(--muted)", margin: "6px 0" }}>
        Manoj Verma
        <br />
        Store Manager, JSL
      </p>
    </div>
    <AccessDenied />
  </div>
);
