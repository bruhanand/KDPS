import { useState } from "react";
import { Link } from "react-router-dom";
import { AlertTriangle, ArrowLeft, CheckCircle2, Sparkles, ThumbsDown, ThumbsUp } from "lucide-react";

import { api, apiErrorMessage } from "../lib/api";
import { ListSearchBar } from "../components/SearchBox";
import { useList } from "../lib/hooks";
import "./PtMapper.css";

const DIM_LABEL: Record<string, string> = {
  color: "Colour", size: "Size", brand: "Brand", season: "Season", fit: "Fit", gender: "Gender",
};
const ORIGIN_TONE: Record<string, string> = {
  review: "blue", remember: "purple", mined: "green", llm: "grey",
};
const STATUS_TONE: Record<string, string> = {
  proposed: "amber", approved: "green", rejected: "grey", auto_rejected: "red",
};

interface ProposalT {
  id: number;
  dimension: string;
  source_key: string;
  target_value: string;
  brand: string;
  scope: string;
  origin: string;
  origin_label: string;
  status: string;
  status_label: string;
  evidence: { occurrences?: number; files?: number[]; brands?: string[] };
  validation: { ok?: boolean; conflicts?: { kind: string; detail: string }[] };
  proposed_by_name: string;
  created_at: string;
}

export function PtProposalsPage() {
  const [status, setStatus] = useState("proposed");
  const [q, setQ] = useState("");
  const { data: items, loading, reload } = useList<ProposalT>("/ptmapper/proposals", { status, q });

  return (
    <div className="page-pad">
      <Link to="/receive/pt" className="btn" style={{ marginBottom: 16 }}>
        <ArrowLeft size={15} /> PT Mapper
      </Link>
      <h1 className="h1 h2-rust" style={{ marginBottom: 4 }}>Learning proposals</h1>
      <p className="lead" style={{ marginBottom: 18, fontSize: 13.5 }}>
        Each card is a mapping the engine <b>learned</b> from human corrections. Approving it writes a
        durable rule so the same raw value maps itself next time — corrections trend to zero. Nothing
        goes live until a steward approves it here.
      </p>

      <div className="toolbar" style={{ marginBottom: 12 }}>
        <div className="upload-context-field" style={{ maxWidth: 220 }}>
          <label className="upload-context-label">Show</label>
          <select
            className="select"
            value={status}
            onChange={(e) => setStatus(e.target.value)}
            data-testid="proposals-status-filter"
          >
            <option value="proposed">Awaiting decision</option>
            <option value="approved">Approved</option>
            <option value="auto_rejected">Auto-rejected (conflicts)</option>
            <option value="rejected">Rejected</option>
            <option value="all">All</option>
          </select>
        </div>
      </div>

      <ListSearchBar
        value={q}
        onChange={setQ}
        placeholder="Search proposals — raw value, target, brand, status"
        label="Search learning proposals"
        testId="proposals-search"
        noun="proposal"
        count={items.length}
        loading={loading}
      />

      {loading ? (
        <p className="lead">Loading…</p>
      ) : items.length === 0 ? (
        <div className="ok-note" data-testid="proposals-empty">
          <CheckCircle2 size={14} />{" "}
          {q ? `No proposal matches “${q}”.` : "Nothing here — no proposals in this state."}
        </div>
      ) : (
        <div className="review-list" data-testid="proposals-list">
          {items.map((p) => (
            <ProposalCard key={p.id} p={p} showStatus={status === "all"} onDone={reload} />
          ))}
        </div>
      )}
    </div>
  );
}

function ProposalCard({ p, showStatus, onDone }: { p: ProposalT; showStatus: boolean; onDone: () => void }) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const ev = p.evidence || {};
  const conflicts = p.validation?.conflicts ?? [];

  async function decide(action: "approve" | "reject") {
    setBusy(true);
    setError("");
    try {
      await api.post(`/ptmapper/proposals/${p.id}/decide`, { action });
      onDone();
    } catch (e) {
      setError(apiErrorMessage(e));
      setBusy(false);
    }
  }

  const parts: string[] = [];
  if (ev.occurrences) parts.push(`${ev.occurrences} correction${ev.occurrences === 1 ? "" : "s"}`);
  if (ev.files?.length) parts.push(`${ev.files.length} file${ev.files.length === 1 ? "" : "s"}`);
  if (p.proposed_by_name) parts.push(`by ${p.proposed_by_name}`);

  return (
    <div className="card review-item" data-testid={`proposal-${p.id}`}>
      <div className="review-head">
        <span className="chip chip-blue">{DIM_LABEL[p.dimension] ?? p.dimension}</span>
        <span className="review-raw mono">{p.source_key} → {p.target_value}</span>
        <span className={`chip chip-${p.brand ? "navy" : "grey"}`} data-testid={`proposal-scope-${p.id}`}>{p.scope}</span>
        <span className={`chip chip-${ORIGIN_TONE[p.origin] ?? "grey"}`}>{p.origin_label}</span>
        {showStatus && <span className={`chip chip-${STATUS_TONE[p.status] ?? "grey"}`}>{p.status_label}</span>}
      </div>
      {parts.length > 0 && <div className="review-samples">{parts.join(" · ")}</div>}
      {conflicts.length > 0 && (
        <div className="warn-note" style={{ marginTop: 8 }} data-testid={`proposal-conflict-${p.id}`}>
          <AlertTriangle size={14} /> {conflicts.map((c) => c.detail).join(" · ")}
        </div>
      )}
      {p.status === "proposed" && (
        <div className="review-resolve" style={{ marginTop: 10 }}>
          <button className="btn btn-primary" disabled={busy} onClick={() => decide("approve")} data-testid={`proposal-approve-${p.id}`}>
            <ThumbsUp size={14} /> Approve
          </button>
          <button className="btn btn-sm" disabled={busy} onClick={() => decide("reject")} data-testid={`proposal-reject-${p.id}`}>
            <ThumbsDown size={14} /> Reject
          </button>
        </div>
      )}
      {error && <div className="warn-note" style={{ marginTop: 8 }}>{error}</div>}
    </div>
  );
}

export const ProposalsIcon = Sparkles;
