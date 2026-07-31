// The bell: two feeds, one popup, with history behind each (#226).
//
// It used to be a link to `/approvals` with a count of undecided documents on
// it. That left the other half of "things that want you" - the alerts feed -
// with no presence in the top bar at all, reachable only from a dashboard card
// somebody had to be standing on Home to see.
//
// So the bell now opens rather than navigates. Two tabs, Alerts first because
// it is the one nobody was watching, Approvals second because it already had a
// screen. Each tab shows its live list and, behind a button, its history.
//
// Two things it deliberately does *not* do:
//
// * **It does not decide.** A row links into `/approvals`, where the decision
//   sits beside its step trail. A popup that approved things would be a second
//   place maker-checker happens, and the trail would not be on screen.
// * **It does not replace the dashboard cards.** The bell is a second path to
//   the same two places (grill s3), so Home is untouched.
import { useCallback, useEffect, useRef, useState } from "react";
import { Link, useLocation } from "react-router-dom";
import { AlertTriangle, Bell, ChevronDown, ChevronRight, History, Inbox } from "lucide-react";

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
  dayHeading,
  groupResolvedByDay,
  sinceFor,
  unreadAlerts,
  type RangeKey,
} from "./bellModel";

/** Anyone who decides an approval says so here, so the bell can recount.
 *
 *  A DOM event rather than a store: the bell and the inbox are the only two
 *  things that care, they are never mounted together outside the shell, and one
 *  line beats a context for a fact this small. */
export const APPROVALS_CHANGED = "kdps:approvals-changed";

export function announceApprovalsChanged() {
  window.dispatchEvent(new Event(APPROVALS_CHANGED));
}

type TabKey = "alerts" | "approvals";

/** What a fetch said. `null` on either feed means the request failed and the tab
 *  shows a quiet line rather than an empty list, which would read as "all
 *  clear" - the most dangerous thing an alerts panel can say wrongly. */
type Feed<T> = T[] | null;

// ---------------------------------------------------------------------------
// History, shared by both tabs
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
// The two tabs
// ---------------------------------------------------------------------------

function AlertsTab({ alerts, onNavigate }: { alerts: Feed<AlertT>; onNavigate: () => void }) {
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

function ApprovalsTab({
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
// The bell itself
// ---------------------------------------------------------------------------

export function NotificationBell() {
  const [open, setOpen] = useState(false);
  const [tab, setTab] = useState<TabKey>("alerts");
  const [approvals, setApprovals] = useState<Feed<ApprovalT>>([]);
  const [alerts, setAlerts] = useState<Feed<AlertT>>([]);
  // One plain stamp, `null` meaning "no stamp" - which is what the contract
  // says an absent row means, and so also the honest answer while the read is
  // in flight or after it fails. It errs towards showing the count: a bell that
  // silently says "nothing waiting" because a request failed is the one wrong
  // answer an alerting surface must not give.
  const [seenAt, setSeenAt] = useState<string | null>(null);
  const wrap = useRef<HTMLDivElement>(null);
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

  // Re-counted on every navigation *and* whenever a decision is made, not once
  // per session: clearing the last item used to leave the bell insisting one
  // document was still waiting, right beside a page saying nothing was.
  const refresh = useCallback(() => {
    api
      .get("/approvals/inbox")
      .then((r) => setApprovals(r.data ?? []))
      .catch(() => setApprovals(null));
    void loadAlerts();
    api
      .get("/alerts/seen")
      .then((r) => setSeenAt(r.data?.seen_at ?? null))
      .catch(() => setSeenAt(null));
  }, [loadAlerts]);

  useEffect(() => {
    refresh();
    window.addEventListener(APPROVALS_CHANGED, refresh);
    return () => window.removeEventListener(APPROVALS_CHANGED, refresh);
  }, [refresh, pathname]);

  const unread = unreadAlerts(alerts ?? [], seenAt);
  const undecided = approvals?.length ?? 0;
  const total = unread + undecided;

  /**
   * Opening the Alerts tab is what "reading" means, so it stamps - but only
   * over a list that was actually just fetched.
   *
   * The feeds otherwise refresh on navigation, so a popup opened after an hour
   * on one screen would stamp "read as of now" across alerts raised in that
   * hour and never shown. `unreadAlerts` is strictly-after, so those would
   * never surface again: exactly the wrong direction for an alerting surface.
   * Hence refetch first, and do not stamp at all if the refetch failed.
   *
   * The badge zeroes locally the moment the tab opens rather than waiting for
   * the round trip, and goes back to what it was if the stamp did not land -
   * clearing a count the server never recorded would be the same silence.
   */
  const openAlertsTab = useCallback(() => {
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

  function openTab(next: TabKey) {
    setTab(next);
    if (next === "alerts") openAlertsTab();
  }

  function toggle() {
    if (open) {
      setOpen(false);
      return;
    }
    setOpen(true);
    openTab("alerts");
  }

  // Outside click and Esc, the two ways every other popup in this shell closes.
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

  const label = total
    ? `${total} thing${total === 1 ? "" : "s"} want your attention`
    : "Notifications - nothing waiting for you";

  return (
    <div className="bell-wrap" ref={wrap}>
      <button
        type="button"
        className="icon-btn"
        onClick={toggle}
        aria-label={label}
        aria-expanded={open}
        title={label}
        data-testid="notifications"
      >
        <Bell size={18} />
        {!!total && (
          <span className="bell-count" data-testid="notifications-count">
            {total > 9 ? "9+" : total}
          </span>
        )}
      </button>

      {open && (
        <div className="bell-popup" data-testid="notifications-popup">
          <div className="bell-tabs" role="tablist">
            {(
              [
                ["alerts", "Alerts", unread],
                ["approvals", "Approvals", undecided],
              ] as [TabKey, string, number][]
            ).map(([key, text, count]) => (
              <button
                key={key}
                type="button"
                role="tab"
                aria-selected={tab === key}
                className={`bell-tab ${tab === key ? "active" : ""}`}
                onClick={() => openTab(key)}
                data-testid={`bell-tab-${key}`}
              >
                {text}
                {!!count && (
                  <span className="bell-tab-count" data-testid={`bell-tab-count-${key}`}>
                    {count > 9 ? "9+" : count}
                  </span>
                )}
              </button>
            ))}
          </div>
          <div className="bell-body">
            {tab === "alerts" ? (
              <AlertsTab alerts={alerts} onNavigate={() => setOpen(false)} />
            ) : (
              <ApprovalsTab approvals={approvals} onNavigate={() => setOpen(false)} />
            )}
          </div>
        </div>
      )}
    </div>
  );
}
