import { KeyRound, Plus, X } from "lucide-react";

import { Money } from "../../../lib/format";
import type { priceCart } from "../../../till/cart";
import { newNote } from "../../../till/tender";
import type { NoteStanding, Payment } from "../../../till/tender";
import { RupeeInput } from "./RupeeInput";

// --- the payment panel -----------------------------------------------------

/**
 * The four trimmed modes, the notes among them, and what is still unpaid (#182).
 *
 * The cash box is deliberately not a controlled copy of the derived figure: the
 * cash tender is `null` until somebody types in it, meaning "whatever is left of
 * the bill", so an all-cash sale needs no keystrokes and a split says out loud
 * that it is one. Clearing the box hands the row back to the balance.
 */
export function PaymentPanel({
  bill,
  payment,
  locked,
  onChange,
  onAsk,
}: {
  bill: ReturnType<typeof priceCart>;
  payment: Payment;
  locked: boolean;
  onChange: (patch: Partial<Payment>) => void;
  onAsk: () => void;
}) {
  const { split } = bill;
  // An exchange whose returns outweigh its sales pays the *customer*, and it pays
  // them in a credit note rather than out of the drawer (#184, grill Q7). The
  // panel closes rather than showing a negative to collect: there is no amount to
  // take, and a cash box a cashier could still type into is a drawer somebody
  // could still open.
  if (bill.credit_note_paise > 0) {
    return (
      <section className="card section-card bill-panel" data-testid="bill-owes-customer">
        <p className="eyebrow">Owed to the customer</p>
        <p className="bill-due" data-testid="bill-credit-note">
          <Money paise={bill.credit_note_paise} />
        </p>
        <p className="muted-cell">
          The pieces coming back are worth more than the ones going out. Save &amp; Print issues a
          credit note for the difference, spendable at this shop - no cash comes out of the
          drawer. Its number prints on the bill.
        </p>
      </section>
    );
  }
  return (
    <section className="card section-card bill-panel">
      <p className="eyebrow">To pay</p>
      <p className="bill-due" data-testid="bill-due">
        <Money paise={bill.net_paise} />
      </p>

      <div className="bill-tenders">
        <TenderRow
          testId="bill-cash"
          label="Cash"
          paise={split.cash_paise}
          derived={payment.cash_paise === null}
          locked={locked}
          onChange={(paise) => onChange({ cash_paise: paise })}
        />
        <TenderRow
          testId="bill-card"
          label="Card"
          paise={payment.card_paise}
          locked={locked}
          onChange={(paise) => onChange({ card_paise: paise ?? 0 })}
        />
        <TenderRow
          testId="bill-upi"
          label="UPI"
          paise={payment.upi_paise}
          locked={locked}
          onChange={(paise) => onChange({ upi_paise: paise ?? 0 })}
        />
      </div>

      <Notes
        notes={split.notes}
        locked={locked}
        onChange={(index, patch) =>
          onChange({
            notes: payment.notes.map((note, i) => (i === index ? { ...note, ...patch } : note)),
          })
        }
        onAdd={() => onChange({ notes: [...payment.notes, newNote()] })}
        onRemove={(index) =>
          onChange({ notes: payment.notes.filter((_, i) => i !== index) })
        }
      />

      <div className="bill-row">
        <span>Still to pay</span>
        <span
          data-testid="bill-balance"
          className={split.balance_paise === 0 ? "" : "bill-unpaid"}
        >
          <Money paise={split.balance_paise} />
        </span>
      </div>

      <div className="field">
        <label htmlFor="bill-cash-received">Cash received</label>
        <RupeeInput
          testId="bill-cash-received"
          label="Cash received"
          paise={payment.cash_received_paise}
          locked={locked}
          placeholder="0"
          onChange={(paise) => onChange({ cash_received_paise: paise ?? 0 })}
        />
      </div>
      <div className="bill-row">
        <span>Change</span>
        <span data-testid="bill-change">
          <Money paise={split.change_paise} />
        </span>
      </div>

      <Authorised bill={bill} locked={locked} onAsk={onAsk} />
    </section>
  );
}

