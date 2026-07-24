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
import { Link } from "react-router-dom";
import { CheckCircle2, Inbox, ShieldCheck, XCircle } from "lucide-react";

import { api, apiErrorMessage } from "../lib/api";
import { useList } from "../lib/hooks";
import { Money } from "../lib/format";
import "./Booking.css";

export interface ApprovalT {
  id: number;
  kind: string;
  kind_label: string;
  title: string;
  object_id: number;
  store: number | null;
  store_code: string;
  store_name: string;
  value_paise: number;
  status: "pending" | "approved" | "rejected";
  requested_by: number;
  requested_by_name: string;
  requested_at: string;
  decided_by: number | null;
  decided_by_name: string;
  decided_at: string | null;
  reason: string;
}

// kind → the document's own page. The server never knows about client routes.
const KIND_ROUTE: Record<string, string> = {
  writeoff: "/outbound/writeoffs",
  vflip: "/outbound/vflips",
  adjustment: "/outbound/adjustments",
};

export function approvalDocPath(a: Pick<ApprovalT, "kind" | "object_id">): string | null {
  const base = KIND_ROUTE[a.kind];
  return base ? `${base}/${a.object_id}` : null;
}

function fmtWhen(iso: string): string {
  return new Date(iso).toLocaleString("en-IN", {
    day: "numeric",
    month: "short",
    year: "numeric",
    hour: "numeric",
    minute: "2-digit",
  });
}

const STATUS_TONE: Record<string, string> = {
  pending: "amber",
  approved: "green",
  rejected: "red",
};

export function ApprovalPill({ status }: { status: string }) {
  return (
    <span className={`chip chip-${STATUS_TONE[status] ?? "grey"} status-pill`}>
      {status === "pending" ? "Waiting" : status === "approved" ? "Approved" : "Rejected"}
    </span>
  );
}

/** The made-by / approved-by / when block every wired document shows, forever. */
export function ApprovalTrail({
  createdByName,
  approval,
}: {
  createdByName: string;
  approval: ApprovalT | null;
}) {
  return (
    <div className="card section-card" data-testid="approval-trail">
      <p className="eyebrow">Maker · Checker</p>
      <p className="lead" style={{ marginTop: 6 }}>
        Made by <b>{createdByName || "—"}</b>
        {approval ? ` on ${fmtWhen(approval.requested_at)}` : ""}
      </p>
      {approval ? (
        <p className="lead">
          {approval.status === "pending" ? (
            <>Waiting for approval by a second person.</>
          ) : (
            <>
              {approval.status === "approved" ? "Approved" : "Rejected"} by{" "}
              <b>{approval.decided_by_name || "—"}</b>
              {approval.decided_at ? ` on ${fmtWhen(approval.decided_at)}` : ""}
              {approval.reason ? ` — ${approval.reason}` : ""}
            </>
          )}
        </p>
      ) : (
        <p className="lead">No approval on record.</p>
      )}
      <ApprovalPill status={approval?.status ?? "pending"} />
    </div>
  );
}

// ---------------------------------------------------------------------------
// The inbox
// ---------------------------------------------------------------------------

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
              <tr>
                <th>What</th>
                <th>Document</th>
                <th>Store</th>
                <th className="num">Value</th>
                <th>Asked by</th>
                <th>When</th>
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
                    <td>
                      <b className="mono">{a.store_code || "—"}</b>
                    </td>
                    <td className="num">{a.value_paise ? <Money paise={a.value_paise} /> : "—"}</td>
                    <td>{a.requested_by_name}</td>
                    <td>{fmtWhen(a.requested_at)}</td>
                    <td>
                      {rejecting === a.id ? (
                        <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
                          <input
                            className="input"
                            autoFocus
                            placeholder="Reason (required)"
                            value={reason}
                            onChange={(e) => setReason(e.target.value)}
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
