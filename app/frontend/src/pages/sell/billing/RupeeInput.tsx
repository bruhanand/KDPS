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
  onChange,
}: {
  testId: string;
  label: string;
  paise: number;
  locked: boolean;
  placeholder: string;
  onChange: (paise: number | null) => void;
}) {
  const [text, setText] = useState(paise ? paiseToRupees(paise) : "");
  const shown = useRef(paise);

  useEffect(() => {
    // Follow the cart when something other than this box moved the number - a
    // season swap changing the ticket price, or a new bill clearing it.
    if (paise === shown.current) return;
    shown.current = paise;
    setText(paise ? paiseToRupees(paise) : "");
  }, [paise]);

  return (
    <input
      className="input bill-cell"
      inputMode="decimal"
      data-testid={testId}
      aria-label={label}
      disabled={locked}
      placeholder={placeholder}
      value={text}
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
