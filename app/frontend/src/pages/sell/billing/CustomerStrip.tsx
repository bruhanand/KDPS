import { AlertTriangle, FileText } from "lucide-react";

import { describeGstin, TAX_KIND_WORDS, taxKindFor } from "../../../till/gstin";
import type { TillCustomer } from "../../../till/types";

/**
 * Who the bill is for - and, when they give a GSTIN, what kind of bill it is.
 *
 * A GSTIN turns a retail sale into a full tax invoice (#187, grill Q8): the
 * split printed on the customer's copy is derived here, offline, from the
 * buyer's state against the shop's, because it prints minutes before head office
 * hears about the bill and cannot wait for anybody.
 *
 * The check on what they typed is *soft*, and visibly so. The counter says the
 * registration looks wrong and the bill closes anyway - the customer is standing
 * there holding the garment, and a mistyped character is a tax invoice head
 * office corrects, not a sale to decline. Saying it here is still worth doing,
 * because here is the one moment the customer can read their card out again.
 */
export function CustomerStrip({
  value,
  storeStateCode,
  locked,
  onChange,
}: {
  value: TillCustomer;
  /** Null when the counter has not learned which state it is in - see below. */
  storeStateCode: string | null;
  locked: boolean;
  onChange: (v: TillCustomer) => void;
}) {
  // A counter that does not know its own state cannot say which tax a business
  // bill carries, and there is no safe guess: one wrong answer prints IGST on a
  // local buyer's copy while the books post CGST + SGST, and the other does it
  // the other way round. So the field closes and says why, rather than taking a
  // registration it would then charge the wrong tax on.
  const canBillB2b = storeStateCode !== null;
  const kind = canBillB2b ? taxKindFor(value.gstin, storeStateCode) : "none";
  const malformed = canBillB2b ? describeGstin(value.gstin) : "";
  return (
    <section className="card section-card bill-panel">
      <p className="eyebrow">Customer</p>
      <div className="field">
        <label htmlFor="bill-mobile">Mobile</label>
        <input
          id="bill-mobile"
          className="input"
          data-testid="bill-mobile"
          autoComplete="off"
          disabled={locked}
          value={value.mobile}
          onChange={(e) => onChange({ ...value, mobile: e.target.value })}
        />
      </div>
      <div className="field">
        <label htmlFor="bill-customer-name">Name</label>
        <input
          id="bill-customer-name"
          className="input"
          data-testid="bill-customer-name"
          autoComplete="off"
          disabled={locked}
          value={value.name}
          onChange={(e) => onChange({ ...value, name: e.target.value })}
        />
      </div>
      <div className="field">
        <label htmlFor="bill-gstin">GSTIN (for a business bill)</label>
        <input
          id="bill-gstin"
          className="input mono"
          data-testid="bill-gstin"
          autoComplete="off"
          maxLength={15}
          spellCheck={false}
          disabled={locked || !canBillB2b}
          value={value.gstin}
          // Upper-cased as it is typed, so what the cashier reads back is what
          // prints and what the server stores - a GSTIN differing from itself by
          // case would flag every second business bill.
          onChange={(e) => onChange({ ...value, gstin: e.target.value.toUpperCase() })}
        />
      </div>
      {!canBillB2b && (
        <p className="bill-alert" data-testid="bill-gstin-unavailable">
          <AlertTriangle size={15} /> This counter has not synced its own registration yet, so it
          cannot say whether a buyer is in this state. Sync from Till &amp; Sync to bill a
          business; a retail bill is unaffected.
        </p>
      )}
      {kind !== "none" && (
        <p className="ok-note" data-testid="bill-tax-kind">
          <FileText size={15} /> Tax invoice · {TAX_KIND_WORDS[kind]}
          {kind === "igst" ? " (buyer is out of state)" : ""}
        </p>
      )}
      {malformed && (
        <p className="bill-alert" data-testid="bill-gstin-warning">
          <AlertTriangle size={15} /> {malformed} The bill will still close - check the card.
        </p>
      )}
      <p className="muted-cell">The bill works without any of these.</p>
    </section>
  );
}
