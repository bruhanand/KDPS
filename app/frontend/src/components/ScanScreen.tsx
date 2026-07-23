/**
 * ScanScreen — the phone-first scan surface (#68).
 *
 * Full-screen scan target, big running count, distinct beeps for right and
 * wrong pieces, one confirm button. Built for keyboard-wedge scanners (the
 * scanner types the code and sends Enter): an invisible input keeps focus and
 * swallows the keystrokes, with a manual type-in fallback for tags that won't
 * scan. Every later scan flow (receive, counting, returns) reuses this screen.
 *
 * Scan-is-truth: the scanned counts are the only quantities handed to
 * onConfirm. A piece outside the target list beeps wrong and is rejected
 * (unless the flow allows scan-to-build via `lookup`). A quantity gap versus
 * the expected numbers is flagged on screen, never blocked (Rule 5) — except
 * `strictExpected` flows (receive), where scanning MORE than was sent is a
 * wrong-piece beep.
 */

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Check, CornerUpLeft, X } from "lucide-react";

import "./ScanScreen.css";

export interface ScanTarget {
  barcode: string;
  label: string; // "Shirt · Blue · M"
  expected: number | null; // planned (dispatch) / sent (receive); null = no plan
  available?: number | null; // stock cap for scan-to-build lines
}

interface ScanScreenProps {
  mode: string; // "DISPATCH" | "RECEIVE" — shown in the header chip
  docLabel: string; // doc number or "Draft #12"
  routeLabel: string; // "RAN-WH → DEO"
  targets: ScanTarget[];
  /** Scan-to-build: resolve an unknown barcode (null → wrong piece). */
  lookup?: (barcode: string) => Promise<ScanTarget | null>;
  /** Receive: never allow scanning past `expected` (server rejects too). */
  strictExpected?: boolean;
  confirmLabel: string;
  busy?: boolean;
  error?: string;
  onConfirm: (scans: Record<string, number>) => void;
  onClose: () => void;
}

// --- audio: two unmistakable beeps (ok = short high ping, wrong = low buzz) --

let audioCtx: AudioContext | null = null;
function ctx(): AudioContext {
  audioCtx ??= new AudioContext();
  return audioCtx;
}

function tone(freq: number, ms: number, type: OscillatorType, when = 0) {
  try {
    const ac = ctx();
    const osc = ac.createOscillator();
    const gain = ac.createGain();
    osc.type = type;
    osc.frequency.value = freq;
    gain.gain.value = 0.25;
    osc.connect(gain).connect(ac.destination);
    const t0 = ac.currentTime + when;
    osc.start(t0);
    osc.stop(t0 + ms / 1000);
  } catch {
    /* no audio available — the visual flash still fires */
  }
}

function beepOk() {
  tone(1320, 90, "sine");
  navigator.vibrate?.(30);
}

function beepWrong() {
  tone(196, 160, "square");
  tone(196, 160, "square", 0.2);
  navigator.vibrate?.([120, 60, 120]);
}

// ---------------------------------------------------------------------------

