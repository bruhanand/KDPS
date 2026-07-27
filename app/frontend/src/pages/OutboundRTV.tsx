import { useState } from "react";
import { Link, useNavigate, useParams, useSearchParams } from "react-router-dom";
import {
  ArrowLeft,
  PackageMinus,
  Plus,
  RotateCcw,
  Send,
  Trash2,
} from "lucide-react";

import { api, apiErrorMessage } from "../lib/api";
import { useAuth } from "../auth/AuthContext";
import { useDoc, useList } from "../lib/hooks";
import { Money } from "../lib/format";
import { canWriteReturnToBrand } from "../lib/outbound-rbac";
import { ListSearchBar } from "../components/SearchBox";
import "./Booking.css";
import { PageHeader } from "../components/PageHeader";

// ---------------------------------------------------------------------------
// Helpers & controlled vocab
// ---------------------------------------------------------------------------

function fmtDate(iso: string): string {
  return new Date(iso).toLocaleDateString("en-IN", { day: "numeric", month: "short", year: "numeric" });
}

const DS_TONE: Record<number, string> = { 0: "grey", 1: "green", 2: "red" };
const DS_LABEL: Record<number, string> = { 0: "Draft", 1: "Submitted", 2: "Cancelled" };
function DocPill({ ds }: { ds: number }) {
  return <span className={`chip chip-${DS_TONE[ds] ?? "grey"} status-pill`}>{DS_LABEL[ds] ?? ds}</span>;
}

const RETURN_TYPE_LABEL: Record<string, string> = {
  defective: "Defective / GR return",
  seasonal: "Season-end return",
};

const LOGISTICS_OPTIONS = [
  { value: "store_pickup", label: "Brand collects from store (Madura)" },
  { value: "warehouse", label: "Consolidated at warehouse" },
];

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface RTVLineT {
  id: number;
  sku_code: string;
  design: string;
  color: string;
  size: string;
  brand: string;
  season: string;
  item: string;
  hsn: string;
  qty: number;
  unit_cost_paise: number;
}

interface RTVT {
  id: number;
  doc_number: string | null;
  docstatus: number;
  store: number;
  store_code: string;
  store_name: string;
  vendor: number;
  brand: number | null;
  return_type: string;
  logistics_route: string;
  season: string;
  return_window_date: string | null;
  credit_note_received: boolean;
  credit_note_date: string | null;
  notes: string;
  created_by: number | null;
  created_at: string;
  updated_at: string;
  lines: RTVLineT[];
}

interface StoreT { id: number; code: string; name: string; store_type: string; }
interface VendorT { id: number; name: string; }
interface BrandT { id: number; name: string; }

// ---------------------------------------------------------------------------
// List
// ---------------------------------------------------------------------------

