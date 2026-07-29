import { Money, Stat, StatusChip } from "kdps-frontend";

/** A label over a value. The value slot is a ReactNode, so it takes Money,
 *  a chip, or plain text. */
export const HeaderStats = () => (
  <div className="card" style={{ padding: 18, maxWidth: 560 }}>
    <p className="eyebrow">GRN 26-27/RAN-WH/GRN/311</p>
    <div style={{ display: "flex", gap: 40, marginTop: 12 }}>
      <Stat label="Pieces received" value="1,248" />
      <Stat label="Invoice value" value={<Money paise={128450000} short />} />
      <Stat label="Vendor" value="Credo Brands" />
      <Stat label="Status" value={<StatusChip status="Matched" />} />
    </div>
  </div>
);

/** The dense form, as it sits across the top of a ledger screen. */
export const LedgerSummary = () => (
  <div className="card" style={{ padding: 18, maxWidth: 560 }}>
    <p className="eyebrow">Deoghar · this month</p>
    <div style={{ display: "flex", gap: 40, marginTop: 12 }}>
      <Stat label="Bills" value="412" />
      <Stat label="Net sales" value={<Money paise={185600000} short />} />
      <Stat label="Returns" value={<Money paise={-4210000} short />} />
      <Stat label="Pieces sold" value="1,036" />
    </div>
  </div>
);
