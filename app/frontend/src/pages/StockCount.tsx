/**
 * Stock Count — blind counting sessions and the variance they produce (#76).
 *
 * Two screens. The list is the counts at your locations; the detail is one
 * count: its sessions (several counters may be scanning different sections at
 * once), and — once at least one of them has been submitted — the merged
 * variance report in pieces and in rupees.
 *
 * Blind is not a UI decision here: an open session's lines simply carry no book
 * quantity, because the server does not take one until submit. So there is
 * nothing on this screen to remember to hide.
 *
 * Nothing on this page subtracts anything. Book, counted, difference and value
 * all arrive computed — the old typing screen's arithmetic is gone.
 */

import { useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { ArrowLeft, ClipboardCheck, Play, Plus, ScanLine, Send } from "lucide-react";

import { api, apiErrorMessage } from "../lib/api";
import { useAuth } from "../auth/AuthContext";
import { useDoc, useList } from "../lib/hooks";
import { Money } from "../lib/format";
import { canWriteStockCount } from "../lib/outbound-rbac";
import { ScanScreen, type ScanResult, type ScanTarget } from "../components/ScanScreen";
import "./Booking.css";

// ---------------------------------------------------------------------------
// Types + helpers
// ---------------------------------------------------------------------------

interface SessionLineT {
  id: number;
  sku_code: string;
  design: string;
  color: string;
  size: string;
  brand: string;
  counted_qty: number;
  book_qty: number | null;
}

interface SessionT {
  id: number;
  scope: string;
  scope_value: string;
  scope_label: string;
  status: string;
  counted_by_name: string;
  counted_pieces: number;
  submitted_at: string | null;
  lines: SessionLineT[];
}

interface StocktakeT {
  id: number;
  store: number;
  store_code: string;
  store_name: string;
  status: string;
  note: string;
  opened_by_name: string;
  adjustment: number | null;
  adjustment_doc_number: string;
  adjustment_docstatus: number | null;
  created_at: string;
  sessions: SessionT[];
}

interface VarianceLineT {
  sku_code: string;
  design: string;
  color: string;
  size: string;
  brand: string;
  book_qty: number;
  counted_qty: number;
  adj_qty: number;
  live_book_qty: number;
  moved: boolean;
  unit_cost_paise: number;
  variance_paise: number;
  cost_known: boolean;
}

interface VarianceT {
  lines: VarianceLineT[];
  net_pieces: number;
  net_variance_paise: number;
  unpriced: string[];
}

interface StoreT { id: number; code: string; name: string; }

const SCOPES = [
  { value: "store", label: "Whole store" },
  { value: "brand", label: "One brand" },
  { value: "section", label: "One section" },
];

const STATUS_TONE: Record<string, string> = { open: "amber", submitted: "navy", closed: "green" };
const STATUS_LABEL: Record<string, string> = {
  open: "Counting",
  submitted: "Submitted",
  closed: "Applied",
};

function fmtDate(iso: string): string {
  return new Date(iso).toLocaleDateString("en-IN", { day: "numeric", month: "short", year: "numeric" });
}

function skuLabel(l: { design: string; color: string; size: string; brand: string }): string {
  return [l.design, l.color, l.size].filter(Boolean).join(" · ") || l.brand || "—";
}

function StatusPill({ status }: { status: string }) {
  return (
    <span className={`chip chip-${STATUS_TONE[status] ?? "grey"} status-pill`}>
      {STATUS_LABEL[status] ?? status}
    </span>
  );
}

function Signed({ n }: { n: number }) {
  return (
    <span style={{ color: n < 0 ? "var(--red)" : n > 0 ? "var(--green)" : undefined, fontWeight: 700 }}>
      {n > 0 ? "+" : ""}{n}
    </span>
  );
}

// ---------------------------------------------------------------------------
// List
// ---------------------------------------------------------------------------

export function StockCountListPage() {
  const { user } = useAuth();
  const navigate = useNavigate();
  const { data, loading } = useList<StocktakeT>("/outbound/stocktakes");
  const { data: stores } = useList<StoreT>("/masters/stores");
  const writable = canWriteStockCount(user);

  const storeLocked = user?.scope_type === "store" && (user?.stores?.length ?? 0) >= 1;
  const lockedStore = storeLocked ? user!.stores[0] : null;
  const [storeId, setStoreId] = useState<string>(lockedStore ? String(lockedStore.id) : "");
  const [note, setNote] = useState("");
  const [error, setError] = useState("");
  const [opening, setOpening] = useState(false);

  async function openCount() {
    setError("");
    if (!storeId) { setError("Select a location to count."); return; }
    setOpening(true);
    try {
      const { data: take } = await api.post("/outbound/stocktakes", {
        store: Number(storeId),
        note,
      });
      navigate(`/stock-count/${take.id}`);
    } catch (e) {
      setError(apiErrorMessage(e));
    } finally {
      setOpening(false);
    }
  }

  return (
    <div className="page-pad">
      <div className="toolbar">
        <div>
          <p className="eyebrow">Stock Count · Sessions</p>
          <h1 className="h1 h2-rust">Stock Counts</h1>
          <p className="lead">Counters scan blind; the book appears when the count is submitted.</p>
        </div>
      </div>

      {writable && (
        <div className="card section-card" data-testid="open-count-card">
          <p className="eyebrow">Start a count</p>
          <div className="form-row" style={{ marginTop: 10 }}>
            <div className="field">
              <label>Location</label>
              {storeLocked && lockedStore ? (
                <div className="store-lock" data-testid="count-store-locked">
                  {lockedStore.code} · {lockedStore.name}
                </div>
              ) : (
                <select
                  className="select"
                  value={storeId}
                  onChange={(e) => setStoreId(e.target.value)}
                  data-testid="count-store-select"
                >
                  <option value="">Select location…</option>
                  {stores.map((s) => (
                    <option key={s.id} value={s.id}>{s.code} · {s.name}</option>
                  ))}
                </select>
              )}
            </div>
            <div className="field">
              <label>Note (optional)</label>
              <input
                className="input"
                value={note}
                onChange={(e) => setNote(e.target.value)}
                placeholder="Month-end audit"
                data-testid="count-note"
              />
            </div>
          </div>
          {error && <div className="login-error" style={{ maxWidth: 480 }} data-testid="count-open-error">{error}</div>}
          <button className="btn btn-cta" disabled={opening} onClick={openCount} data-testid="open-count-btn">
            <Plus size={16} /> {opening ? "Opening…" : "Open a count"}
          </button>
        </div>
      )}

      {loading ? (
        <p className="lead">Loading…</p>
      ) : data.length === 0 ? (
        <div className="card section-card" data-testid="count-empty">
          No counts yet. Open one to start counting a store, a brand or a section.
        </div>
      ) : (
        <div className="table-wrap">
          <table className="data" data-testid="count-table">
            <thead>
              <tr>
                <th>Count</th>
                <th>Location</th>
                <th className="num">Sessions</th>
                <th className="num">Pieces counted</th>
                <th>Status</th>
                <th>Correction</th>
                <th>Opened</th>
              </tr>
            </thead>
            <tbody>
              {data.map((t) => (
                <tr key={t.id} data-testid={`count-row-${t.id}`}>
                  <td>
                    <Link to={`/stock-count/${t.id}`} className="link-cell mono" data-testid={`count-link-${t.id}`}>
                      <b>Count #{t.id}</b>
                    </Link>
                  </td>
                  <td><b className="mono">{t.store_code}</b></td>
                  <td className="num">{t.sessions.length}</td>
                  <td className="num">{t.sessions.reduce((s, x) => s + x.counted_pieces, 0)}</td>
                  <td><StatusPill status={t.status} /></td>
                  <td>
                    {t.adjustment ? (
                      <Link to={`/stock-count/adjustments/${t.adjustment}`} className="mono">
                        {t.adjustment_doc_number || `Draft #${t.adjustment}`}
                      </Link>
                    ) : "—"}
                  </td>
                  <td>{fmtDate(t.created_at)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Detail — sessions, scanning, and the merged variance
// ---------------------------------------------------------------------------

export function StockCountDetailPage() {
  const { id } = useParams();
  const { user } = useAuth();
  const { data: take, loading } = useDoc<StocktakeT>(`/outbound/stocktakes/${id}`);
  const writable = canWriteStockCount(user);

  const [scope, setScope] = useState("store");
  const [scopeValue, setScopeValue] = useState("");
  const [scanning, setScanning] = useState<SessionT | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [variance, setVariance] = useState<VarianceT | null>(null);
  const [movedAsk, setMovedAsk] = useState<VarianceLineT[] | null>(null);

  if (loading || !take) return <div className="page-pad"><p className="lead">Loading…</p></div>;

  const submitted = take.sessions.filter((s) => s.status !== "open");
  const canApply = writable && take.status !== "closed" && submitted.length > 0;

  /** Post something and show the result, which on this screen always means
   *  reloading: a count changes on the server (another counter submits, the
   *  variance is applied) and a partial client update would show one of the two
   *  halves. `onFail` lets a caller answer a refusal in its own way. */
  async function post(url: string, body: unknown, onFail?: (e: unknown) => boolean) {
    setError("");
    setBusy(true);
    try {
      await api.post(url, body);
      window.location.reload();
    } catch (e) {
      if (!onFail?.(e)) setError(apiErrorMessage(e));
      setBusy(false);
    }
  }

  const startSession = () =>
    post(`/outbound/stocktakes/${take.id}/sessions`, {
      scope,
      scope_value: scope === "store" ? "" : scopeValue,
    });

  /** A count's lookup, not a transfer's: it never answers with a quantity, and
   *  a piece the location holds none of still scans — that is the surplus. */
  async function lookupPiece(barcode: string): Promise<ScanTarget | null> {
    try {
      const { data } = await api.get(
        `/outbound/count-lookup?store=${take!.store}&barcode=${encodeURIComponent(barcode)}`,
      );
      return { barcode: data.barcode, label: skuLabel(data), expected: null };
    } catch {
      return null;
    }
  }

  const saveScans = (session: SessionT, result: ScanResult) =>
    post(`/outbound/count-sessions/${session.id}/scan`, {
      scans: Object.entries(result.scans).map(([barcode, qty]) => ({ barcode, qty })),
    });

  const submitSession = (session: SessionT) =>
    post(`/outbound/count-sessions/${session.id}/submit`, {});

  async function loadVariance() {
    setError("");
    try {
      const { data } = await api.get(`/outbound/stocktakes/${take!.id}/variance`);
      setVariance(data);
    } catch (e) {
      setError(apiErrorMessage(e));
    }
  }

  const apply = (confirm: string[] = []) =>
    post(`/outbound/stocktakes/${take.id}/apply`, { confirm }, (e: any) => {
      // 409: pieces moved between the count and now. Never overwritten blind —
      // the person sees which piece moved, and says so line by line.
      if (e?.response?.status !== 409) return false;
      setMovedAsk(e.response.data.moved as VarianceLineT[]);
      return true;
    });

  return (
    <div className="page-pad">
      <Link to="/stock-count" className="btn" style={{ marginBottom: 16 }} data-testid="count-detail-back">
        <ArrowLeft size={15} /> Stock counts
      </Link>
      <div className="toolbar">
        <div>
          <p className="eyebrow">Count #{take.id}</p>
          <h1 className="h1">Stock Count — {take.store_code}</h1>
          <p className="lead">
            {take.store_name}
            {take.note ? ` · ${take.note}` : ""} · opened by {take.opened_by_name || "—"}
          </p>
        </div>
        <div className="spacer" />
        <StatusPill status={take.status} />
      </div>

      {error && <div className="login-error" style={{ maxWidth: 560 }} data-testid="count-detail-error">{error}</div>}

      {writable && take.status === "open" && (
        <div className="card section-card" data-testid="new-session-card">
          <p className="eyebrow">Add a counter</p>
          <h3 className="h3">New session</h3>
          <div className="form-row" style={{ marginTop: 10 }}>
            <div className="field">
              <label>Scope</label>
              <select className="select" value={scope} onChange={(e) => setScope(e.target.value)} data-testid="session-scope-select">
                {SCOPES.map((s) => <option key={s.value} value={s.value}>{s.label}</option>)}
              </select>
            </div>
            {scope !== "store" && (
              <div className="field">
                <label>{scope === "brand" ? "Brand" : "Section"}</label>
                <input
                  className="input"
                  value={scopeValue}
                  onChange={(e) => setScopeValue(e.target.value)}
                  placeholder={scope === "brand" ? "Louis Philippe" : "Rack A / Kids floor"}
                  data-testid="session-scope-value"
                />
              </div>
            )}
          </div>
          <button className="btn btn-cta" disabled={busy} onClick={startSession} data-testid="start-session-btn">
            <Play size={15} /> Start counting
          </button>
        </div>
      )}

      <div className="card section-card">
        <p className="eyebrow">Sessions</p>
        <h3 className="h3">{take.sessions.length} counter{take.sessions.length === 1 ? "" : "s"}</h3>
        {take.sessions.length === 0 ? (
          <p className="lead">Nobody is counting yet.</p>
        ) : (
          <div className="table-wrap" style={{ marginTop: 10 }}>
            <table className="data" data-testid="session-table">
              <thead>
                <tr>
                  <th>Scope</th>
                  <th>Counter</th>
                  <th className="num">Pieces scanned</th>
                  <th>Status</th>
                  <th />
                </tr>
              </thead>
              <tbody>
                {take.sessions.map((s) => (
                  <tr key={s.id} data-testid={`session-row-${s.id}`}>
                    <td>{s.scope_label}</td>
                    <td>{s.counted_by_name || "—"}</td>
                    <td className="num">{s.counted_pieces}</td>
                    <td><StatusPill status={s.status} /></td>
                    <td>
                      {s.status === "open" && writable && (
                        <>
                          <button
                            type="button"
                            className="btn"
                            onClick={() => { setError(""); setScanning(s); }}
                            data-testid={`scan-session-${s.id}`}
                          >
                            <ScanLine size={15} /> Scan
                          </button>{" "}
                          <button
                            type="button"
                            className="btn btn-cta"
                            disabled={busy}
                            onClick={() => void submitSession(s)}
                            data-testid={`submit-session-${s.id}`}
                          >
                            <Send size={15} /> Submit count
                          </button>
                        </>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {submitted.length > 0 && (
        <div className="card section-card" data-testid="variance-card">
          <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between" }}>
            <div>
              <p className="eyebrow">Book vs counted · every submitted session merged</p>
              <h3 className="h3">Variance report</h3>
            </div>
            <button type="button" className="btn" onClick={() => void loadVariance()} data-testid="load-variance-btn">
              <ClipboardCheck size={15} /> {variance ? "Refresh" : "Show variance"}
            </button>
          </div>

          {variance && (
            <>
              <div className="form-row" style={{ margin: "14px 0" }}>
                <div className="card section-card">
                  <p className="eyebrow">Net pieces</p>
                  <h3 className="h3"><Signed n={variance.net_pieces} /></h3>
                </div>
                <div className="card section-card">
                  <p className="eyebrow">Net value</p>
                  <h3 className="h3" style={{ color: variance.net_variance_paise < 0 ? "var(--red)" : undefined }}>
                    <Money paise={variance.net_variance_paise} />
                  </h3>
                </div>
                <div className="card section-card">
                  <p className="eyebrow">Lines</p>
                  <h3 className="h3">{variance.lines.length}</h3>
                </div>
              </div>

              {variance.unpriced.length > 0 && (
                <div className="chip chip-amber" data-testid="variance-unpriced">
                  The books cannot price {variance.unpriced.length} piece
                  {variance.unpriced.length === 1 ? "" : "s"} — bring them in on a PT before correcting.
                </div>
              )}

              <div className="table-wrap" style={{ marginTop: 10 }}>
                <table className="data" data-testid="variance-table">
                  <thead>
                    <tr>
                      <th>SKU</th>
                      <th>Piece</th>
                      <th className="num">Book</th>
                      <th className="num">Counted</th>
                      <th className="num">Difference</th>
                      <th className="num">Cost</th>
                      <th className="num">Value</th>
                    </tr>
                  </thead>
                  <tbody>
                    {variance.lines.map((l) => (
                      <tr key={l.sku_code} data-testid={`variance-row-${l.sku_code}`}>
                        <td><b className="mono">{l.sku_code}</b></td>
                        <td>
                          {skuLabel(l)}
                          {l.moved && (
                            <span className="chip chip-amber" style={{ marginLeft: 8 }} data-testid={`moved-${l.sku_code}`}>
                              moved since the count
                            </span>
                          )}
                        </td>
                        <td className="num">{l.book_qty}</td>
                        <td className="num">{l.counted_qty}</td>
                        <td className="num"><Signed n={l.adj_qty} /></td>
                        <td className="num">{l.cost_known ? <Money paise={l.unit_cost_paise} /> : "unknown"}</td>
                        <td className="num">{l.cost_known ? <Money paise={l.variance_paise} /> : "—"}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>

              {canApply && (
                <button
                  className="btn btn-primary btn-lg"
                  style={{ marginTop: 14 }}
                  disabled={busy}
                  onClick={() => void apply()}
                  data-testid="apply-variance-btn"
                >
                  <ClipboardCheck size={16} /> {busy ? "Applying…" : "Apply the variance"}
                </button>
              )}
            </>
          )}
        </div>
      )}

      {take.adjustment && (
        <div className="card section-card" data-testid="count-adjustment-card">
          <p className="eyebrow">The correction this count produced</p>
          <h3 className="h3">
            <Link to={`/stock-count/adjustments/${take.adjustment}`} className="mono">
              {take.adjustment_doc_number || `Draft #${take.adjustment}`}
            </Link>
          </h3>
          <p className="lead">
            {take.adjustment_docstatus === 1
              ? "Within tolerance — adjusted and logged, no second person asked."
              : "Above tolerance — waiting for a second person to approve it."}
          </p>
        </div>
      )}

      {movedAsk && (
        <div className="card section-card" data-testid="moved-confirm-card">
          <p className="eyebrow">Confirm before applying</p>
          <h3 className="h3">These pieces moved since the count</h3>
          <p className="lead">
            Somebody sold, transferred or corrected them after the count was submitted. The
            difference the count found still applies — the later movement is already on the books —
            but nothing is overwritten until you say so.
          </p>
          <div className="table-wrap" style={{ marginTop: 10 }}>
            <table className="data" data-testid="moved-table">
              <thead>
                <tr>
                  <th>SKU</th>
                  <th className="num">Book at count</th>
                  <th className="num">Book now</th>
                  <th className="num">Counted</th>
                  <th className="num">Difference</th>
                </tr>
              </thead>
              <tbody>
                {movedAsk.map((l) => (
                  <tr key={l.sku_code}>
                    <td><b className="mono">{l.sku_code}</b></td>
                    <td className="num">{l.book_qty}</td>
                    <td className="num">{l.live_book_qty}</td>
                    <td className="num">{l.counted_qty}</td>
                    <td className="num"><Signed n={l.adj_qty} /></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <div style={{ display: "flex", gap: 10, marginTop: 12 }}>
            <button
              className="btn btn-primary"
              disabled={busy}
              onClick={() => void apply(movedAsk.map((l) => l.sku_code))}
              data-testid="confirm-moved-btn"
            >
              Apply these too
            </button>
            <button className="btn" onClick={() => setMovedAsk(null)} data-testid="cancel-moved-btn">
              Not now
            </button>
          </div>
        </div>
      )}

      {scanning && (
        <ScanScreen
          mode="COUNT"
          docLabel={`Count #${take.id}`}
          routeLabel={`${take.store_code} · ${scanning.scope_label}`}
          targets={[]}
          lookup={lookupPiece}
          confirmLabel="Save what I counted"
          busy={busy}
          error={error}
          onConfirm={(result) => void saveScans(scanning, result)}
          onClose={() => setScanning(null)}
        />
      )}
    </div>
  );
}