export function RTVListPage() {
  const [params, setParams] = useSearchParams();
  const { user } = useAuth();
  const tab = params.get("type") === "seasonal" ? "seasonal" : "defective";
  const [q, setQ] = useState("");
  const { data, loading } = useList<RTVT>("/outbound/rtvs", { return_type: tab, q });
  const writable = canWriteReturnToBrand(user);

  function setTab(next: string) {
    setParams((p) => { p.set("type", next); return p; });
  }

  return (
    <div className="page-pad">
      <PageHeader
        actions={
          writable && (
            <Link className="btn btn-cta" to="/return-to-brand/new" data-testid="new-rtv-btn">
              <Plus size={16} /> New RTV
            </Link>
          )
        }
      />

      <div className="mode-toggle" data-testid="rtv-type-toggle" style={{ maxWidth: 520, marginBottom: 18 }}>
        <button
          type="button"
          className={`mode-btn ${tab === "defective" ? "active" : ""}`}
          onClick={() => setTab("defective")}
          data-testid="rtv-tab-defective"
        >
          <PackageMinus size={16} /> Defective / GR
        </button>
        <button
          type="button"
          className={`mode-btn ${tab === "seasonal" ? "active" : ""}`}
          onClick={() => setTab("seasonal")}
          data-testid="rtv-tab-seasonal"
        >
          <RotateCcw size={16} /> Season-end
        </button>
      </div>

      <ListSearchBar
        value={q}
        onChange={setQ}
        placeholder="Search returns — doc number, brand"
        label="Search returns to brand"
        testId="rtv-search"
        noun="return"
        count={data.length}
        loading={loading}
      />

      {loading ? (
        <p className="lead">Loading…</p>
      ) : data.length === 0 ? (
        <div className="card section-card" data-testid="rtv-empty">
          {q
            ? `No ${RETURN_TYPE_LABEL[tab]?.toLowerCase() || tab} matches “${q}”.`
            : `No ${RETURN_TYPE_LABEL[tab]?.toLowerCase() || tab} returns yet.`}
        </div>
      ) : (
        <div className="table-wrap">
          <table className="data" data-testid="rtv-table">
            <thead>
              <tr>
                <th>Doc #</th>
                <th>Store</th>
                <th>Type</th>
                <th>Logistics</th>
                <th className="num">Lines</th>
                <th>Credit note</th>
                <th>Status</th>
                <th>Date</th>
              </tr>
            </thead>
            <tbody>
              {data.map((r) => (
                <tr key={r.id} data-testid={`rtv-row-${r.id}`}>
                  <td>
                    <Link to={`/return-to-brand/${r.id}`} className="link-cell mono" data-testid={`rtv-link-${r.id}`}>
                      <b>{r.doc_number || `Draft #${r.id}`}</b>
                    </Link>
                  </td>
                  <td><b className="mono">{r.store_code}</b></td>
                  <td>
                    <span className={`chip chip-${r.return_type === "defective" ? "red" : "amber"}`}>
                      {RETURN_TYPE_LABEL[r.return_type] ?? r.return_type}
                    </span>
                  </td>
                  <td>{LOGISTICS_OPTIONS.find((o) => o.value === r.logistics_route)?.label || r.logistics_route || "—"}</td>
                  <td className="num">{r.lines.length}</td>
                  <td>
                    {r.credit_note_received ? (
                      <span className="chip chip-green">Received</span>
                    ) : (
                      <span className="chip chip-grey">Pending</span>
                    )}
                  </td>
                  <td><DocPill ds={r.docstatus} /></td>
                  <td>{fmtDate(r.created_at)}</td>
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
// Create
// ---------------------------------------------------------------------------

interface DraftRTVLine {
  sku_code: string;
  design: string;
  size: string;
  color: string;
  qty: number | string;
}
const emptyLine = (): DraftRTVLine => ({
  sku_code: "", design: "", size: "", color: "", qty: "",
});

export function RTVNewPage() {
  const navigate = useNavigate();
  const { user } = useAuth();
  const { data: stores } = useList<StoreT>("/masters/stores");
  const { data: vendors } = useList<VendorT>("/vendors");
  const { data: brands } = useList<BrandT>("/masters/brands");

  const storeLocked = user?.scope_type === "store" && (user?.stores?.length ?? 0) >= 1;
  const lockedStore = storeLocked ? user!.stores[0] : null;

  const [storeId, setStoreId] = useState<string>(lockedStore ? String(lockedStore.id) : "");
  const [vendorId, setVendorId] = useState("");
  const [brandId, setBrandId] = useState("");
  const [returnType, setReturnType] = useState("defective");
  const [logisticsRoute, setLogisticsRoute] = useState("");
  const [season, setSeason] = useState("");
  const [returnWindowDate, setReturnWindowDate] = useState("");
  const [notes, setNotes] = useState("");
  const [lines, setLines] = useState<DraftRTVLine[]>([emptyLine()]);
  const [error, setError] = useState("");
  const [saving, setSaving] = useState(false);

  function setLine(i: number, key: keyof DraftRTVLine, val: string) {
    setLines((ls) => ls.map((l, idx) => (idx === i ? { ...l, [key]: val } : l)));
  }

  async function save() {
    setError("");
    if (!storeId) { setError("Select a store."); return; }
    if (!vendorId) { setError("Select a vendor."); return; }
    const payloadLines = lines
      .filter((l) => l.sku_code && Number(l.qty) > 0)
      .map((l) => ({
        sku_code: l.sku_code,
        design: l.design,
        size: l.size,
        color: l.color,
        qty: Number(l.qty),
      }));
    if (!payloadLines.length) { setError("Add at least one line with a SKU and quantity."); return; }
    setSaving(true);
    try {
      const { data } = await api.post("/outbound/rtvs", {
        store: Number(storeId),
        vendor: Number(vendorId),
        brand: brandId ? Number(brandId) : null,
        return_type: returnType,
        logistics_route: logisticsRoute,
        season,
        return_window_date: returnWindowDate || null,
        notes,
        lines: payloadLines,
      });
      navigate(`/return-to-brand/${data.id}`);
    } catch (e) {
      setError(apiErrorMessage(e));
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="page-pad">
      <Link to="/return-to-brand" className="btn" style={{ marginBottom: 16 }} data-testid="rtv-back-link">
        <ArrowLeft size={15} /> Returns
      </Link>
      <h1 className="h1 h2-rust" style={{ marginBottom: 18 }}>New Return to Vendor</h1>

      <div className="card section-card">
        <p className="eyebrow">Step 1 · Return details</p>
        <div className="form-row" style={{ marginTop: 10 }}>
          <div className="field">
            <label>Store</label>
            {storeLocked && lockedStore ? (
              <div className="store-lock" data-testid="rtv-store-locked">{lockedStore.code} · {lockedStore.name}</div>
            ) : (
              <select className="select" value={storeId} onChange={(e) => setStoreId(e.target.value)} data-testid="rtv-store-select">
                <option value="">Select store…</option>
                {stores.map((s) => <option key={s.id} value={s.id}>{s.code} · {s.name}</option>)}
              </select>
            )}
          </div>
          <div className="field">
            <label>Vendor</label>
            <select className="select" value={vendorId} onChange={(e) => setVendorId(e.target.value)} data-testid="rtv-vendor-select">
              <option value="">Select vendor…</option>
              {vendors.map((v) => <option key={v.id} value={v.id}>{v.name}</option>)}
            </select>
          </div>
          <div className="field">
            <label>Brand (optional)</label>
            <select className="select" value={brandId} onChange={(e) => setBrandId(e.target.value)} data-testid="rtv-brand-select">
              <option value="">All / unspecified</option>
              {brands.map((b) => <option key={b.id} value={b.id}>{b.name}</option>)}
            </select>
          </div>
          <div className="field">
            <label>Return type</label>
            <select className="select" value={returnType} onChange={(e) => setReturnType(e.target.value)} data-testid="rtv-type-select">
              <option value="defective">Defective / GR return</option>
              <option value="seasonal">Season-end return</option>
            </select>
          </div>
        </div>
        <div className="form-row" style={{ marginTop: 14 }}>
          <div className="field">
            <label>Logistics route</label>
            <select className="select" value={logisticsRoute} onChange={(e) => setLogisticsRoute(e.target.value)} data-testid="rtv-logistics-select">
              <option value="">Select route…</option>
              {LOGISTICS_OPTIONS.map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}
            </select>
          </div>
          <div className="field">
            <label>Season</label>
            <input className="input" value={season} onChange={(e) => setSeason(e.target.value)} placeholder="e.g. AW24" data-testid="rtv-season" />
          </div>
          {returnType === "seasonal" && (
            <div className="field">
              <label>Return window deadline</label>
              <input className="input" type="date" value={returnWindowDate} onChange={(e) => setReturnWindowDate(e.target.value)} data-testid="rtv-window-date" />
            </div>
          )}
          <div className="field">
            <label>Notes</label>
            <input className="input" value={notes} onChange={(e) => setNotes(e.target.value)} placeholder="Optional notes" data-testid="rtv-notes" />
          </div>
        </div>
      </div>

      <div className="card section-card">
        <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 10 }}>
          <div>
            <p className="eyebrow">Step 2 · Items to return</p>
            <h3 className="h3">Return lines</h3>
          </div>
          <button type="button" className="btn" onClick={() => setLines((l) => [...l, emptyLine()])} data-testid="add-rtv-line">
            <Plus size={15} /> Add line
          </button>
        </div>
        <table className="lines-table" data-testid="rtv-lines">
          <thead>
            <tr>
              <th style={{ width: "24%" }}>SKU code</th>
              <th>Design</th>
              <th>Size</th>
              <th>Colour</th>
              <th className="num">Qty</th>
              <th />
            </tr>
          </thead>
          <tbody>
            {lines.map((l, i) => (
              <tr key={i}>
                <td><input value={l.sku_code} onChange={(e) => setLine(i, "sku_code", e.target.value)} data-testid={`rtv-sku-${i}`} /></td>
                <td><input value={l.design} onChange={(e) => setLine(i, "design", e.target.value)} data-testid={`rtv-design-${i}`} /></td>
                <td><input value={l.size} onChange={(e) => setLine(i, "size", e.target.value)} data-testid={`rtv-size-${i}`} /></td>
                <td><input value={l.color} onChange={(e) => setLine(i, "color", e.target.value)} data-testid={`rtv-color-${i}`} /></td>
                <td><input className="num" value={l.qty} onChange={(e) => setLine(i, "qty", e.target.value)} data-testid={`rtv-qty-${i}`} /></td>
                <td><button type="button" className="line-del" onClick={() => setLines((ls) => ls.filter((_, idx) => idx !== i))} data-testid={`delete-rtv-line-${i}`}><Trash2 size={15} /></button></td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {error && <div className="login-error" style={{ maxWidth: 480 }} data-testid="rtv-create-error">{error}</div>}
      <button className="btn btn-primary btn-lg" disabled={saving} onClick={save} data-testid="save-rtv-btn">
        <RotateCcw size={16} /> {saving ? "Saving…" : "Create RTV (draft)"}
      </button>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Detail
// ---------------------------------------------------------------------------

export function RTVDetailPage() {
  const { id } = useParams();
  const { user } = useAuth();
  const { data: r, loading } = useDoc<RTVT>(`/outbound/rtvs/${id}`);
  const writable = canWriteReturnToBrand(user);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState("");

  if (loading || !r) return <div className="page-pad"><p className="lead">Loading…</p></div>;

  const totalQty = r.lines.reduce((s, l) => s + l.qty, 0);
  const canSubmit = r.docstatus === 0 && writable;

  async function handleSubmit() {
    setError("");
    setSubmitting(true);
    try {
      await api.post(`/outbound/rtvs/${r!.id}/submit`);
      window.location.reload();
    } catch (e) {
      setError(apiErrorMessage(e));
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div className="page-pad">
      <Link to="/return-to-brand" className="btn" style={{ marginBottom: 16 }} data-testid="rtv-detail-back">
        <ArrowLeft size={15} /> Returns
      </Link>
      <div className="toolbar">
        <div>
          <p className="eyebrow">{r.doc_number || `Draft #${r.id}`}</p>
          <h1 className="h1">RTV — {r.store_code}</h1>
          <p className="lead">
            {r.store_name}
            {r.season ? ` · ${r.season}` : ""}
            {r.notes ? ` · ${r.notes}` : ""}
          </p>
        </div>
        <div className="spacer" />
        <DocPill ds={r.docstatus} />
        <span className={`chip chip-${r.return_type === "defective" ? "red" : "amber"}`}>
          {RETURN_TYPE_LABEL[r.return_type] ?? r.return_type}
        </span>
        {canSubmit && (
          <button
            type="button"
            className="btn btn-cta"
            disabled={submitting}
            onClick={handleSubmit}
            data-testid="submit-rtv-btn"
          >
            <Send size={15} /> {submitting ? "Submitting…" : "Submit RTV"}
          </button>
        )}
      </div>

      <div className="form-row" style={{ marginBottom: 18 }}>
        <div className="card section-card">
          <p className="eyebrow">Logistics</p>
          <h3 className="h3">{LOGISTICS_OPTIONS.find((o) => o.value === r.logistics_route)?.label || r.logistics_route || "—"}</h3>
        </div>
        <div className="card section-card">
          <p className="eyebrow">Total qty</p>
          <h3 className="h3">{totalQty} pcs</h3>
        </div>
        <div className="card section-card">
          <p className="eyebrow">Credit note</p>
          <h3 className="h3">{r.credit_note_received ? `Received ${r.credit_note_date ? fmtDate(r.credit_note_date) : ""}` : "Pending"}</h3>
        </div>
        {r.return_window_date && (
          <div className="card section-card">
            <p className="eyebrow">Return window</p>
            <h3 className="h3">{fmtDate(r.return_window_date)}</h3>
          </div>
        )}
        <div className="card section-card">
          <p className="eyebrow">Date</p>
          <h3 className="h3">{fmtDate(r.created_at)}</h3>
        </div>
      </div>

      {error && <div className="login-error" style={{ maxWidth: 480 }} data-testid="rtv-detail-error">{error}</div>}

      <div className="table-wrap">
        <table className="data" data-testid="rtv-detail-lines">
          <thead>
            <tr>
              <th>SKU</th>
              <th>Design</th>
              <th>Size</th>
              <th>Colour</th>
              <th>Brand</th>
              <th>Season</th>
              <th className="num">Qty</th>
              <th className="num">Cost</th>
            </tr>
          </thead>
          <tbody>
            {r.lines.map((l) => (
              <tr key={l.id}>
                <td><b className="mono">{l.sku_code}</b></td>
                <td>{l.design || "—"}</td>
                <td>{l.size || "—"}</td>
                <td>{l.color || "—"}</td>
                <td>{l.brand || "—"}</td>
                <td>{l.season || "—"}</td>
                <td className="num">{l.qty}</td>
                <td className="num">{l.unit_cost_paise ? <Money paise={l.unit_cost_paise} /> : "—"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
