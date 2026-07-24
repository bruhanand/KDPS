import { useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import {
  ArrowLeft,
  ClipboardCheck,
  Plus,
  Send,
  Trash2,
} from "lucide-react";

import { api, apiErrorMessage } from "../lib/api";
import { useAuth } from "../auth/AuthContext";
import { useDoc, useList } from "../lib/hooks";
import { Money } from "../lib/format";
import { canOutboundWrite } from "../lib/outbound-rbac";
import { ApprovalPill, ApprovalTrail, isCleared, type ApprovalT } from "../components/approval";
import "./Booking.css";

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function fmtDate(iso: string): string {
  return new Date(iso).toLocaleDateString("en-IN", { day: "numeric", month: "short", year: "numeric" });
}

const DS_TONE: Record<number, string> = { 0: "grey", 1: "green", 2: "red" };
const DS_LABEL: Record<number, string> = { 0: "Draft", 1: "Submitted", 2: "Cancelled" };
function DocPill({ ds }: { ds: number }) {
  return <span className={`chip chip-${DS_TONE[ds] ?? "grey"} status-pill`}>{DS_LABEL[ds] ?? ds}</span>;
}

const REASON_OPTIONS = [
  { value: "shrinkage", label: "Shrinkage" },
  { value: "miscount", label: "Miscount" },
  { value: "damage", label: "Damage" },
  { value: "surplus_found", label: "Surplus found" },
  { value: "other", label: "Other" },
];

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface AdjLineT {
  id: number;
  sku_code: string;
  design: string;
  color: string;
  size: string;
  brand: string;
  season: string;
  item: string;
  hsn: string;
  book_qty: number;
  counted_qty: number;
  adj_qty: number;
  unit_cost_paise: number;
}

interface AdjT {
  id: number;
  doc_number: string | null;
  docstatus: number;
  store: number;
  store_code: string;
  store_name: string;
  reason: string;
  approved_by: number | null;
  approved_by_name: string;
  approval: ApprovalT | null;
  approval_history: ApprovalT[];
  notes: string;
  created_by: number | null;
  created_by_name: string;
  created_at: string;
  updated_at: string;
  lines: AdjLineT[];
}

interface StoreT { id: number; code: string; name: string; store_type: string; }

// ---------------------------------------------------------------------------
// List
// ---------------------------------------------------------------------------

export function AdjustmentListPage() {
  const { user } = useAuth();
  const { data, loading } = useList<AdjT>("/outbound/adjustments");
  const writable = canOutboundWrite(user?.role?.code);

  return (
    <div className="page-pad">
      <div className="toolbar">
        <div>
          <p className="eyebrow">Outbound · Adjustments</p>
          <h1 className="h1 h2-rust">Stock Adjustments</h1>
        </div>
        <div className="spacer" />
        {writable && (
          <Link className="btn btn-cta" to="/stock-count/adjustments/new" data-testid="new-adjustment-btn">
            <Plus size={16} /> New adjustment
          </Link>
        )}
      </div>

      {loading ? (
        <p className="lead">Loading…</p>
      ) : data.length === 0 ? (
        <div className="card section-card" data-testid="adjustment-empty">
          No stock adjustments yet. Create one after a physical count.
        </div>
      ) : (
        <div className="table-wrap">
          <table className="data" data-testid="adjustment-table">
            <thead>
              <tr>
                <th>Doc #</th>
                <th>Store</th>
                <th>Reason</th>
                <th className="num">Lines</th>
                <th className="num">Net variance</th>
                <th>Status</th>
                <th>Date</th>
              </tr>
            </thead>
            <tbody>
              {data.map((a) => {
                const netAdj = a.lines.reduce((s, l) => s + l.adj_qty, 0);
                return (
                  <tr key={a.id} data-testid={`adj-row-${a.id}`}>
                    <td>
                      <Link to={`/stock-count/adjustments/${a.id}`} className="link-cell mono" data-testid={`adj-link-${a.id}`}>
                        <b>{a.doc_number || `Draft #${a.id}`}</b>
                      </Link>
                    </td>
                    <td><b className="mono">{a.store_code}</b></td>
                    <td>{REASON_OPTIONS.find((r) => r.value === a.reason)?.label || a.reason}</td>
                    <td className="num">{a.lines.length}</td>
                    <td className="num">
                      <span style={{ color: netAdj < 0 ? "var(--red)" : netAdj > 0 ? "var(--green)" : undefined }}>
                        {netAdj > 0 ? "+" : ""}{netAdj}
                      </span>
                    </td>
                    <td><DocPill ds={a.docstatus} /></td>
                    <td>{fmtDate(a.created_at)}</td>
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

// ---------------------------------------------------------------------------
// Create
// ---------------------------------------------------------------------------

interface DraftAdjLine {
  sku_code: string;
  design: string;
  size: string;
  color: string;
  book_qty: number | string;
  counted_qty: number | string;
}
const emptyLine = (): DraftAdjLine => ({
  sku_code: "", design: "", size: "", color: "", book_qty: "", counted_qty: "",
});

export function AdjustmentNewPage() {
  const navigate = useNavigate();
  const { user } = useAuth();
  const { data: stores } = useList<StoreT>("/masters/stores");

  const storeLocked = user?.scope_type === "store" && (user?.stores?.length ?? 0) >= 1;
  const lockedStore = storeLocked ? user!.stores[0] : null;

  const [storeId, setStoreId] = useState<string>(lockedStore ? String(lockedStore.id) : "");
  const [reason, setReason] = useState("");
  const [notes, setNotes] = useState("");
  const [lines, setLines] = useState<DraftAdjLine[]>([emptyLine()]);
  const [error, setError] = useState("");
  const [saving, setSaving] = useState(false);

  function setLine(i: number, key: keyof DraftAdjLine, val: string) {
    setLines((ls) => ls.map((l, idx) => (idx === i ? { ...l, [key]: val } : l)));
  }

  async function save() {
    setError("");
    if (!storeId) { setError("Select a store."); return; }
    if (!reason) { setError("Select a reason."); return; }
    const payloadLines = lines
      .filter((l) => l.sku_code)
      .map((l) => {
        const book = Number(l.book_qty) || 0;
        const counted = Number(l.counted_qty) || 0;
        return {
          sku_code: l.sku_code,
          design: l.design,
          size: l.size,
          color: l.color,
          book_qty: book,
          counted_qty: counted,
          adj_qty: counted - book,
        };
      });
    if (!payloadLines.length) { setError("Add at least one line with a SKU."); return; }
    setSaving(true);
    try {
      const { data } = await api.post("/outbound/adjustments", {
        store: Number(storeId),
        reason,
        notes,
        lines: payloadLines,
      });
      navigate(`/stock-count/adjustments/${data.id}`);
    } catch (e) {
      setError(apiErrorMessage(e));
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="page-pad">
      <Link to="/stock-count/adjustments" className="btn" style={{ marginBottom: 16 }} data-testid="adj-back-link">
        <ArrowLeft size={15} /> Adjustments
      </Link>
      <h1 className="h1 h2-rust" style={{ marginBottom: 18 }}>New Stock Adjustment</h1>

      <div className="card section-card">
        <p className="eyebrow">Step 1 · Adjustment details</p>
        <div className="form-row" style={{ marginTop: 10 }}>
          <div className="field">
            <label>Store</label>
            {storeLocked && lockedStore ? (
              <div className="store-lock" data-testid="adj-store-locked">{lockedStore.code} · {lockedStore.name}</div>
            ) : (
              <select className="select" value={storeId} onChange={(e) => setStoreId(e.target.value)} data-testid="adj-store-select">
                <option value="">Select store…</option>
                {stores.map((s) => <option key={s.id} value={s.id}>{s.code} · {s.name}</option>)}
              </select>
            )}
          </div>
          <div className="field">
            <label>Reason</label>
            <select className="select" value={reason} onChange={(e) => setReason(e.target.value)} data-testid="adj-reason-select">
              <option value="">Select reason…</option>
              {REASON_OPTIONS.map((r) => <option key={r.value} value={r.value}>{r.label}</option>)}
            </select>
          </div>
          <div className="field">
            <label>Notes (optional)</label>
            <input className="input" value={notes} onChange={(e) => setNotes(e.target.value)} placeholder="Context for this adjustment" data-testid="adj-notes" />
          </div>
        </div>
      </div>

      <div className="card section-card">
        <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 10 }}>
          <div>
            <p className="eyebrow">Step 2 · Book vs physical count</p>
            <h3 className="h3">Adjustment lines</h3>
          </div>
          <button type="button" className="btn" onClick={() => setLines((l) => [...l, emptyLine()])} data-testid="add-adj-line">
            <Plus size={15} /> Add line
          </button>
        </div>
        <table className="lines-table" data-testid="adj-lines">
          <thead>
            <tr>
              <th style={{ width: "22%" }}>SKU code</th>
              <th>Design</th>
              <th>Size</th>
              <th>Colour</th>
              <th className="num">Book qty</th>
              <th className="num">Counted</th>
              <th className="num">Adj</th>
              <th />
            </tr>
          </thead>
          <tbody>
            {lines.map((l, i) => {
              const adj = (Number(l.counted_qty) || 0) - (Number(l.book_qty) || 0);
              return (
                <tr key={i}>
                  <td><input value={l.sku_code} onChange={(e) => setLine(i, "sku_code", e.target.value)} data-testid={`adj-sku-${i}`} /></td>
                  <td><input value={l.design} onChange={(e) => setLine(i, "design", e.target.value)} data-testid={`adj-design-${i}`} /></td>
                  <td><input value={l.size} onChange={(e) => setLine(i, "size", e.target.value)} data-testid={`adj-size-${i}`} /></td>
                  <td><input value={l.color} onChange={(e) => setLine(i, "color", e.target.value)} data-testid={`adj-color-${i}`} /></td>
                  <td><input className="num" value={l.book_qty} onChange={(e) => setLine(i, "book_qty", e.target.value)} data-testid={`adj-book-${i}`} /></td>
                  <td><input className="num" value={l.counted_qty} onChange={(e) => setLine(i, "counted_qty", e.target.value)} data-testid={`adj-counted-${i}`} /></td>
                  <td className="num" style={{ color: adj < 0 ? "var(--red)" : adj > 0 ? "var(--green)" : undefined, fontWeight: 700 }}>
                    {adj > 0 ? "+" : ""}{adj || "—"}
                  </td>
                  <td><button type="button" className="line-del" onClick={() => setLines((ls) => ls.filter((_, idx) => idx !== i))} data-testid={`delete-adj-line-${i}`}><Trash2 size={15} /></button></td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>

      {error && <div className="login-error" style={{ maxWidth: 480 }} data-testid="adj-create-error">{error}</div>}
      <button className="btn btn-primary btn-lg" disabled={saving} onClick={save} data-testid="save-adj-btn">
        <ClipboardCheck size={16} /> {saving ? "Saving…" : "Create adjustment (draft)"}
      </button>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Detail
// ---------------------------------------------------------------------------

export function AdjustmentDetailPage() {
  const { id } = useParams();
  const { user } = useAuth();
  const { data: a, loading } = useDoc<AdjT>(`/outbound/adjustments/${id}`);
  const writable = canOutboundWrite(user?.role?.code);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState("");

  if (loading || !a) return <div className="page-pad"><p className="lead">Loading…</p></div>;

  const netAdj = a.lines.reduce((s, l) => s + l.adj_qty, 0);
  // An adjustment cannot post until a second person has approved it (#70).
  const canSubmit = a.docstatus === 0 && writable && isCleared(a.approval);

  async function handleSubmit() {
    setError("");
    setSubmitting(true);
    try {
      await api.post(`/outbound/adjustments/${a!.id}/submit`);
      window.location.reload();
    } catch (e) {
      setError(apiErrorMessage(e));
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div className="page-pad">
      <Link to="/stock-count/adjustments" className="btn" style={{ marginBottom: 16 }} data-testid="adj-detail-back">
        <ArrowLeft size={15} /> Adjustments
      </Link>
      <div className="toolbar">
        <div>
          <p className="eyebrow">{a.doc_number || `Draft #${a.id}`}</p>
          <h1 className="h1">Stock Adjustment — {a.store_code}</h1>
          <p className="lead">
            {a.store_name} · {REASON_OPTIONS.find((r) => r.value === a.reason)?.label || a.reason}
            {a.notes ? ` · ${a.notes}` : ""}
          </p>
        </div>
        <div className="spacer" />
        <DocPill ds={a.docstatus} />
        {a.docstatus === 0 && <ApprovalPill status={a.approval?.status ?? "pending"} />}
        {canSubmit && (
          <button
            type="button"
            className="btn btn-cta"
            disabled={submitting}
            onClick={handleSubmit}
            data-testid="submit-adj-btn"
          >
            <Send size={15} /> {submitting ? "Submitting…" : "Submit adjustment"}
          </button>
        )}
      </div>

      <div className="form-row" style={{ marginBottom: 18 }}>
        <div className="card section-card">
          <p className="eyebrow">Reason</p>
          <h3 className="h3">{REASON_OPTIONS.find((r) => r.value === a.reason)?.label || a.reason}</h3>
        </div>
        <div className="card section-card">
          <p className="eyebrow">Net variance</p>
          <h3 className="h3" style={{ color: netAdj < 0 ? "var(--red)" : netAdj > 0 ? "var(--green)" : undefined }}>
            {netAdj > 0 ? "+" : ""}{netAdj} pcs
          </h3>
        </div>
        <div className="card section-card">
          <p className="eyebrow">Lines</p>
          <h3 className="h3">{a.lines.length}</h3>
        </div>
        <div className="card section-card">
          <p className="eyebrow">Date</p>
          <h3 className="h3">{fmtDate(a.created_at)}</h3>
        </div>
      </div>

      <div style={{ marginBottom: 18 }}>
        <ApprovalTrail
          createdByName={a.created_by_name}
          createdAt={a.created_at}
          approval={a.approval}
          history={a.approval_history}
          askAgainPath={writable ? `/outbound/adjustments/${a.id}/request-approval` : undefined}
        />
      </div>

      {error && <div className="login-error" style={{ maxWidth: 480 }} data-testid="adj-detail-error">{error}</div>}

      <div className="table-wrap">
        <table className="data" data-testid="adj-detail-lines">
          <thead>
            <tr>
              <th>SKU</th>
              <th>Design</th>
              <th>Size</th>
              <th>Colour</th>
              <th>Brand</th>
              <th className="num">Book</th>
              <th className="num">Counted</th>
              <th className="num">Adj</th>
              <th className="num">Cost</th>
            </tr>
          </thead>
          <tbody>
            {a.lines.map((l) => (
              <tr key={l.id}>
                <td><b className="mono">{l.sku_code}</b></td>
                <td>{l.design || "—"}</td>
                <td>{l.size || "—"}</td>
                <td>{l.color || "—"}</td>
                <td>{l.brand || "—"}</td>
                <td className="num">{l.book_qty}</td>
                <td className="num">{l.counted_qty}</td>
                <td className="num" style={{ fontWeight: 700, color: l.adj_qty < 0 ? "var(--red)" : l.adj_qty > 0 ? "var(--green)" : undefined }}>
                  {l.adj_qty > 0 ? "+" : ""}{l.adj_qty}
                </td>
                <td className="num">{l.unit_cost_paise ? <Money paise={l.unit_cost_paise} /> : "—"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
