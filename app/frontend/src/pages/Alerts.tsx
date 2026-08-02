// Home's Alerts surface (#77, #84 story 9) — one feed for problems that find
// you rather than the other way round. Two kinds today, sharing one screen:
// stock stuck in transit, and a brand's return window closing at 30/15/7 days
// left. A later kind (dead stock, another deadline) is another row shape here,
// never a new screen — the acceptance criterion #77 itself draws.
//
// Read-only: nobody approves or rejects an alert. It clears itself the run its
// condition stops being true (the daily job, `alerts.checks`).
import { AlertTriangle, Bell } from "lucide-react";

import { useList } from "../lib/hooks";
import { PageHeader } from "../components/PageHeader";
import {
  AlertTitle,
  alertWhere,
  daysLeftLabel,
  daysLeftTone,
  fmtAlertWhen,
  type AlertT,
} from "../components/alert";

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
              {data.map((a) => (
                <tr key={a.id} data-testid={`alert-row-${a.id}`}>
                  <td>
                    <p className="eyebrow">
                      <AlertTriangle size={13} /> {a.kind_label}
                    </p>
                    <AlertTitle alert={a} />
                  </td>
                  <td>{alertWhere(a)}</td>
                  <td>
                    <span className={`chip chip-${daysLeftTone(a.days_left)}`}>
                      {daysLeftLabel(a.days_left)}
                    </span>
                  </td>
                  <td style={{ whiteSpace: "nowrap", color: "var(--muted)", fontSize: 12 }}>
                    {fmtAlertWhen(a.created_at)}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

export default AlertsPage;
