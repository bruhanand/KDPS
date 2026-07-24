// The one approvals inbox for the whole system (#70).
//
// "The senior person opens one screen each morning and clears it" — so this is
// deliberately a single flat list across every document family, not a tab per
// module. Everything the row needs (what, where, how much, who asked, when) is
// snapshotted on the approval itself, so the list renders in one request.
//
// Nothing here decides anything: the server owns who may approve what, refuses
// self-approval, and demands a reason on reject. This screen only asks.
import { useState } from "react";
import type { CSSProperties } from "react";
import { Link } from "react-router-dom";
import { CheckCircle2, Inbox, ShieldCheck, XCircle } from "lucide-react";

import { api, apiErrorMessage } from "../lib/api";
import { useList } from "../lib/hooks";
import { Money } from "../lib/format";
import {
  approvalDocPath,
  fmtApprovalWhenShort,
  type ApprovalT,
} from "../components/approval";
import "./Booking.css";

// ---------------------------------------------------------------------------
// The inbox
// ---------------------------------------------------------------------------

/** Keeps Approve/Reject pinned to the right edge of a horizontally scrolling
 *  table, and stops the buttons wrapping onto two lines. */
const ACTIONS_CELL: CSSProperties = {
  position: "sticky",
  right: 0,
  whiteSpace: "nowrap",
  background: "var(--surface)",
  borderLeft: "1px solid var(--hairline)",
};

export function ApprovalsPage() {
  const { data, loading, reload } = useList<ApprovalT>("/approvals/inbox");
  const [rejecting, setRejecting] = useState<number | null>(null);
  const [reason, setReason] = useState("");
  const [busy, setBusy] = useState<number | null>(null);
  const [error, setError] = useState("");

  async function decide(id: number, action: "approve" | "reject", why = "") {
    setError("");
    setBusy(id);
    try {
      await api.post(`/approvals/${id}/decide`, { action, reason: why });
      setRejecting(null);
      setReason("");
      reload();
    } catch (e) {
      setError(apiErrorMessage(e));
    } finally {
      setBusy(null);
    }
  }

  return (
    <div className="page-pad">
      <div className="toolbar">
        <div>
          <p className="eyebrow">Controls · Approvals</p>
          <h1 className="h1 h2-rust">Approvals inbox</h1>
          <p className="lead">
            Everything waiting for your decision. You will never see your own requests here —
            no document is approved by the person who made it.
          </p>
        </div>
      </div>

      {error && (
        <div className="login-error" style={{ maxWidth: 520 }} data-testid="approvals-error">
          {error}
        </div>
      )}

      {loading ? (
        <p className="lead">Loading…</p>
      ) : data.length === 0 ? (
        <div className="card section-card" data-testid="approvals-empty">
          <p className="eyebrow">
            <Inbox size={15} /> All clear
          </p>
          Nothing is waiting for you.
        </div>
      ) : (
        <div className="table-wrap">
          <table className="data" data-testid="approvals-table">
            <thead>
              {/* Deliberately few columns: this screen is cleared on a phone or a
                  half-width pane as often as on a desk monitor, and the store is
                  already the first thing in the document title. */}
              <tr>
                <th>What</th>
                <th>Document</th>
                <th className="num">Value</th>
                <th>Asked by</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {data.map((a) => {
                const path = approvalDocPath(a);
                return (
                  <tr key={a.id} data-testid={`approval-row-${a.id}`}>
                    <td>
                      <b>{a.kind_label}</b>
                    </td>
                    <td>
                      {path ? (
                        <Link to={path} className="link-cell mono" data-testid={`approval-link-${a.id}`}>
                          {a.title}
                        </Link>
                      ) : (
                        <span className="mono">{a.title}</span>
                      )}
                    </td>
                    <td className="num">{a.value_paise ? <Money paise={a.value_paise} /> : "—"}</td>
                    <td style={{ whiteSpace: "nowrap" }}>
                      {a.requested_by_name}
                      <br />
                      <span style={{ color: "var(--muted)", fontSize: 12 }}>
                        {fmtApprovalWhenShort(a.requested_at)}
                      </span>
                    </td>
                    {/* The decision is the point of this screen, so it must never
                        be the thing that scrolls out of sight on a narrow pane:
                        the actions cell sticks to the right edge while the rest
                        of the row scrolls under it. */}
                    <td style={ACTIONS_CELL}>
                      {rejecting === a.id ? (
                        <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
                          <input
                            className="input"
                            autoFocus
                            placeholder="Reason (required)"
                            value={reason}
                            onChange={(e) => setReason(e.target.value)}
                            // A table cell sizes to its content; without a floor
                            // the reason box collapses to a sliver you can't type in.
                            style={{ minWidth: 240 }}
                            data-testid={`reject-reason-${a.id}`}
                          />
                          <button
                            type="button"
                            className="btn"
                            disabled={!reason.trim() || busy === a.id}
                            onClick={() => decide(a.id, "reject", reason)}
                            data-testid={`confirm-reject-${a.id}`}
                          >
                            Confirm reject
                          </button>
                          <button
                            type="button"
                            className="btn"
                            onClick={() => {
                              setRejecting(null);
                              setReason("");
                            }}
                          >
                            Cancel
                          </button>
                        </div>
                      ) : (
                        <div style={{ display: "flex", gap: 8 }}>
                          <button
                            type="button"
                            className="btn btn-cta"
                            disabled={busy === a.id}
                            onClick={() => decide(a.id, "approve")}
                            data-testid={`approve-${a.id}`}
                          >
                            <CheckCircle2 size={15} /> Approve
                          </button>
                          <button
                            type="button"
                            className="btn"
                            disabled={busy === a.id}
                            onClick={() => {
                              setRejecting(a.id);
                              setReason("");
                            }}
                            data-testid={`reject-${a.id}`}
                          >
                            <XCircle size={15} /> Reject
                          </button>
                        </div>
                      )}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}

      <p className="lead" style={{ marginTop: 18, opacity: 0.75 }}>
        <ShieldCheck size={14} /> Every decision is recorded on the document — made by, approved
        by, and when.
      </p>
    </div>
  );
}

export default ApprovalsPage;
