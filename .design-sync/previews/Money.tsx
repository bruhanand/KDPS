import { Money } from "kdps-frontend";

/** Money is display-only: it takes integer paise and renders INR with Indian
 *  Lakh/Crore grouping. Never hand a float to a write path. */
export const BillAmounts = () => (
  <div className="card" style={{ padding: 16, maxWidth: 360 }}>
    <p className="eyebrow">Bill 26-27/DEO/SAL/74</p>
    <table className="tabular" style={{ width: "100%", fontSize: 14, borderSpacing: "0 6px" }}>
      <tbody>
        <tr>
          <td style={{ color: "var(--muted)" }}>MUFTI shirt</td>
          <td align="right"><Money paise={249900} /></td>
        </tr>
        <tr>
          <td style={{ color: "var(--muted)" }}>Levi's 511 </td>
          <td align="right"><Money paise={379950} /></td>
        </tr>
        <tr>
          <td style={{ color: "var(--muted)" }}>Discount</td>
          <td align="right"><Money paise={-94985} /></td>
        </tr>
        <tr>
          <td style={{ fontWeight: 700 }}>Net payable</td>
          <td align="right" style={{ fontWeight: 700, fontSize: 17 }}><Money paise={534865} /></td>
        </tr>
      </tbody>
    </table>
  </div>
);

/** `short` folds big numbers into Lakh/Crore — the form owners read in reports. */
export const ShortForm = () => (
  <div className="card" style={{ padding: 16, maxWidth: 360, display: "grid", gap: 10 }}>
    <p className="eyebrow">Month to date · all stores</p>
    <div style={{ display: "flex", justifyContent: "space-between", fontSize: 14 }}>
      <span className="muted-cell" style={{ color: "var(--muted)" }}>Sales</span>
      <b style={{ fontSize: 18 }}><Money paise={285000000} short /></b>
    </div>
    <div style={{ display: "flex", justifyContent: "space-between", fontSize: 14 }}>
      <span style={{ color: "var(--muted)" }}>Stock at cost</span>
      <b style={{ fontSize: 18 }}><Money paise={1420000000} short /></b>
    </div>
    <div style={{ display: "flex", justifyContent: "space-between", fontSize: 14 }}>
      <span style={{ color: "var(--muted)" }}>Cash in drawer</span>
      <b style={{ fontSize: 18 }}><Money paise={4785000} short /></b>
    </div>
  </div>
);

/** Whole rupees show no paise; anything with paise shows both digits. */
export const Precision = () => (
  <div className="card" style={{ padding: 16, maxWidth: 360, display: "grid", gap: 8, fontSize: 15 }}>
    <p className="eyebrow">Rounding</p>
    <div><Money paise={100000} /> <span style={{ color: "var(--caption)", fontSize: 12.5 }}>— whole rupees, no decimals</span></div>
    <div><Money paise={122250} /> <span style={{ color: "var(--caption)", fontSize: 12.5 }}>— paise present, both digits</span></div>
    <div><Money paise={0} /> <span style={{ color: "var(--caption)", fontSize: 12.5 }}>— zero</span></div>
    <div><Money paise={-45000} /> <span style={{ color: "var(--caption)", fontSize: 12.5 }}>— credit / refund</span></div>
  </div>
);
