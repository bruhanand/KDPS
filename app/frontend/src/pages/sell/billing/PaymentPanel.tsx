import { KeyRound, Plus, X } from "lucide-react";

import { formatINR, Money } from "../../../lib/format";
import type { priceCart } from "../../../till/cart";
import {
  balanceStandingOf,
  cashChips,
  newNote,
  notePrefillFor,
  prefillFor,
} from "../../../till/tender";
import type { NoteStanding, Payment, TenderSplit } from "../../../till/tender";
import { RupeeInput } from "./RupeeInput";

/** One tender row's offer: the balance if the row is standing empty, nothing if
 *  somebody has already filled it. Written once so a fifth row cannot get the
 *  emptiness test subtly wrong - the three modes each spell "empty" their own
 *  way (`null` for cash, nought for the rest). */
function offerIf(empty: boolean, owed: number): number | null {
  return empty ? owed : null;
}

/**
 * The four trimmed modes, the notes among them, and what is still unpaid (#182,
 * rebuilt by #246 around one rule: what is still owed is always on screen, and
 * tapping a tender row fills it).
 *
 * The cash box is deliberately not a controlled copy of the derived figure: the
 * cash tender is `null` until somebody types in it, meaning "whatever is left of
 * the bill", so an all-cash sale needs no keystrokes and a split says out loud
 * that it is one. Clearing the box hands the row back to the balance.
 *
 * There is no split-payment *mode*, and never was: the rows are the split. What
 * #246 adds is the arithmetic a cashier was doing in their head between them -
 * tapping an empty row offers the remainder (`prefillFor`), typing over it
 * splits, and one colour-coded line says whether money is still coming in or
 * going back out. None of it moves a figure `splitOf` computes, so the day-close
 * numbers are the same numbers.
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
  const owed = prefillFor(split);
  // The cash row is what the customer is handing notes against, so the chips are
  // read off it rather than off `balance_paise` - which is nought on the
  // ordinary all-cash panel, the one sale the chips were asked for.
  const chips = cashChips(split.cash_paise);
  // Hidden when the bill takes no cash at all - but never while it holds a
  // figure somebody typed, which would put a control out of reach (the standing
  // rule behind grill-decisions amendment 12: never hide a control).
  const showReceived = split.cash_paise > 0 || payment.cash_received_paise > 0;

  return (
    <section className="card section-card bill-panel">
      <p className="eyebrow">To pay</p>
      <p className="bill-due" data-testid="bill-due">
        <Money paise={bill.net_paise} />
      </p>

      <div className="bill-tenders">
        <div className="bill-cash-block">
          <TenderRow
            testId="bill-cash"
            label="Cash"
            paise={split.cash_paise}
            // Empty in the sense the prefill cares about: the row shows the
            // balance it is about to absorb, but nobody has typed in it yet.
            prefillPaise={offerIf(payment.cash_paise === null, owed)}
            derived={payment.cash_paise === null}
            locked={locked}
            onChange={(paise) => onChange({ cash_paise: paise })}
          />
          <CashChips
            chips={chips}
            locked={locked}
            onPick={(paise) => onChange({ cash_received_paise: paise })}
          />
          {showReceived && (
            <TenderRow
              testId="bill-cash-received"
              label="Cash received"
              paise={payment.cash_received_paise}
              // Never prefilled: what the customer physically handed over is the
              // one figure on this panel the till has no business guessing - the
              // chips are how it is offered, one deliberate tap at a time.
              locked={locked}
              quiet
              onChange={(paise) => onChange({ cash_received_paise: paise ?? 0 })}
            />
          )}
        </div>
        <TenderRow
          testId="bill-card"
          label="Card"
          paise={payment.card_paise}
          prefillPaise={offerIf(payment.card_paise === 0, owed)}
          locked={locked}
          onChange={(paise) => onChange({ card_paise: paise ?? 0 })}
        />
        <TenderRow
          testId="bill-upi"
          label="UPI"
          paise={payment.upi_paise}
          prefillPaise={offerIf(payment.upi_paise === 0, owed)}
          locked={locked}
          onChange={(paise) => onChange({ upi_paise: paise ?? 0 })}
        />
      </div>

      <Notes
        notes={split.notes}
        locked={locked}
        prefillFor={(standing) =>
          offerIf(standing.note.amount_paise === 0, notePrefillFor(split, standing))
        }
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

      <BalanceLine split={split} />

      <Authorised bill={bill} locked={locked} onAsk={onAsk} />
    </section>
  );
}

/**
 * The one line that says where the money stands - red while the bill is short,
 * green when there is change to hand back, and never both at once (#246).
 *
 * It replaced a "Still to pay" row and a "Change" row that were on screen
 * together, each answering with a ₹0 for most of the bill's life. Two figures
 * that are nearly always nought teach a cashier to stop reading them, which is
 * the opposite of what the one number that matters is for.
 *
 * Which of the five it is, and in what words, is `balanceStandingOf`'s - a rule
 * with its own tests, because the green line is an instruction to open the
 * drawer and this component is only allowed to draw it.
 */
