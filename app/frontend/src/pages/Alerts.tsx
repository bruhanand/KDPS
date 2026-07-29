// Home's Alerts surface (#77, #84 story 9) — one feed for problems that find
// you rather than the other way round. Two kinds today, sharing one screen:
// stock stuck in transit, and a brand's return window closing at 30/15/7 days
// left. A later kind (dead stock, another deadline) is another row shape here,
// never a new screen — the acceptance criterion #77 itself draws.
//
// Read-only: nobody approves or rejects an alert. It clears itself the run its
// condition stops being true (the daily job, `alerts.checks`).
import { AlertTriangle, Bell, Link2 } from "lucide-react";
import { Link } from "react-router-dom";

import { useList } from "../lib/hooks";
import { PageHeader } from "../components/PageHeader";

interface AlertT {
  id: number;
  kind: string;
  kind_label: string;
  title: string;
  object_id: number | null;
  store: number | null;
  store_code: string;
  store_name: string;
  brand: string;
  due_date: string | null;
  days_left: number | null;
  threshold_days: number | null;
  status: string;
  created_at: string;
}

// kind → the document behind it, when there is one — the same idea as
// `approvalDocPath`, one entry smaller: a return-window alert names a holding,
// not a document, so it has no page of its own to open.
const KIND_ROUTE: Record<string, string> = {
  in_transit_aging: "/transfer",
};

function alertDocPath(a: Pick<AlertT, "kind" | "object_id">): string | null {
  const base = KIND_ROUTE[a.kind];
  if (!base || a.object_id === null) return null;
  return `${base}/${a.object_id}`;
}

function fmtWhen(iso: string): string {
  return new Date(iso).toLocaleString("en-IN", {
    day: "numeric",
    month: "short",
    hour: "numeric",
    minute: "2-digit",
  });
}

/** Red once the deadline is blown past, amber inside the last week, else the
 *  screen doesn't need to shout — the same "amber inside the last fortnight"
 *  idea the return-to-brand screen already uses. */
function daysLeftTone(days: number | null): string {
  if (days === null) return "grey";
  if (days < 0) return "red";
  if (days <= 7) return "amber";
  return "grey";
}

function daysLeftLabel(days: number | null): string {
  if (days === null) return "—";
  if (days < 0) return `${Math.abs(days)} day(s) overdue`;
  if (days === 0) return "Due today";
  return `${days} day(s) left`;
}

export function AlertsPage() {
  const { data, loading } = useList<AlertT>("/alerts");

  return (
    <div className="page-pad">
      <PageHeader lead="Everything that needs attention today — stock stuck in transit, and return windows closing. This list clears itself once a condition stops being true; nothing here needs a decision." />

      {loading ? (
        <p className="lead">Loading…</p>
      ) : data.length === 0 ? (
        <div className="card section-card" data-testid="alerts-empty">
          <p className="eyebrow">
            <Bell size={15} /> All clear
          </p>
          Nothing is raising its hand right now.
        </div>
      ) : (
        <div className="table-wrap">
          <table className="data" data-testid="alerts-table">
            <thead>
              <tr>
                <th>What</th>
                <th>Where</th>
                <th>Deadline</th>
                <th>Raised</th>
              </tr>
            </thead>
            <tbody>
              {data.map((a) => {
                const path = alertDocPath(a);
                return (
                  <tr key={a.id} data-testid={`alert-row-${a.id}`}>
                    <td>
                      <p className="eyebrow">
                        <AlertTriangle size={13} /> {a.kind_label}
                      </p>
                      {path ? (
                        <Link to={path} className="link-cell" data-testid={`alert-link-${a.id}`}>
                          {a.title}
                          <Link2 size={12} style={{ marginLeft: 4 }} />
                        </Link>
                      ) : (
                        a.title
                      )}
                    </td>
                    <td>
                      {a.store_name ? `${a.store_code} · ${a.store_name}` : a.brand || "—"}
                    </td>
                    <td>
                      <span className={`chip chip-${daysLeftTone(a.days_left)}`}>
                        {daysLeftLabel(a.days_left)}
                      </span>
                    </td>
                    <td style={{ whiteSpace: "nowrap", color: "var(--muted)", fontSize: 12 }}>
                      {fmtWhen(a.created_at)}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

export default AlertsPage;
