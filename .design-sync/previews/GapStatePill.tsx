import { GapStatePill } from "kdps-frontend";

/** A transfer's gap state is derived server-side, never typed. It answers one
 *  question: does what left the source store still match what was scanned in? */
export const AllStates = () => (
  <div className="card" style={{ padding: 16, maxWidth: 460 }}>
    <p className="eyebrow">Derived gap state</p>
    <div className="chip-picker" style={{ marginTop: 10 }}>
      <GapStatePill state="in_transit" />
      <GapStatePill state="received" />
      <GapStatePill state="gap" />
      <GapStatePill state="closed" />
    </div>
    <p className="lead" style={{ marginTop: 12, fontSize: 13 }}>
      A draft transfer has no state at all — the pill renders nothing until stock
      actually moves.
    </p>
  </div>
);

/** Where it earns its keep: the transfer register. Red is the only row anyone
 *  has to act on — pieces left RAN-WH and were never scanned in at Deoghar. */
export const InTheTransferRegister = () => (
  <div className="card" style={{ padding: 16, maxWidth: 520 }}>
    <p className="eyebrow">Transfers out · Ranchi warehouse</p>
    <table style={{ width: "100%", fontSize: 13.5, borderSpacing: "0 10px" }}>
      <tbody>
        <tr>
          <td className="mono">26-27/RAN-WH/TRF/118</td>
          <td style={{ color: "var(--muted)" }}>→ DEO</td>
          <td align="right"><GapStatePill state="gap" /></td>
        </tr>
        <tr>
          <td className="mono">26-27/RAN-WH/TRF/119</td>
          <td style={{ color: "var(--muted)" }}>→ JSL</td>
          <td align="right"><GapStatePill state="in_transit" /></td>
        </tr>
        <tr>
          <td className="mono">26-27/RAN-WH/TRF/120</td>
          <td style={{ color: "var(--muted)" }}>→ DEO</td>
          <td align="right"><GapStatePill state="received" /></td>
        </tr>
        <tr>
          <td className="mono">26-27/RAN-WH/TRF/114</td>
          <td style={{ color: "var(--muted)" }}>→ JSL</td>
          <td align="right"><GapStatePill state="closed" /></td>
        </tr>
      </tbody>
    </table>
  </div>
);

/** The state is a full sentence, not a code, because the person reading it six
 *  months later is a store manager, not the developer who wrote the transfer. */
export const WhatEachStateMeans = () => (
  <div className="card" style={{ padding: 16, maxWidth: 520, display: "grid", gap: 14 }}>
    <p className="eyebrow">Reading the pill</p>
    {[
      ["in_transit", "Dispatched from RAN-WH, nothing scanned at the other end yet."],
      ["received", "Every piece sent was scanned in. Nothing left to answer for."],
      ["gap", "The pieces sit in the in-transit bucket and RAN-WH is answerable for them."],
      ["closed", "The Operations Head closed it with a reason. The receiving store never can."],
    ].map(([state, meaning]) => (
      <div key={state} style={{ display: "grid", gap: 5 }}>
        <div>
          <GapStatePill state={state} />
        </div>
        <span className="lead" style={{ fontSize: 13 }}>{meaning}</span>
      </div>
    ))}
  </div>
);
