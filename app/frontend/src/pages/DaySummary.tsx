// The store's day, by tender - and what the day left open (#188, D10 step 6).
//
// One screen, two halves, because they are one question. The top is what the
// counter took, which is the number a store person counts a drawer against. The
// bottom is the day's exceptions, which is why the drawer might not agree.
//
// **Read-only about money.** There is no "confirm the day" button and there
// deliberately cannot be one: agreeing a day - counting the float, locking the
// date - is store open/close (I3), its own designed flow sequenced after this.
// The single write on this screen is against an *exception*, and clearing one is
// a statement about somebody's attention, never a correction to a bill (A7).

import { useCallback, useEffect, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { AlertTriangle, Check, EyeOff, Receipt } from "lucide-react";

import { api, apiErrorMessage } from "../lib/api";
import { Money } from "../lib/format";
import { PageHeader } from "../components/PageHeader";
import { tillToday } from "../till/pricing";
import "./DaySummary.css";

/** `GET /api/store/cash-summary`. */
interface SummaryT {
  store: string;
  date: string;
  modes: { cash: number; card: number; upi: number; credit_note: number };
  /** `modes.upi`, split by how the money was proven. The only control on manual
   *  UPI: no manager PIN, just visibility the same evening. Optional because the
   *  API and PWA are two independently-deployed Render services (`render.yaml`)
   *  - a browser can hold the new bundle before the field ships. */
  upi_split?: { confirmed: number; manual: number };
  bills: number;
  returns: number;
  credit_notes_issued_paise: number;
  flags_open: number;
}

/** One row of `GET /api/sell/flags`. */
interface FlagT {
  id: number;
  kind: string;
  kind_label: string;
  status: "open" | "resolved" | "ignored";
  store_code: string;
  /** Empty on a flag about no particular bill - a hole, or a seller's return
   *  count. That is a fact rather than a gap, so there is no link to draw. */
  doc_number: string;
  billed_at: string | null;
  details: Record<string, unknown>;
  created_at: string;
  cleared_note: string;
  resolved_by_name: string;
  resolved_at: string | null;
}

/** The four tender columns, in the order a summary is read. Spelled out rather
 *  than mapped off the payload so a day with no card sales still draws a card
 *  tile: a column that vanishes when unused makes a person wonder where it went. */
const MODES = [
  { key: "cash", label: "Cash" },
  { key: "card", label: "Card" },
  { key: "upi", label: "UPI" },
  { key: "credit_note", label: "Credit note" },
] as const;

/** The finding, said the way a person would say it.
 *
 *  The server sends `details` as the machine wrote them, because a later nightly
 *  pass rewrites them and a sentence frozen at first sight would go stale. This
 *  is where they become English - one line, because this is a list somebody
 *  scans, and the whole row is there for anybody who wants the rest. */
export function flagLine(flag: Pick<FlagT, "kind" | "details">): string {
  const d = flag.details ?? {};
  switch (flag.kind) {
    case "number_hole": {
      const missing = (d.missing as number[]) ?? [];
      const count = (d.count as number) ?? missing.length;
      const shown = missing.slice(0, 6).join(", ");
      return count === 1
        ? `Bill ${shown} never arrived.`
        : `${count} bills never arrived${shown ? ` (${shown}${count > 6 ? "…" : ""})` : ""}.`;
    }
    case "employee_returns": {
      const sellers = (d.sellers as { name: string; returns: number }[]) ?? [];
      return sellers.length
        ? sellers.map((s) => `${s.name} took back ${s.returns}`).join("; ") +
            ` (over ${d.threshold ?? "the limit"} in a day).`
        : "A seller took back more than the day's limit.";
    }
    case "gst_mismatch": {
      const lines = (d.lines as { line_no: number }[]) ?? [];
      if (!lines.length) return `Printed ${d.printed_split ?? "?"}, books say ${d.derived_split ?? "?"}.`;
      return `Tax on line ${lines.map((l) => l.line_no).join(", ")} is not the dated slab's.`;
    }
    case "offer_mismatch": {
      const lines = (d.lines as { line_no: number }[]) ?? [];
      return `Line ${lines.map((l) => l.line_no).join(", ")} was not charged what the rulebook says.`;
    }
    case "gstin_invalid":
      return `The buyer's GSTIN ${d.gstin ?? ""} is not well formed: ${d.reason ?? "check it"}.`;
    case "cn_unverified":
      return `A credit note the shop does not recognise was taken: ${(d.notes as string[])?.join(", ") ?? ""}.`;
    case "return_orig_missing":
      return "A piece came back against a bill we do not hold.";
    case "aged_uncosted":
      return `Sold before inward and still unpriced since ${d.waiting_since ?? "?"}.`;
    default:
      return "";
  }
}

function fmtDate(iso: string): string {
  const [y, m, d] = iso.split("-").map(Number);
  return new Date(y, m - 1, d).toLocaleDateString("en-IN", {
    weekday: "short",
    day: "numeric",
    month: "short",
    year: "numeric",
  });
}

/** Saying something about one exception. Two answers and no way back to open -
 *  "dealt with" and "looked at, needs nothing" are different sentences, and the
 *  second takes a reason because nothing else evidences it. */
function ClearPanel({ flag, onDone }: { flag: FlagT; onDone: () => void }) {
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  async function send(status: "resolved" | "ignored") {
    setError("");
    setBusy(true);
    try {
      await api.put(`/sell/flags/${flag.id}`, { status, note });
      onDone();
    } catch (e) {
      setError(apiErrorMessage(e));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="flag-clear">
      <input
        className="input"
        value={note}
        disabled={busy}
        maxLength={240}
        placeholder="What did you do about it?"
        aria-label={`Note for ${flag.kind_label}`}
        onChange={(e) => setNote(e.target.value)}
        data-testid={`flag-note-${flag.id}`}
      />
      <button
        type="button"
        className="btn btn-primary"
        disabled={busy}
        onClick={() => void send("resolved")}
        data-testid={`flag-resolve-${flag.id}`}
      >
        <Check size={14} /> Dealt with
      </button>
      <button
        type="button"
        className="btn"
        disabled={busy || !note.trim()}
        title={note.trim() ? "" : "Say why this one needs nothing doing"}
        onClick={() => void send("ignored")}
        data-testid={`flag-ignore-${flag.id}`}
      >
        <EyeOff size={14} /> Needs nothing
      </button>
      {error && (
        <div className="login-error flag-error" data-testid={`flag-error-${flag.id}`}>
          {error}
        </div>
      )}
    </div>
  );
}

export default function DaySummary() {
  const [params, setParams] = useSearchParams();
  // The store's own day, not the browser's UTC one - the same helper the till
  // prices its offers by, because "today" flipping at 18:30 IST is the defect
  // that class of bug already produced once.
  const day = params.get("date") || tillToday();
  const [summary, setSummary] = useState<SummaryT>();
  const [open, setOpen] = useState<FlagT[]>([]);
  const [settled, setSettled] = useState<FlagT[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  // **Open exceptions are never narrowed to the picked day; settled ones are.**
  // They are the work, and this is the rule the IRN queue already holds to: a
  // store with three unanswered exceptions from last Tuesday still has three
  // today, and the Dashboard's own count says so with no date on it. Arriving
  // from that row and being told "nothing to look at" because the picker had
  // defaulted to this morning would be the card lying about itself. The picker
  // still governs the money above and the history behind.
  const load = useCallback(() => {
    setLoading(true);
    setError("");
    Promise.all([
      api.get("/store/cash-summary", { params: { date: day } }),
      api.get("/sell/flags", { params: { status: "open" } }),
      api.get("/sell/flags", { params: { date: day, status: "all" } }),
    ])
      .then(([s, live, ofDay]) => {
        setSummary(s.data);
        setOpen(live.data.rows as FlagT[]);
        setSettled((ofDay.data.rows as FlagT[]).filter((row) => row.status !== "open"));
      })
      .catch((e) => setError(apiErrorMessage(e)))
      .finally(() => setLoading(false));
  }, [day]);

  useEffect(load, [load]);

  return (
    <div className="page-pad">
      <PageHeader lead="What the counter took, and what the day left open. Read-only - the day is agreed at store close." />

      <div className="day-picker">
        <label className="day-picker-label" htmlFor="day-summary-date">
          Day
        </label>
        <input
          id="day-summary-date"
          type="date"
          className="input"
          value={day}
          max={tillToday()}
          onChange={(e) => setParams(e.target.value ? { date: e.target.value } : {})}
          data-testid="day-picker"
        />
        {summary && <span className="chip chip-grey">{summary.store}</span>}
      </div>

      {error && (
        <div className="login-error" data-testid="day-error">
          {error}
        </div>
      )}

      {loading || !summary ? (
        <p className="lead">Loading…</p>
      ) : (
        <>
          <div className="card day-panel" data-testid="day-money">
            <div className="day-panel-head">
              <p className="eyebrow">Collected</p>
              <h3 className="h3">{fmtDate(summary.date)}</h3>
            </div>
            <div className="day-modes" data-testid="day-modes">
              {MODES.map((mode) => (
                <div className="day-cell" key={mode.key} data-testid={`day-mode-${mode.key}`}>
                  <span className="day-num mono">
                    <Money paise={summary.modes[mode.key]} />
                  </span>
                  <span className="day-label">{mode.label}</span>
                  {mode.key === "upi" && (
                    <span className="day-upi-split" data-testid="day-upi-split">
                      <Money paise={summary.upi_split?.confirmed ?? 0} /> confirmed ·{" "}
                      <Money paise={summary.upi_split?.manual ?? 0} /> manual
                    </span>
                  )}
                </div>
              ))}
            </div>
            <div className="day-counts" data-testid="day-counts">
              <span className="day-count">
                <b className="mono">
                  {/* Folded over `MODES` rather than adding the four by name:
                      a fifth place the tender list is spelled is a fifth place
                      it can fall out of step with the other four. */}
                  <Money paise={MODES.reduce((sum, m) => sum + summary.modes[m.key], 0)} />
                </b>
                Taken in all
              </span>
              <span className="day-count">
                <b className="mono">{summary.bills}</b>Bills
              </span>
              <span className="day-count">
                <b className="mono">{summary.returns}</b>Pieces back
              </span>
              <span className="day-count">
                <b className="mono">
                  <Money paise={summary.credit_notes_issued_paise} />
                </b>
                Credit notes given
              </span>
            </div>
            {/* Credit notes are not money in the drawer - they close a liability
                the shop already owed - so the one figure a person counts cash
                against is said out loud rather than left to be worked out. */}
            <p className="lead day-drawer" data-testid="day-drawer">
              Cash in the drawer for this day: <b className="mono"><Money paise={summary.modes.cash} /></b>
            </p>
          </div>

          <div className="card day-panel" data-testid="day-flags">
            <div className="day-panel-head">
              <p className="eyebrow">Exceptions</p>
              <h3 className="h3">
                {open.length === 0 ? "Nothing to look at" : `${open.length} to look at`}
              </h3>
              {/* Said out loud, because it is the one block on this screen the
                  day picker does not govern - and a person who had just moved
                  the picker would otherwise read these as that day's. */}
              <p className="lead day-flags-scope">
                Every exception still open at this store, whichever day it came from.
                {settled.length > 0 && " Below them, what was answered on the day picked above."}
              </p>
            </div>

            {open.length === 0 && settled.length === 0 ? (
              <p className="lead" data-testid="day-flags-empty">
                <Receipt size={15} /> Nothing is waiting - every bill arrived, and the tax and
                offers agree with the rulebook.
              </p>
            ) : (
              <div className="flag-list">
                {[...open, ...settled].map((flag) => (
                  <div
                    className="flag-row"
                    key={flag.id}
                    data-status={flag.status}
                    data-testid={`flag-${flag.id}`}
                  >
                    <div className="flag-head">
                      <AlertTriangle size={15} className="flag-ic" />
                      <b>{flag.kind_label}</b>
                      {flag.doc_number && (
                        <Link
                          className="flag-bill mono"
                          to={`/sell/customers?doc=${encodeURIComponent(flag.doc_number)}`}
                          data-testid={`flag-bill-${flag.id}`}
                        >
                          {flag.doc_number}
                        </Link>
                      )}
                      {flag.status !== "open" && (
                        <span className={`chip chip-${flag.status === "resolved" ? "green" : "grey"}`}>
                          {flag.status === "resolved" ? "Dealt with" : "Needs nothing"}
                          {flag.resolved_by_name ? ` · ${flag.resolved_by_name}` : ""}
                        </span>
                      )}
                    </div>
                    <p className="flag-say">{flagLine(flag)}</p>
                    {flag.cleared_note && <p className="flag-note">“{flag.cleared_note}”</p>}
                    {flag.status === "open" && <ClearPanel flag={flag} onDone={load} />}
                  </div>
                ))}
              </div>
            )}
          </div>
        </>
      )}
    </div>
  );
}
