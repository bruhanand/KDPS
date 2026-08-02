import { useEffect, useState } from "react";
import { AlertTriangle, CheckCircle2, QrCode, RefreshCw, WifiOff } from "lucide-react";

import { Money } from "../../../lib/format";
import { chargeStamp } from "../../../till/payment";
import type { ChargeStanding, PaymentAdapter, UpiCharged } from "../../../till/payment";
// The house modal (`.modal-backdrop` / `.modal` / `.modal-head`), which every
// screen with a dialog on it borrows from the same place.
import "../../Booking.css";

// ---------------------------------------------------------------------------
// The QR charge card (#248, grill Q5)
// ---------------------------------------------------------------------------
//
// Five states on one card, and the cashier can leave from any of them with the
// bill exactly as they left it. Nothing here writes to the cart until the bank
// says a payment happened, and on this build nothing can - the mock adapter
// cannot emit `success` (see `till/payment.ts`). What ships now is the flow and
// the seam; the hardware slice swaps the adapter underneath and touches no
// screen.
//
// Two things about it are decisions rather than layout.
//
// **The counter never decides a timeout.** `unknown` is its own state with its
// own words - "this counter cannot reach the bank" - and its own button, and it
// stays unknown however long the cashier waits. A till that quietly called it
// failed would send the cashier to collect money the customer may already have
// paid (grill Q5).
//
// **Closing is always available and always safe.** Cancel, a failure, an
// unknown, the backdrop, Escape - every way out lands back on the payment card
// with the UPI figure the cashier typed still in the box, ready to be saved as
// `manual`, which is the fallback that must never stop working: manual UPI
// entry is allowed forever, because billing never stops on the internet.

/** What the card is showing before the adapter has said anything at all. The
 *  first frame of a charge is `generating` and it arrives synchronously, so this
 *  is a floor rather than a state anybody should see. */
const OPENING: ChargeStanding = { state: "generating", reason: "", qr: "" };

