import { useEffect, useRef, useState } from "react";

import { paiseToRupees, rupeesToPaise } from "../../../lib/format";

/**
 * An amount in rupees, held as integer paise.
 *
 * The typed text is state of its own so a half-written "12." survives the
 * keystroke that made it: parsing on every change and writing the parse back
 * would delete the decimal point as the cashier types it. Only text that is
 * actually an amount reaches the cart (`rupeesToPaise`, ADR-0004 - never
 * `Number(x) * 100`).
 *
 * An emptied box answers `null` rather than nought, and the caller says which it
 * means. For most boxes they are the same thing; for the cash tender they are
 * not - nought is "this bill takes no cash" and empty is "cash takes whatever is
 * left", and a cashier who clears the box to undo a split means the second.
 */
export function RupeeInput({
  testId,
  label,
  paise,
  locked,
  placeholder,
  prefillPaise = null,
  onChange,
}: {
  testId: string;
  label: string;
  paise: number;
  locked: boolean;
  placeholder: string;
  /**
   * What this box adopts if the cashier taps into it while it is standing empty
   * - `null` when it is already filled, or when there is nothing left to offer
   * (#246: "tapping into an empty amount box pre-fills whatever is still owed").
   *
   * Whether the box is empty is the **caller's** judgement, not this box's text.
   * The cash row displays the balance it is about to absorb while nobody has yet
   * typed in it, and that row is the one the prefill exists for; a rule based on
   * the text being blank would skip exactly it.
   *
   * Adopting a figure is an ordinary edit - it goes out through `onChange` like
   * any keystroke and can be typed straight over, which is what makes a split a
   * split.
   */
  prefillPaise?: number | null;
  onChange: (paise: number | null) => void;
}) {
  const [text, setText] = useState(paise ? paiseToRupees(paise) : "");
  const shown = useRef(paise);
  const box = useRef<HTMLInputElement>(null);
  // Counted rather than flagged: a prefill that lands on the figure already
  // shown - the cash row adopting the balance it was displaying anyway - leaves
  // `text` identical, so an effect watching the text would not run on the one
  // row this matters most for.
  const [prefills, setPrefills] = useState(0);

  useEffect(() => {
    // Follow the cart when something other than this box moved the number - a
    // season swap changing the ticket price, or a new bill clearing it.
    if (paise === shown.current) return;
    shown.current = paise;
    setText(paise ? paiseToRupees(paise) : "");
  }, [paise]);

  useEffect(() => {
    // A box that just adopted the balance is selected whole, so the next
    // keystroke replaces it: the ticket's flow is "tap UPI, it offers ₹2,848,
    // overtype ₹2,000", and a cashier who has to clear the offer first would
    // rather it had never been made.
    if (prefills > 0) box.current?.select();
  }, [prefills]);

  return (
    <input
      ref={box}
      className="input bill-cell"
      inputMode="decimal"
      data-testid={testId}
      aria-label={label}
      disabled={locked}
      placeholder={placeholder}
      value={text}
      onFocus={() => {
        if (locked || prefillPaise === null || prefillPaise <= 0) return;
        shown.current = prefillPaise;
        setText(paiseToRupees(prefillPaise));
        setPrefills((n) => n + 1);
        onChange(prefillPaise);
      }}
      onChange={(e) => {
        setText(e.target.value);
        if (e.target.value.trim() === "") {
          shown.current = 0;
          onChange(null);
          return;
        }
        // Text that is not an amount yet ("12.") is held on screen and kept off
        // the cart until it is one.
        const parsed = rupeesToPaise(e.target.value);
        if (parsed === null) return;
        shown.current = parsed;
        onChange(parsed);
      }}
    />
  );
}
