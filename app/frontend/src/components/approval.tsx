// The approval bits shared between the inbox screen and every document that
// needs a second person (#70). The shape mirrors ApprovalReadSerializer.
import { Link } from "react-router-dom";

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

export function fmtApprovalWhen(iso: string): string {
  return new Date(iso).toLocaleString("en-IN", {
    day: "numeric",
    month: "short",
    year: "numeric",
    hour: "numeric",
    minute: "2-digit",
  });
}

/** Same moment, minus the year — the inbox only ever holds live requests, and
 *  the full form wraps to three lines in a table cell on a narrow pane. */
export function fmtApprovalWhenShort(iso: string): string {
  return new Date(iso).toLocaleString("en-IN", {
    day: "numeric",
    month: "short",
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
        {approval ? ` on ${fmtApprovalWhen(approval.requested_at)}` : ""}
      </p>
      {approval ? (
        <p className="lead">
          {approval.status === "pending" ? (
            <>
              Waiting for approval by a second person — clear it from the{" "}
              <Link to="/approvals">approvals inbox</Link>.
            </>
          ) : (
            <>
              {approval.status === "approved" ? "Approved" : "Rejected"} by{" "}
              <b>{approval.decided_by_name || "—"}</b>
              {approval.decided_at ? ` on ${fmtApprovalWhen(approval.decided_at)}` : ""}
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