export function UpiCharge({
  amountPaise,
  adapter,
  onConfirmed,
  onClose,
}: {
  /** What the UPI row is taking - the figure being charged, and the figure the
   *  stamp will be pinned to. */
  amountPaise: number;
  adapter: PaymentAdapter;
  /** The bank answered. Only reachable behind a real adapter. */
  onConfirmed: (charged: UpiCharged) => void;
  onClose: () => void;
}) {
  const [standing, setStanding] = useState<ChargeStanding>(OPENING);
  /** Bumped by "Show the QR again", which is how a failed card starts over. */
  const [attempt, setAttempt] = useState(0);
  const [checking, setChecking] = useState(false);

  useEffect(() => {
    // `live` as well as `adapter.cancel()`: the cancel stops the mock's own
    // timers, and the flag stops a state that is already in flight from landing
    // on an unmounted card. React's StrictMode runs this twice on mount, which
    // is exactly the race, so it is guarded rather than assumed away.
    let live = true;
    setStanding(OPENING);
    void (async () => {
      for await (const next of adapter.charge(amountPaise)) {
        if (!live) return;
        setStanding(next);
        const charged = chargeStamp(next, amountPaise);
        if (charged) {
          onConfirmed(charged);
          return;
        }
      }
    })();
    return () => {
      live = false;
      void adapter.cancel();
    };
    // `onConfirmed` is deliberately out of the deps: it closes over the
    // screen's own `setCart`, so a new identity on every render would restart
    // the charge on every render - a QR that regenerates while the customer is
    // trying to scan it. The screen wraps it in `useCallback` for the same
    // reason, so this is belt and braces rather than a leak.
  }, [adapter, amountPaise, attempt, onConfirmed]);

  /** Ask the bank again. Never a way to fail a charge - `checkStatus` reports
   *  where it stands, and an unknown that stays unknown is the honest answer. */
  async function recheck() {
    if (checking) return;
    setChecking(true);
    try {
      const now = await adapter.checkStatus();
      if (!now) return;
      setStanding(now);
      const charged = chargeStamp(now, amountPaise);
      if (charged) onConfirmed(charged);
    } finally {
      setChecking(false);
    }
  }

  const waiting = standing.state === "generating" || standing.state === "awaiting";

  return (
    <div className="modal-backdrop" data-testid="bill-upi-modal" onClick={onClose}>
      <div
        className="modal bill-upi"
        role="dialog"
        aria-label="UPI payment"
        data-state={standing.state}
        onClick={(e) => e.stopPropagation()}
        onKeyDown={(e) => {
          if (e.key === "Escape") onClose();
        }}
      >
        <div className="modal-head">
          <h3 className="h3">
            <QrCode size={17} style={{ verticalAlign: "-3px", marginRight: 6 }} />
            UPI payment
          </h3>
          <button type="button" className="btn" data-testid="bill-upi-close" onClick={onClose}>
            {waiting ? "Cancel" : "Close"}
          </button>
        </div>

        {/* The figure the customer is being asked for, in the size it should be
            read at across a counter. It is the one thing on this card that is
            true in every state. */}
        <p className="bill-upi-amount" data-testid="bill-upi-amount">
          <Money paise={amountPaise} />
        </p>

        {waiting ? (
          <Waiting standing={standing} />
        ) : (
          <Answer standing={standing} />
        )}

        <div className="bill-upi-actions">
          {(standing.state === "awaiting" || standing.state === "unknown") && (
            <button
              type="button"
              className="btn btn-cta"
              data-testid="bill-upi-check"
              disabled={checking}
              onClick={() => void recheck()}
            >
              <RefreshCw size={15} />
              {checking ? "Checking…" : "Check status"}
            </button>
          )}
          {standing.state === "failed" && (
            <button
              type="button"
              className="btn btn-cta"
              data-testid="bill-upi-again"
              onClick={() => setAttempt((n) => n + 1)}
            >
              <QrCode size={15} />
              Show the QR again
            </button>
          )}
        </div>

        <p className="muted-cell" data-testid="bill-upi-fallback">
          Closing this leaves the bill exactly as it is. The UPI amount stays on the payment
          card, and saving it records the payment on the cashier&apos;s word - which the day
          close shows separately from the ones the bank confirmed.
        </p>
      </div>
    </div>
  );
}

/** Generating and awaiting: the QR, and what the counter is waiting for. */
function Waiting({ standing }: { standing: ChargeStanding }) {
  const generating = standing.state === "generating";
  return (
    <>
      <div className="bill-upi-qr" data-testid="bill-upi-qr">
        {/* A real adapter hands over the acquirer's `upi://pay?…` payload and
            this becomes a drawn code. The mock has none, and a made-up square
            that looks scannable and pays nobody would be worse than saying so -
            which is why the placeholder says which counter it is standing on. */}
        <QrCode size={64} aria-hidden="true" />
        <span>
          {generating
            ? "Making the code…"
            : standing.qr
              ? "Ask the customer to scan this with any UPI app."
              : "No payment machine is connected to this counter yet, so there is no code to scan. This is the flow, waiting on the hardware."}
        </span>
      </div>
      <p className="bill-upi-says" data-testid="bill-upi-says">
        {generating
          ? "Asking the bank for a code."
          : "Waiting for the bank to say the money arrived. This card waits as long as it takes - only the bank decides that a payment did not happen."}
      </p>
    </>
  );
}

/** Success, failed, unknown: what the bank said, and what to do about it. */
function Answer({ standing }: { standing: ChargeStanding }) {
  if (standing.state === "success") {
    return (
      <p className="bill-upi-answer is-good" data-testid="bill-upi-answer">
        <CheckCircle2 size={18} />
        <span>
          The bank confirmed this payment. Reference {standing.reference}. It goes on the bill as
          confirmed.
        </span>
      </p>
    );
  }
  const unknown = standing.state === "unknown";
  return (
    <p
      className={unknown ? "bill-upi-answer is-doubt" : "bill-upi-answer is-bad"}
      data-testid="bill-upi-answer"
    >
      {unknown ? <WifiOff size={18} /> : <AlertTriangle size={18} />}
      <span>{standing.reason}</span>
    </p>
  );
}
