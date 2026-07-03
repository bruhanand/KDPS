import { useCallback, useEffect, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { ClipboardList, FileSpreadsheet } from "lucide-react";

import { api, apiErrorMessage } from "../lib/api";

/** A GRN as the work queue needs it — a subset of the inbound list row. */
export interface QueueGrnT {
  id: number;
  number: string;
  vendor_name: string;
  store_code: string;
  invoice_number: string;
  received_total: number;
  created_at: string;
}

export interface QueueT {
  awaiting_pt: QueueGrnT[];
  pt_in_progress: {
    id: number;
    original_filename: string;
    source: string;
    stage: string;
    stage_label: string;
    grn_id: number | null;
    grn_number: string | null;
    row_count: number;
    blank_cell_count: number;
  }[];
  counts: { awaiting_pt: number; pt_in_progress: number };
}

function fmtDate(iso: string): string {
  return new Date(iso).toLocaleDateString("en-IN", { day: "numeric", month: "short", year: "numeric" });
}

/** The inbound work queue (Q9: in-app record). null = not loaded / not my screen (403). */
export function useInboundQueue() {
  const [queue, setQueue] = useState<QueueT | null>(null);
  const reload = useCallback(() => {
    api
      .get("/inbound/queue")
      .then((r) => setQueue(r.data))
      .catch(() => setQueue(null));
  }, []);
  useEffect(reload, [reload]);
  return { queue, reload };
}

/** POST from-grn and jump into the PT editor; 409 with an existing PT also navigates to it. */
export function useMakePt() {
  const navigate = useNavigate();
  const [makingId, setMakingId] = useState<number | null>(null);
  const [error, setError] = useState("");
  async function makePt(grnId: number) {
    setMakingId(grnId);
    setError("");
    try {
      const { data } = await api.post(`/ptmapper/files/from-grn/${grnId}`);
      navigate(`/documents/pt-mapper/${data.id}`);
    } catch (e: any) {
      const existing = e?.response?.data?.pt_file_id;
      if (existing) {
        navigate(`/documents/pt-mapper/${existing}`);
        return;
      }
      setError(apiErrorMessage(e));
    } finally {
      setMakingId(null);
    }
  }
  return { makePt, makingId, error };
}

/** Arrivals awaiting a PT + PTs in progress, with the "Make PT file" action.
 *  Lives on the PT File Operation → PT File Making tab (non-brand authoring). */
export function InboundQueueCard({ queue }: { queue: QueueT }) {
  const { makePt, makingId, error } = useMakePt();
  if (queue.counts.awaiting_pt === 0 && queue.counts.pt_in_progress === 0) return null;
  return (
    <div className="section-card card" data-testid="inbound-queue-card">
      <p className="eyebrow">Warehouse work queue</p>
      <h3 className="h3" style={{ marginBottom: 4 }}>
        {queue.counts.awaiting_pt > 0
          ? `${queue.counts.awaiting_pt} arrival(s) awaiting a PT file`
          : "All arrivals have a PT in progress"}
      </h3>
      <p className="lead" style={{ fontSize: 13, marginBottom: 12 }}>
        Goods are sellable only after their PT posts at Patna — start the PT as soon as the goods are counted.
      </p>
      {error && <div className="warn-note" data-testid="queue-make-pt-error">{error}</div>}
      {queue.awaiting_pt.length > 0 && (
        <div className="card-grid" data-testid="queue-awaiting-grid">
          {queue.awaiting_pt.map((g) => (
            <div key={g.id} className="card bk-card" data-testid={`queue-grn-${g.number}`}>
              <div className="bk-card-top">
                <Link to={`/inbound/${g.id}`} className="bk-num mono">{g.number}</Link>
                <span className="chip chip-amber status-pill">{g.received_total} pcs</span>
              </div>
              <div className="bk-brand">{g.vendor_name || "Direct receipt"}</div>
              <div className="bk-meta">
                {g.store_code} · {fmtDate(g.created_at)}
                {g.invoice_number ? ` · inv ${g.invoice_number}` : ""}
              </div>
              <button
                type="button"
                className="btn btn-cta btn-sm"
                style={{ marginTop: 10 }}
                disabled={makingId === g.id}
                onClick={() => makePt(g.id)}
                data-testid={`queue-make-pt-${g.id}`}
              >
                <FileSpreadsheet size={14} /> {makingId === g.id ? "Making…" : "Make PT file"}
              </button>
            </div>
          ))}
        </div>
      )}
      {queue.pt_in_progress.length > 0 && (
        <div style={{ marginTop: 14 }} data-testid="queue-in-progress">
          <p className="eyebrow">PTs in progress</p>
          {queue.pt_in_progress.map((p) => (
            <div key={p.id} style={{ display: "flex", gap: 10, alignItems: "center", padding: "6px 0" }}>
              <ClipboardList size={14} style={{ color: "var(--rust)" }} />
              <Link to={`/documents/pt-mapper/${p.id}`} className="link-cell">
                <b>{p.original_filename}</b>
              </Link>
              {p.grn_number && <span className="mono" style={{ fontSize: 12.5 }}>{p.grn_number}</span>}
              <span className={`chip chip-${p.stage === "sent" ? "amber" : "blue"}`}>{p.stage_label}</span>
              {p.blank_cell_count > 0 && (
                <span className="chip chip-grey">{p.blank_cell_count} blank cells</span>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
