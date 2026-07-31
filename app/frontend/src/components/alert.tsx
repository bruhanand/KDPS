// The alert bits shared between the Alerts screen and the bell (#77, #226).
// The shape mirrors `AlertReadSerializer`; the helpers are the ones both
// surfaces have to agree on - a deadline that reads "3 days left" in the popup
// and "overdue" on the screen would be two different answers to one question.
import { Link } from "react-router-dom";
import { Link2 } from "lucide-react";

export interface AlertT {
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
  /** When the condition stopped being true. Null on everything the open feed
   *  carries - history is the only place it is ever set (#226). */
  resolved_at: string | null;
}

// kind → the document behind it, when there is one - the same idea as
// `approvalDocPath`, one entry smaller: a return-window alert names a holding,
// not a document, so it has no page of its own to open.
const KIND_ROUTE: Record<string, string> = {
  in_transit_aging: "/transfer",
};

export function alertDocPath(a: Pick<AlertT, "kind" | "object_id">): string | null {
  const base = KIND_ROUTE[a.kind];
  if (!base || a.object_id === null) return null;
  return `${base}/${a.object_id}`;
}

export function fmtAlertWhen(iso: string): string {
  return new Date(iso).toLocaleString("en-IN", {
    day: "numeric",
    month: "short",
    hour: "numeric",
    minute: "2-digit",
  });
}

/** Red once the deadline is blown past, amber inside the last week, else the
 *  screen doesn't need to shout - the same "amber inside the last fortnight"
 *  idea the return-to-brand screen already uses. */
export function daysLeftTone(days: number | null): string {
  if (days === null) return "grey";
  if (days < 0) return "red";
  if (days <= 7) return "amber";
  return "grey";
}

export function daysLeftLabel(days: number | null): string {
  if (days === null) return "—";
  if (days < 0) return `${Math.abs(days)} day(s) overdue`;
  if (days === 0) return "Due today";
  return `${days} day(s) left`;
}

/** Where the alert is, said the way both surfaces say it. */
export function alertWhere(a: Pick<AlertT, "store_code" | "store_name" | "brand">): string {
  return a.store_name ? `${a.store_code} · ${a.store_name}` : a.brand || "—";
}

/** The alert's own one-liner, as a link where there is a document to open. */
export function AlertTitle({ alert, onNavigate }: { alert: AlertT; onNavigate?: () => void }) {
  const path = alertDocPath(alert);
  if (!path) return <>{alert.title}</>;
  return (
    <Link to={path} className="link-cell" onClick={onNavigate} data-testid={`alert-link-${alert.id}`}>
      {alert.title}
      <Link2 size={12} style={{ marginLeft: 4 }} />
    </Link>
  );
}
