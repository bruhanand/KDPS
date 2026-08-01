// Alerts and Approvals: two buttons, each with its own count and its own
// popup, each with history behind its live list (#226, reshaped 1 Aug 2026).
//
// They began as one bell with one combined count, which could not say which of
// the two feeds wanted you - and opening it to read approvals put the alerts
// feed on screen too, entangling "I read my approvals" with "I read my
// alerts". Split, each button owns its feed, its count and its popup, and
// opening one cannot touch the other's state: `ApprovalsButton` simply has no
// read-stamp to call.
//
// Two things the popups deliberately do *not* do:
//
// * **They do not decide.** A row links into `/approvals`, where the decision
//   sits beside its step trail. A popup that approved things would be a second
//   place maker-checker happens, and the trail would not be on screen.
// * **They do not replace the dashboard cards.** The buttons are a second path
//   to the same two places (grill s3), so Home is untouched.
import { useCallback, useEffect, useRef, useState } from "react";
import { Link, useLocation } from "react-router-dom";
import { AlertTriangle, Bell, ChevronDown, ChevronRight, History, Inbox } from "lucide-react";
import type { LucideIcon } from "lucide-react";

import { api } from "../lib/api";
import { Money } from "../lib/format";
import { fmtApprovalWhenShort, type ApprovalT } from "../components/approval";
import {
  alertWhere,
  daysLeftLabel,
  daysLeftTone,
  fmtAlertWhen,
  type AlertT,
} from "../components/alert";
import {
  DEFAULT_RANGE,
  RANGE_KEYS,
  RANGE_LABELS,
  badgeLabel,
  dayHeading,
  groupResolvedByDay,
  sinceFor,
  unreadAlerts,
  type RangeKey,
} from "./bellModel";
import { useMobileNavExclusion } from "./MobileNavContext";

/** Anyone who decides an approval says so here, so the bell can recount.
 *
 *  A DOM event rather than a store: the bell and the inbox are the only two
 *  things that care, they are never mounted together outside the shell, and one
 *  line beats a context for a fact this small. */
export const APPROVALS_CHANGED = "kdps:approvals-changed";

export function announceApprovalsChanged() {
  window.dispatchEvent(new Event(APPROVALS_CHANGED));
}

/** What a fetch said. `null` on either feed means the request failed and the
 *  popup shows a quiet line rather than an empty list, which would read as "all
 *  clear" - the most dangerous thing an alerts panel can say wrongly. */
type Feed<T> = T[] | null;

// ---------------------------------------------------------------------------
// History, shared by both feeds
// ---------------------------------------------------------------------------

function RangePicker({ value, onChange }: { value: RangeKey; onChange: (r: RangeKey) => void }) {
  return (
    <div className="bell-ranges" role="group" aria-label="History range">
      {RANGE_KEYS.map((key) => (
        <button
          key={key}
          type="button"
          className={`bell-range ${value === key ? "active" : ""}`}
          onClick={() => onChange(key)}
          aria-pressed={value === key}
          data-testid={`bell-range-${key}`}
        >
          {RANGE_LABELS[key]}
        </button>
      ))}
    </div>
  );
}

/**
 * The expandable History block: a disclosure button, a range, and a body.
 *
 * Fetch-on-expand, never on open: the popup has to appear instantly, and most
 * openings are somebody glancing at the live list and closing it again. The
 * fetcher is re-run whenever the range changes, and its answer replaces the
 * previous one rather than merging with it.
 */
