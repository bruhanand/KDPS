import { CircleAlert } from "lucide-react";
import type { CounterMode } from "./BillBar";

/** The rail's fixed commit point, below the scrollable payment and customer tiles. */
export function RailFoot({
  blocked,
  saving,
  mode,
  paper,
  lastBillNumber,
  onReprint,
  onSave,
}: {
  blocked: string;
  saving: boolean;
  mode: CounterMode;
  paper: number | null;
  lastBillNumber: string | null;
  onReprint: () => void;
  onSave: () => void;
}) {
  const primaryLabel =
    saving
      ? "Saving…"
      : paper !== null
        ? `Save bill ${paper}`
        : mode === "return"
          ? "Exchange & print"
          : "Save & print";

  return (
    <footer className="bill-rail-foot">
      {blocked && (
        <p className="bill-rail-blocked" data-testid="bill-blocked">
          <CircleAlert size={14} />
          {blocked}
        </p>
      )}
      <div className="bill-rail-actions">
        <button
          type="button"
          className="btn bill-rail-reprint"
          data-testid="bill-reprint"
          title="Reprint (no keyboard shortcut)"
          disabled={!lastBillNumber || saving}
          onClick={onReprint}
        >
          Reprint
          {lastBillNumber && <span className="mono">{lastBillNumber}</span>}
        </button>
        <button
          type="button"
          className="btn btn-cta bill-rail-save"
          data-testid="bill-save"
          title={mode === "return" ? "Exchange & Print (F9)" : "Save & Print (F9)"}
          disabled={Boolean(blocked) || saving}
          onClick={onSave}
        >
          {primaryLabel}
          {!saving && <span className="bill-rail-key mono">F9</span>}
        </button>
      </div>
    </footer>
  );
}
