import { useEffect } from "react";

export type CounterKeyAction = "hold" | "lookup" | "new-bill" | "save" | "back-to-scan";

/** The counter owns these keys. Keeping the map pure makes the browser handler
 * small and gives the operational key contract one direct test seam. */
export function counterKeyAction(key: string): CounterKeyAction | null {
  switch (key) {
    case "F2":
      return "hold";
    case "F3":
      return "lookup";
    case "F4":
      return "new-bill";
    case "F9":
      return "save";
    case "Escape":
      return "back-to-scan";
    default:
      return null;
  }
}

/** Claim the counter's accelerators unless a modal is asking the cashier a
 * question. A modal owns its own Escape handling, so the bill must stay still. */
export function useCounterKeys({
  disabled,
  onHold,
  onLookup,
  onNewBill,
  onSave,
  onBackToScan,
}: {
  disabled: boolean;
  onHold: () => void;
  onLookup: () => void;
  onNewBill: () => void;
  onSave: () => void;
  onBackToScan: () => void;
}): void {
  useEffect(() => {
    function onKeyDown(event: KeyboardEvent) {
      const action = counterKeyAction(event.key);
      if (!action || disabled) return;

      event.preventDefault();
      if (event.repeat) return;

      switch (action) {
        case "hold":
          onHold();
          break;
        case "lookup":
          onLookup();
          break;
        case "new-bill":
          onNewBill();
          break;
        case "save":
          onSave();
          break;
        case "back-to-scan":
          onBackToScan();
          break;
      }
    }

    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [disabled, onBackToScan, onHold, onLookup, onNewBill, onSave]);
}