function HistorySection<T>({
  testId,
  fetcher,
  children,
}: {
  testId: string;
  fetcher: (since: string) => Promise<T[]>;
  children: (rows: T[]) => React.ReactNode;
}) {
  const [open, setOpen] = useState(false);
  const [range, setRange] = useState<RangeKey>(DEFAULT_RANGE);
  const [rows, setRows] = useState<Feed<T>>([]);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    if (!open) return;
    let live = true;
    setLoading(true);
    fetcher(sinceFor(range))
      .then((r) => live && setRows(r))
      .catch(() => live && setRows(null))
      .finally(() => live && setLoading(false));
    return () => {
      live = false;
    };
  }, [open, range, fetcher]);

  return (
    <div className="bell-history">
      <button
        type="button"
        className="bell-history-toggle"
        onClick={() => setOpen((o) => !o)}
        aria-expanded={open}
        data-testid={`${testId}-toggle`}
      >
        {open ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
        <History size={14} /> History
      </button>
      {open && (
        <div data-testid={testId}>
          <RangePicker value={range} onChange={setRange} />
          {loading ? (
            <p className="bell-quiet">Loading…</p>
          ) : rows === null ? (
            <p className="bell-quiet" data-testid={`${testId}-error`}>
              Could not load history just now.
            </p>
          ) : rows.length === 0 ? (
            <p className="bell-quiet">Nothing in this period.</p>
          ) : (
            children(rows)
          )}
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// The two feeds
// ---------------------------------------------------------------------------

function AlertsFeed({ alerts, onNavigate }: { alerts: Feed<AlertT>; onNavigate: () => void }) {
  const fetchHistory = useCallback(
    (since: string) =>
      api.get("/alerts/history", { params: { since } }).then((r) => r.data as AlertT[]),
    [],
  );

  return (
    <>
      {alerts === null ? (
        <p className="bell-quiet" data-testid="bell-alerts-error">
          Could not load alerts just now. Open the{" "}
          <Link to="/alerts" onClick={onNavigate}>
            alerts screen
          </Link>
          .
        </p>
      ) : alerts.length === 0 ? (
        <p className="bell-quiet" data-testid="bell-alerts-empty">
          Nothing is raising its hand right now.
        </p>
      ) : (
        <ul className="bell-list" data-testid="bell-alerts-list">
          {alerts.map((a) => (
            <li key={a.id} className="bell-row" data-testid={`bell-alert-${a.id}`}>
              <p className="bell-row-head">
                <AlertTriangle size={12} /> {a.kind_label}
                <span className={`chip chip-${daysLeftTone(a.days_left)}`}>
                  {daysLeftLabel(a.days_left)}
                </span>
              </p>
              {/* Into the full screen, not the document behind the alert: the
                  popup is a reader and a launcher (grill s2), and `/alerts` is
                  where the row sits beside its deadline and its own link on. */}
              <p className="bell-row-title">
                <Link to="/alerts" className="link-cell" onClick={onNavigate}>
                  {a.title}
                </Link>
              </p>
              <p className="bell-row-meta">
                {alertWhere(a)} · {fmtAlertWhen(a.created_at)}
              </p>
            </li>
          ))}
        </ul>
      )}
      <Link to="/alerts" className="bell-all" onClick={onNavigate} data-testid="bell-alerts-all">
        Open the alerts screen
      </Link>
      <HistorySection testId="bell-alerts-history" fetcher={fetchHistory}>
        {(rows: AlertT[]) => (
          <ul className="bell-list">
            {groupResolvedByDay(rows).map((group) => (
              <li key={group.day} className="bell-day">
                <p className="bell-day-head">{dayHeading(group.day)}</p>
                {group.alerts.map((a) => (
                  <div key={a.id} className="bell-row" data-testid={`bell-alert-past-${a.id}`}>
                    <p className="bell-row-title">{a.title}</p>
                    <p className="bell-row-meta">
                      {a.kind_label} · {alertWhere(a)}
                    </p>
                  </div>
                ))}
              </li>
            ))}
          </ul>
        )}
      </HistorySection>
    </>
  );
}

function ApprovalsFeed({
  approvals,
  onNavigate,
}: {
  approvals: Feed<ApprovalT>;
  onNavigate: () => void;
}) {
  const fetchHistory = useCallback(
    (since: string) =>
      api
        .get("/approvals", { params: { decided: "1", since } })
        .then((r) => r.data as ApprovalT[]),
    [],
  );

  return (
    <>
      {approvals === null ? (
        <p className="bell-quiet" data-testid="bell-approvals-error">
          Could not load approvals just now. Open the{" "}
          <Link to="/approvals" onClick={onNavigate}>
            approvals inbox
          </Link>
          .
        </p>
      ) : approvals.length === 0 ? (
        <p className="bell-quiet" data-testid="bell-approvals-empty">
          Nothing is waiting for you.
        </p>
      ) : (
        <ul className="bell-list" data-testid="bell-approvals-list">
          {approvals.map((a) => (
            <li key={a.id} className="bell-row" data-testid={`bell-approval-${a.id}`}>
              <p className="bell-row-head">
                <Inbox size={12} /> {a.kind_label}
                {!!a.value_paise && (
                  <span className="bell-value">
                    <Money paise={a.value_paise} />
                  </span>
                )}
              </p>
              {/* Into the inbox, never the document and never a decision here:
                  the step trail and the reason box live on `/approvals`, and a
                  decision taken without them is the thing maker-checker exists
                  to prevent (grill s2, design assumption 5). */}
              <p className="bell-row-title">
                <Link to="/approvals" className="link-cell mono" onClick={onNavigate}>
                  {a.title}
                </Link>
              </p>
              <p className="bell-row-meta">
                {a.requested_by_name} · {fmtApprovalWhenShort(a.requested_at)}
              </p>
            </li>
          ))}
        </ul>
      )}
      <Link
        to="/approvals"
        className="bell-all"
        onClick={onNavigate}
        data-testid="bell-approvals-all"
      >
        Open the approvals inbox
      </Link>
      <HistorySection testId="bell-approvals-history" fetcher={fetchHistory}>
        {(rows: ApprovalT[]) => (
          <ul className="bell-list">
            {rows.map((a) => (
              <li key={a.id} className="bell-row" data-testid={`bell-approval-past-${a.id}`}>
                <p className="bell-row-title">{a.title}</p>
                <p className="bell-row-meta">
                  {a.status === "approved" ? "Approved" : "Rejected"} by {a.decided_by_name || "—"}
                  {a.decided_at ? ` · ${fmtApprovalWhenShort(a.decided_at)}` : ""}
                  {a.reason ? ` · ${a.reason}` : ""}
                </p>
              </li>
            ))}
          </ul>
        )}
      </HistorySection>
    </>
  );
}

// ---------------------------------------------------------------------------
// The two buttons
// ---------------------------------------------------------------------------

/** The shell both buttons share: an icon button wearing its count, and a popup
 *  with a title row over the feed. The popup closes on outside click and Esc,
 *  the two ways every other popup in this shell closes - and because each
 *  button owns its own instance, opening one cannot close (or stamp) the
 *  other. */
function NoticeButton({
  icon: Icon,
  title,
  label,
  count,
  testId,
  onOpen,
  children,
}: {
  icon: LucideIcon;
  title: string;
  /** The button's spoken line - title and tooltip - which says the count. */
  label: string;
  count: number;
  testId: string;
  /** Called when the popup opens, never when it closes. */
  onOpen?: () => void;
  children: (onNavigate: () => void) => React.ReactNode;
}) {
  const [open, setOpen] = useState(false);
  const wrap = useRef<HTMLDivElement>(null);
  useMobileNavExclusion(open, setOpen);

  function toggle() {
    if (open) {
      setOpen(false);
      return;
    }
    setOpen(true);
    onOpen?.();
  }

  useEffect(() => {
    if (!open) return;
    const off = new AbortController();
    const { signal } = off;
    document.addEventListener(
      "pointerdown",
      (e) => {
        if (!wrap.current?.contains(e.target as Node)) setOpen(false);
      },
      { signal },
    );
    document.addEventListener(
      "keydown",
      (e) => {
        if (e.key === "Escape") setOpen(false);
      },
      { signal },
    );
    return () => off.abort();
  }, [open]);

  const badge = badgeLabel(count);

  return (
    <div className="bell-wrap" ref={wrap}>
      <button
        type="button"
        className="icon-btn"
        onClick={toggle}
        aria-label={label}
        aria-expanded={open}
        title={label}
        data-testid={testId}
      >
        <Icon size={18} />
        {badge && (
          <span className="bell-count" data-testid={`${testId}-count`}>
            {badge}
          </span>
        )}
      </button>

      {open && (
        <div className="bell-popup" data-testid={`${testId}-popup`}>
          <div className="bell-title">
            {title}
            {badge && <span className="bell-title-count">{badge}</span>}
          </div>
          <div className="bell-body">{children(() => setOpen(false))}</div>
        </div>
      )}
    </div>
  );
}

export function AlertsButton() {
  const [alerts, setAlerts] = useState<Feed<AlertT>>([]);
  // One plain stamp, `null` meaning "no stamp" - which is what the contract
  // says an absent row means, and so also the honest answer while the read is
  // in flight or after it fails. It errs towards showing the count: a button
  // that silently says "nothing waiting" because a request failed is the one
  // wrong answer an alerting surface must not give.
  const [seenAt, setSeenAt] = useState<string | null>(null);
  const { pathname } = useLocation();

  const loadAlerts = useCallback(
    () =>
      api
        .get("/alerts")
        .then((r) => {
          const rows = (r.data ?? []) as AlertT[];
          setAlerts(rows);
          return rows;
        })
        .catch(() => {
          setAlerts(null);
          return null;
        }),
    [],
  );

  // Re-counted on every navigation, not once per session.
  useEffect(() => {
    void loadAlerts();
    api
      .get("/alerts/seen")
      .then((r) => setSeenAt(r.data?.seen_at ?? null))
      .catch(() => setSeenAt(null));
  }, [loadAlerts, pathname]);

  /**
   * Opening the popup is what "reading" means, so it stamps - but only over a
   * list that was actually just fetched.
   *
   * The feed otherwise refreshes on navigation, so a popup opened after an
   * hour on one screen would stamp "read as of now" across alerts raised in
   * that hour and never shown. `unreadAlerts` is strictly-after, so those
   * would never surface again: exactly the wrong direction for an alerting
   * surface. Hence refetch first, and do not stamp at all if the refetch
   * failed.
   *
   * The badge zeroes locally the moment the popup opens rather than waiting
   * for the round trip, and goes back to what it was if the stamp did not
   * land - clearing a count the server never recorded would be the same
   * silence.
   */
  const openAndStamp = useCallback(() => {
    const previous = seenAt;
    setSeenAt(new Date().toISOString());
    void loadAlerts().then((rows) => {
      if (rows === null) {
        setSeenAt(previous);
        return;
      }
      api
        .post("/alerts/seen")
        .then((r) => setSeenAt(r.data?.seen_at ?? new Date().toISOString()))
        .catch(() => setSeenAt(previous));
    });
  }, [loadAlerts, seenAt]);

  const unread = unreadAlerts(alerts ?? [], seenAt);
  const label = unread
    ? `${unread} unread alert${unread === 1 ? "" : "s"}`
    : "Alerts - nothing unread";

  return (
    <NoticeButton
      icon={Bell}
      title="Alerts"
      label={label}
      count={unread}
      testId="alerts-button"
      onOpen={openAndStamp}
    >
      {(onNavigate) => <AlertsFeed alerts={alerts} onNavigate={onNavigate} />}
    </NoticeButton>
  );
}

export function ApprovalsButton() {
  const [approvals, setApprovals] = useState<Feed<ApprovalT>>([]);
  const { pathname } = useLocation();

  // Re-counted on every navigation *and* whenever a decision is made, not once
  // per session: clearing the last item used to leave the old bell insisting
  // one document was still waiting, right beside a page saying nothing was.
  const refresh = useCallback(() => {
    api
      .get("/approvals/inbox")
      .then((r) => setApprovals(r.data ?? []))
      .catch(() => setApprovals(null));
  }, []);

  useEffect(() => {
    refresh();
    window.addEventListener(APPROVALS_CHANGED, refresh);
    return () => window.removeEventListener(APPROVALS_CHANGED, refresh);
  }, [refresh, pathname]);

  const waiting = approvals?.length ?? 0;
  const label = waiting
    ? `${waiting} approval${waiting === 1 ? "" : "s"} waiting`
    : "Approvals - nothing waiting";

  // No `onOpen` and no read-stamp anywhere in this component, structurally:
  // reading your approvals says nothing about whether you have read your
  // alerts, and the one endpoint that stamps is called only by AlertsButton.
  return (
    <NoticeButton
      icon={Inbox}
      title="Approvals"
      label={label}
      count={waiting}
      testId="approvals-button"
    >
      {(onNavigate) => <ApprovalsFeed approvals={approvals} onNavigate={onNavigate} />}
    </NoticeButton>
  );
}