function BalanceLine({ split }: { split: TenderSplit }) {
  const { tone, says, paise } = balanceStandingOf(split);
  return (
    <p
      className={`bill-balance-line is-${tone}`}
      data-testid="bill-balance-line"
      data-tone={tone}
    >
      <span>{says}</span>
      <span data-testid="bill-balance">
        <Money paise={paise} />
      </span>
    </p>
  );
}

/**
 * The quick-cash chips (grill Q4): what the customer is most likely to hand
 * over for the cash half of this bill, one tap each.
 *
 * They record `cash_received_paise` and nothing else - the tender rows are
 * untouched, so a chip can never change what the bill takes, only what the
 * change line answers. Exact is first because it is the common one and because
 * it closes that line to nought.
 */
function CashChips({
  chips,
  locked,
  onPick,
}: {
  chips: number[];
  locked: boolean;
  onPick: (paise: number) => void;
}) {
  if (!chips.length) return null;
  return (
    <div className="bill-chips" data-testid="bill-cash-chips">
      {chips.map((paise, index) => (
        <button
          key={paise}
          type="button"
          className="btn bill-chip"
          data-testid={`bill-cash-chip-${index}`}
          // `formatINR`, never `paise / 100`: a screen reader should hear the
          // same Indian-grouped figure the chip shows, and money is never
          // divided by a hundred on the way out of a paise integer.
          aria-label={`Cash received ${formatINR(paise)}${index === 0 ? " - the exact amount" : ""}`}
          disabled={locked}
          onClick={() => onPick(paise)}
        >
          {index === 0 && <span className="bill-chip-tag">Exact</span>}
          <Money paise={paise} />
        </button>
      ))}
    </div>
  );
}

/** One mode's amount. `derived` is the cash row following the balance - it shows
 *  the figure it is about to take without pretending a person typed it.
 *  `quiet` is the cash-received row, which is a note to self about the drawer
 *  rather than a tender, and reads as one. */
function TenderRow({
  testId,
  label,
  paise,
  derived,
  quiet,
  prefillPaise = null,
  locked,
  onChange,
}: {
  testId: string;
  label: string;
  paise: number;
  derived?: boolean;
  quiet?: boolean;
  prefillPaise?: number | null;
  locked: boolean;
  onChange: (paise: number | null) => void;
}) {
  return (
    <div className={quiet ? "bill-tender is-quiet" : "bill-tender"}>
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
        prefillPaise={prefillPaise}
        onChange={onChange}
      />
    </div>
  );
}

/** The credit notes on this bill, and what the counter knows about each. */
function Notes({
  notes,
  locked,
  prefillFor,
  onChange,
  onAdd,
  onRemove,
}: {
  notes: NoteStanding[];
  locked: boolean;
  prefillFor: (standing: NoteStanding) => number | null;
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
              prefillPaise={prefillFor(standing)}
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