export function ScanScreen({
  mode,
  docLabel,
  routeLabel,
  targets,
  lookup,
  strictExpected = false,
  confirmLabel,
  busy = false,
  error = "",
  onConfirm,
  onClose,
}: ScanScreenProps) {
  const [lines, setLines] = useState<ScanTarget[]>(targets);
  const [scanned, setScanned] = useState<Record<string, number>>({});
  const [history, setHistory] = useState<string[]>([]);
  const [flash, setFlash] = useState<"" | "ok" | "bad">("");
  const [last, setLast] = useState<{ text: string; ok: boolean } | null>(null);
  const [manual, setManual] = useState("");
  const sinkRef = useRef<HTMLInputElement>(null);
  const flashTimer = useRef<number>(0);

  // The wedge scanner types into whatever is focused — keep the sink focused.
  useEffect(() => {
    const t = window.setInterval(() => {
      const active = document.activeElement;
      if (active?.className !== "scan-manual-input" && active !== sinkRef.current) {
        sinkRef.current?.focus();
      }
    }, 400);
    sinkRef.current?.focus();
    return () => window.clearInterval(t);
  }, []);

  const showResult = useCallback((ok: boolean, text: string) => {
    setFlash(ok ? "ok" : "bad");
    setLast({ text, ok });
    window.clearTimeout(flashTimer.current);
    flashTimer.current = window.setTimeout(() => setFlash(""), 250);
    if (ok) beepOk();
    else beepWrong();
  }, []);

  const applyScan = useCallback(
    async (raw: string) => {
      const code = raw.trim();
      if (!code || busy) return;

      let line = lines.find((l) => l.barcode === code);

      if (!line && lookup) {
        // scan-to-build: ask the server whether this piece exists here
        try {
          const found = await lookup(code);
          if (found) {
            line = found;
            setLines((ls) => [...ls, found]);
          }
        } catch {
          line = undefined;
        }
      }

      if (!line) {
        showResult(false, `${code} — not on this transfer`);
        return;
      }

      const count = scanned[code] ?? 0;
      if (strictExpected && line.expected != null && count >= line.expected) {
        showResult(false, `${code} — more than was sent (${line.expected})`);
        return;
      }
      if (line.available != null && count >= line.available) {
        showResult(false, `${code} — only ${line.available} in stock here`);
        return;
      }

      setScanned((s) => ({ ...s, [code]: (s[code] ?? 0) + 1 }));
      setHistory((h) => [...h, code]);
      showResult(true, `${code} ✓`);
    },
    [lines, scanned, busy, lookup, strictExpected, showResult],
  );

  function undoLast() {
    const code = history[history.length - 1];
    if (!code) return;
    setHistory((h) => h.slice(0, -1));
    setScanned((s) => {
      const next = { ...s, [code]: Math.max(0, (s[code] ?? 0) - 1) };
      if (next[code] === 0) delete next[code];
      return next;
    });
    setLast({ text: `undid ${code}`, ok: true });
  }

  const totalScanned = useMemo(
    () => Object.values(scanned).reduce((a, b) => a + b, 0),
    [scanned],
  );
  const totalExpected = useMemo(() => {
    if (lines.some((l) => l.expected == null)) return null;
    return lines.reduce((a, l) => a + (l.expected ?? 0), 0);
  }, [lines]);

  const hasMismatch =
    totalExpected != null &&
    totalScanned !== totalExpected &&
    totalScanned > 0 &&
    !strictExpected;
  const shortReceive =
    strictExpected && totalExpected != null && totalScanned > 0 && totalScanned < totalExpected;

  return (
    <div className="scan-screen" data-testid="scan-screen">
      <div className="scan-head">
        <span className="scan-head-mode">{mode}</span>
        <div className="scan-head-doc">
          <div className="doc">{docLabel}</div>
          <div className="route">{routeLabel}</div>
        </div>
        <button type="button" className="scan-close" onClick={onClose} aria-label="Close" data-testid="scan-close">
          <X size={22} />
        </button>
      </div>

      {/* wedge-capture sink: the scanner types here and sends Enter */}
      <input
        ref={sinkRef}
        className="scan-sink"
        aria-hidden="true"
        tabIndex={-1}
        autoComplete="off"
        onKeyDown={(e) => {
          if (e.key === "Enter") {
            e.preventDefault();
            const v = (e.target as HTMLInputElement).value;
            (e.target as HTMLInputElement).value = "";
            void applyScan(v);
          }
        }}
        data-testid="scan-sink"
      />

      <div className={`scan-target ${flash ? `flash-${flash}` : ""}`} onClick={() => sinkRef.current?.focus()}>
        <div className="scan-count" data-testid="scan-count">
          {totalScanned}
          {totalExpected != null && <span className="of"> / {totalExpected}</span>}
        </div>
        <div className="hint">Scan each piece — count climbs, wrong pieces buzz</div>
        <div className={`scan-last ${last ? (last.ok ? "ok" : "bad") : ""}`} data-testid="scan-last">
          {last?.text ?? ""}
        </div>
      </div>

      <div className="scan-manual">
        <input
          className="scan-manual-input"
          value={manual}
          placeholder="Tag won't scan? Type the barcode…"
          onChange={(e) => setManual(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter") {
              void applyScan(manual);
              setManual("");
            }
          }}
          data-testid="scan-manual-input"
        />
        <button
          type="button"
          onClick={() => {
            void applyScan(manual);
            setManual("");
          }}
          data-testid="scan-manual-add"
        >
          Add
        </button>
      </div>

      <div className="scan-lines" data-testid="scan-lines">
        {lines.map((l) => {
          const count = scanned[l.barcode] ?? 0;
          const done = l.expected != null && count === l.expected;
          const over = l.expected != null && count > l.expected;
          return (
            <div key={l.barcode} className={`scan-line ${done ? "done" : ""} ${over ? "over" : ""}`} data-testid={`scan-line-${l.barcode}`}>
              <div>
                <div className="code">{l.barcode}</div>
                <div className="meta">{l.label}</div>
              </div>
              <div className="counts">
                {count}
                {l.expected != null && <span className="exp"> / {l.expected}</span>}
              </div>
              {done && (
                <span className="tick">
                  <Check size={18} />
                </span>
              )}
            </div>
          );
        })}
        {lines.length === 0 && (
          <div className="scan-line">
            <div className="meta">Nothing scanned yet — scan the first piece to start the list.</div>
          </div>
        )}
      </div>

      {error ? (
        <div className="scan-error" data-testid="scan-error">{error}</div>
      ) : hasMismatch ? (
        <div className="scan-mismatch-note" data-testid="scan-mismatch-note">
          Scanned ≠ planned — the transfer will carry a mismatch flag.
        </div>
      ) : shortReceive ? (
        <div className="scan-mismatch-note" data-testid="scan-short-note">
          {totalExpected! - totalScanned} piece(s) not scanned — they stay in transit, flagged.
        </div>
      ) : null}

      <div className="scan-foot">
        <button type="button" className="scan-undo" onClick={undoLast} disabled={history.length === 0 || busy} data-testid="scan-undo">
          <CornerUpLeft size={16} /> Undo
        </button>
        <button
          type="button"
          className="scan-confirm"
          disabled={totalScanned === 0 || busy}
          onClick={() => onConfirm(scanned)}
          data-testid="scan-confirm"
        >
          <Check size={20} /> {busy ? "Posting…" : confirmLabel}
        </button>
      </div>
    </div>
  );
}
