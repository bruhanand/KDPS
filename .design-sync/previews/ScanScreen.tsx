import { useEffect, useRef } from "react";
import type { ReactNode } from "react";
import { ScanScreen } from "kdps-frontend";

/**
 * ScanScreen is the phone-first wedge-scanner surface reused by dispatch,
 * receipt and counting. It is `position: fixed; inset: 0`, so each card puts it
 * inside a phone-sized frame that owns its own containing block
 * (`transform: translateZ(0)`) — otherwise it would cover the whole preview.
 *
 * The scanned counts live in the component's own state, so a card that only
 * passed props would show an empty "0". Each cell therefore replays a real scan
 * run into the wedge sink (`data-testid="scan-sink"`), exactly the way a
 * keyboard-wedge scanner does: type the code, press Enter.
 */

type Step = { code: string } | { mode: "good" | "damaged" };

function Phone({ eyebrow, children }: { eyebrow: string; children: ReactNode }) {
  return (
    <div style={{ width: 392 }}>
      <p className="eyebrow" style={{ margin: "0 0 8px" }}>
        {eyebrow}
      </p>
      <div
        className="card"
        style={{
          position: "relative",
          width: 392,
          height: 600,
          overflow: "hidden",
          borderRadius: 16,
          transform: "translateZ(0)",
        }}
      >
        {children}
      </div>
    </div>
  );
}

/** Replay a scan run into the live component, one piece per tick. */
function useScanRun(root: React.RefObject<HTMLDivElement | null>, steps: Step[]) {
  useEffect(() => {
    let i = 0;
    const timer = window.setInterval(() => {
      const el = root.current;
      const step = steps[i++];
      if (!el || !step) {
        window.clearInterval(timer);
        return;
      }
      if ("mode" in step) {
        const btn = el.querySelector(`[data-testid="scan-mode-${step.mode}"]`);
        (btn as HTMLButtonElement | null)?.click();
        return;
      }
      const sink = el.querySelector('[data-testid="scan-sink"]') as HTMLInputElement | null;
      if (!sink) return;
      sink.value = step.code;
      sink.dispatchEvent(new KeyboardEvent("keydown", { key: "Enter", bubbles: true }));
    }, 24);
    return () => window.clearInterval(timer);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);
}

const noop = () => {};

// --- dispatch: a planned transfer, scanned short ----------------------------

const dispatchTargets = [
  { barcode: "8901234512347", label: "MUFTI · MFK-4471 · Indigo · 40", expected: 6 },
  { barcode: "8901234512354", label: "MUFTI · MFK-4471 · Indigo · 42", expected: 4 },
  { barcode: "8902117744319", label: "Levi's · 511-2847 · Stone Wash · 32", expected: 5 },
];

const dispatchRun: Step[] = [
  ...Array<Step>(6).fill({ code: "8901234512347" }),
  ...Array<Step>(4).fill({ code: "8901234512354" }),
  ...Array<Step>(3).fill({ code: "8902117744319" }),
];

/** Ranchi warehouse dispatching a planned transfer to Deoghar. Two lines are
 *  complete, one is short — scan-is-truth, so the gap is flagged, not blocked. */
export const DispatchTransfer = () => {
  const root = useRef<HTMLDivElement>(null);
  useScanRun(root, dispatchRun);
  return (
    <Phone eyebrow="Dispatch · Ranchi warehouse">
      <div ref={root} style={{ position: "absolute", inset: 0 }}>
        <ScanScreen
          mode="DISPATCH"
          docLabel="26-27/RAN-WH/TRF/118"
          routeLabel="RAN-WH → Deoghar (DEO)"
          targets={dispatchTargets}
          confirmLabel="Dispatch to Deoghar"
          onConfirm={noop}
          onClose={noop}
        />
      </div>
    </Phone>
  );
};

// --- receipt: good / damaged / extra, all three outcomes on one screen ------

const receiveTargets = [
  { barcode: "8901234512347", label: "MUFTI · MFK-4471 · Indigo · 40", expected: 6 },
];

const receiveRun: Step[] = [
  ...Array<Step>(5).fill({ code: "8901234512347" }),
  { mode: "damaged" },
  { code: "8901234512347" },
  { mode: "good" },
  { code: "8909988771234" },
];

/** Deoghar receiving the transfer. Every piece sent turned up, but one of them
 *  arrived broken and one piece arrived that was never sent — both taken in and
 *  flagged, because refusing them is how stock goes physically missing. */
export const ReceiveWithExceptions = () => {
  const root = useRef<HTMLDivElement>(null);
  useScanRun(root, receiveRun);
  return (
    <Phone eyebrow="Receive · Deoghar store">
      <div ref={root} style={{ position: "absolute", inset: 0 }}>
        <ScanScreen
          mode="RECEIVE"
          docLabel="26-27/DEO/GRN/47"
          routeLabel="RAN-WH → Deoghar (DEO)"
          targets={receiveTargets}
          strictExpected
          exceptions
          confirmLabel="Confirm receipt"
          onConfirm={noop}
          onClose={noop}
        />
      </div>
    </Phone>
  );
};

// --- blind count: no plan on screen, list built by scanning ------------------

const shelf: Record<string, { label: string; available: number }> = {
  "8901234512347": { label: "MUFTI · MFK-4471 · Indigo · 40", available: 9 },
  "8902117744319": { label: "Levi's · 511-2847 · Stone Wash · 32", available: 7 },
  "8905566001248": { label: "Peter England · PEKT-3308 · Navy · L", available: 5 },
};

const countRun: Step[] = [
  { code: "8901234512347" },
  { code: "8901234512347" },
  { code: "8901234512347" },
  { code: "8902117744319" },
  { code: "8902117744319" },
  { code: "8905566001248" },
  { code: "8908844220017" },
];

/** A blind stocktake at JSL: no expected numbers on screen at all, and the line
 *  list is built by the scanner. A piece this store does not stock buzzes. */
export const BlindCount = () => {
  const root = useRef<HTMLDivElement>(null);
  useScanRun(root, countRun);
  return (
    <Phone eyebrow="Stocktake · JSL">
      <div ref={root} style={{ position: "absolute", inset: 0 }}>
        <ScanScreen
          mode="COUNT"
          docLabel="26-27/JSL/CNT/09"
          routeLabel="Blind count · floor 1"
          targets={[]}
          lookup={async (barcode: string) => {
            const hit = shelf[barcode];
            return hit
              ? { barcode, label: hit.label, expected: null, available: hit.available }
              : null;
          }}
          rejectReason="not stocked at JSL"
          availableNoun="on the shelf"
          confirmLabel="Submit count"
          onConfirm={noop}
          onClose={noop}
        />
      </div>
    </Phone>
  );
};