/** One mode's amount. `derived` is the cash row following the balance - it shows
 *  the figure it is about to take without pretending a person typed it. */
function TenderRow({
  testId,
  label,
  paise,
  derived,
  locked,
  onChange,
}: {
  testId: string;
  label: string;
  paise: number;
  derived?: boolean;
  locked: boolean;
  onChange: (paise: number | null) => void;
}) {
  return (
    <div className="bill-tender">
      <label htmlFor={testId}>
        {label}
        {derived && (
          <span className="muted-cell" data-testid={`${testId}-derived`}>
            the rest
          </span>
        )}
      </label>
      <RupeeInput
        testId={testId}
        label={label}
        paise={paise}
        locked={locked}
        placeholder="0"
        onChange={onChange}
      />
    </div>
  );
}

/** The credit notes on this bill, and what the counter knows about each. */
function Notes({
  notes,
  locked,
  onChange,
  onAdd,
  onRemove,
}: {
  notes: NoteStanding[];
  locked: boolean;
  onChange: (index: number, patch: { number?: string; amount_paise?: number }) => void;
  onAdd: () => void;
  onRemove: (index: number) => void;
}) {
  return (
    <div className="bill-notes">
      {notes.map((standing, index) => (
        <div className="bill-note" key={standing.note.key}>
          <div className="bill-note-row">
            <input
              className="input bill-cell"
              data-testid={`bill-note-number-${index}`}
              aria-label={`Credit note number, row ${index + 1}`}
              autoComplete="off"
              placeholder="Credit note number"
              disabled={locked}
              value={standing.note.number}
              onChange={(e) => onChange(index, { number: e.target.value })}
            />
            <RupeeInput
              testId={`bill-note-amount-${index}`}
              label={`Credit note amount, row ${index + 1}`}
              paise={standing.note.amount_paise}
              locked={locked}
              placeholder="0"
              onChange={(paise) => onChange(index, { amount_paise: paise ?? 0 })}
            />
            <button
              type="button"
              className="line-del"
              disabled={locked}
              data-testid={`bill-note-remove-${index}`}
              aria-label={`Take credit note row ${index + 1} off the bill`}
              onClick={() => onRemove(index)}
            >
              <X size={14} />
            </button>
          </div>
          {standing.cached && !standing.doubt && (
            <span className="muted-cell" data-testid={`bill-note-left-${index}`}>
              <Money paise={standing.cached.remaining_paise} /> left · good to{" "}
              {standing.cached.expires_on}
            </span>
          )}
          {standing.doubt && (
            <span className="bill-overcap" data-testid={`bill-note-doubt-${index}`}>
              {standing.doubt}
            </span>
          )}
        </div>
      ))}
      <button
        type="button"
        className="btn bill-note-add"
        data-testid="bill-note-add"
        disabled={locked}
        onClick={onAdd}
      >
        <Plus size={14} />
        Credit note
      </button>
    </div>
  );
}

/** The manager's tap: what this bill needs, and who has agreed to it. */
function Authorised({
  bill,
  locked,
  onAsk,
}: {
  bill: ReturnType<typeof priceCart>;
  locked: boolean;
  onAsk: () => void;
}) {
  const { asks, needsAuthorising, authorisation } = bill;
  if (!asks.length && !authorisation) return null;
  return (
    <div className="bill-authorised" data-testid="bill-authorised">
      {authorisation && (
        <span className="muted-cell" data-testid="bill-authorised-by">
          Approved by {authorisation.name} at {formatClock(authorisation.at)}
        </span>
      )}
      {needsAuthorising.length > 0 && (
        <button
          type="button"
          className="btn"
          data-testid="bill-ask-manager"
          disabled={locked}
          onClick={onAsk}
        >
          <KeyRound size={15} />
          Manager approval
        </button>
      )}
    </div>
  );
}

function formatClock(iso: string): string {
  const at = new Date(iso);
  return Number.isNaN(at.getTime())
    ? iso
    : at.toLocaleTimeString("en-IN", { hour: "2-digit", minute: "2-digit" });
}
