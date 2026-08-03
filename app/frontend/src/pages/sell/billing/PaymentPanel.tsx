import type { ReactNode } from "react";
import { Banknote, CheckCircle2, CreditCard, QrCode, Smartphone } from "lucide-react";

import { formatINR, Money } from "../../../lib/format";
import type { priceCart } from "../../../till/cart";
import {
  balanceStandingOf,
  canFillTenderRest,
  cashChips,
  prefillFor,
  restTenderPatch,
} from "../../../till/tender";
import type { Payment, TenderSplit } from "../../../till/tender";
import { RupeeInput } from "./RupeeInput";

/** One tender row's offer: the balance if the row is standing empty, nothing if
 *  somebody has already filled it. Written once so a fifth row cannot get the
 *  emptiness test subtly wrong - the three modes each spell "empty" their own
 *  way (`null` for cash, nought for the rest). */
function offerIf(empty: boolean, owed: number): number | null {
  return empty ? owed : null;
}

/**
 * The three incoming tender modes and what is still unpaid,
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
  onShowQr,
}: {
  bill: ReturnType<typeof priceCart>;
  payment: Payment;
  locked: boolean;
  onChange: (patch: Partial<Payment>) => void;
  /** Open the QR charge card against whatever the UPI row is taking (#248). */
  onShowQr: () => void;
}) {
  const { split } = bill;
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
    <section className="bill-payment-panel">
      <div className="bill-payment-heading">
        <p className="eyebrow">To pay</p>
        <p className="bill-due" data-testid="bill-due">
          <Money paise={bill.net_paise} />
        </p>
      </div>

      <div className="bill-payment-stack">
        <div className="bill-payment-method bill-cash-block">
          <TenderRow
            testId="bill-cash"
            label="Cash"
            icon={<Banknote size={16} />}
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
        <div className="bill-payment-method bill-upi-block">
          <TenderRow
            testId="bill-upi"
            label="UPI"
            icon={<Smartphone size={16} />}
            paise={payment.upi_paise}
            prefillPaise={offerIf(payment.upi_paise === 0, owed)}
            locked={locked}
            onChange={(paise) => onChange({ upi_paise: paise ?? 0 })}
            action={
              <RestButton
                disabled={locked || !canFillTenderRest(split, "upi")}
                onClick={() => onChange(restTenderPatch(split, "upi"))}
              />
            }
          />
          {(split.upi_paise > 0 || split.upi_confirmed) && (
            <UpiProof
              confirmed={split.upi_confirmed}
              locked={locked || split.upi_confirmed !== null}
              onShowQr={onShowQr}
            />
          )}
        </div>
        <div className="bill-payment-method">
          <TenderRow
            testId="bill-card"
            label="Card"
            icon={<CreditCard size={16} />}
            paise={payment.card_paise}
            prefillPaise={offerIf(payment.card_paise === 0, owed)}
            locked={locked}
            onChange={(paise) => onChange({ card_paise: paise ?? 0 })}
            action={
              <RestButton
                disabled={locked || !canFillTenderRest(split, "card")}
                onClick={() => onChange(restTenderPatch(split, "card"))}
              />
            }
          />
        </div>
      </div>

      <BalanceLine split={split} />
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

/**
 * How the UPI row is being proved (#248, grill Q5).
 *
 * Either the bank said so through the charge card - and then it says which
 * reference, because a stamp with nothing behind it is not a proof - or it is
 * the cashier's own word, which is what "show QR" is offered instead of. Both
 * are allowed, forever: billing never stops on the internet, and the control on
 * a vouched-for payment is that the day close shows the two totals apart.
 *
 * A row the bank has already confirmed cannot be charged again from here, and
 * that is a money guard rather than tidiness: with real hardware behind the
 * adapter, a second "Show QR" against a payment that has already gone through
 * is a second collection from the same customer. The way back is to change what
 * the row is taking - editing the box drops the stamp on its own
 * (`confirmedUpiOf`) and the button comes live again with it.
 */
function UpiProof({
  confirmed,
  locked,
  onShowQr,
}: {
  confirmed: TenderSplit["upi_confirmed"];
  locked: boolean;
  onShowQr: () => void;
}) {
  return (
    <div className="bill-upi-proof">
      <button
        type="button"
        className="btn bill-upi-open"
        data-testid="bill-upi-show-qr"
        disabled={locked}
        onClick={onShowQr}
      >
        <QrCode size={14} />
        Show QR
      </button>
      {confirmed && (
        <span className="bill-upi-confirmed" data-testid="bill-upi-confirmed">
          <CheckCircle2 size={13} />
          Bank confirmed · {confirmed}
        </span>
      )}
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
  icon,
  action,
  paise,
  derived,
  quiet,
  prefillPaise = null,
  locked,
  onChange,
}: {
  testId: string;
  label: string;
  icon?: ReactNode;
  action?: ReactNode;
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
        {icon && <span className="bill-tender-icon">{icon}</span>}
        {label}
        {derived && (
          <span className="muted-cell" data-testid={`${testId}-derived`}>
            the rest
          </span>
        )}
      </label>
      <span className="bill-tender-action">{action}</span>
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

function RestButton({ disabled, onClick }: { disabled: boolean; onClick: () => void }) {
  return (
    <button type="button" className="btn bill-tender-rest" disabled={disabled} onClick={onClick}>
      rest
    </button>
  );
}
