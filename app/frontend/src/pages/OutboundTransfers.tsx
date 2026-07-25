import { useMemo, useState } from "react";
import { Link, useNavigate, useParams, useSearchParams } from "react-router-dom";
import {
  ArrowLeft,
  ArrowRight,
  AlertTriangle,
  Boxes,
  PackageCheck,
  Plus,
  Send,
  Trash2,
  Truck,
} from "lucide-react";

import { api, apiErrorMessage } from "../lib/api";
import { useAuth } from "../auth/AuthContext";
import { useDoc, useList } from "../lib/hooks";
import { Money } from "../lib/format";
import { canWriteTransfer } from "../lib/outbound-rbac";
import { ScanScreen, type ScanTarget } from "../components/ScanScreen";
import "./Booking.css";

// ---------------------------------------------------------------------------
// Shared helpers
// ---------------------------------------------------------------------------

function fmtDate(iso: string): string {
  return new Date(iso).toLocaleDateString("en-IN", { day: "numeric", month: "short", year: "numeric" });
}

const DS_TONE: Record<number, string> = { 0: "grey", 1: "green", 2: "red" };
const DS_LABEL: Record<number, string> = { 0: "Draft", 1: "Submitted", 2: "Cancelled" };

function DocPill({ ds }: { ds: number }) {
  return <span className={`chip chip-${DS_TONE[ds] ?? "grey"} status-pill`}>{DS_LABEL[ds] ?? ds}</span>;
}

const TRANSFER_TYPE_LABEL: Record<string, string> = {
  store_split: "Store split",
  inter_store: "Inter-store",
};

const REASON_OPTIONS = [
  { value: "sister_store_request", label: "Sister store request" },
  { value: "slow_mover", label: "Slow mover" },
  { value: "seasonal_swap", label: "Seasonal swap" },
  { value: "free_floor_space", label: "Free floor space" },
  { value: "customer_waiting", label: "Customer waiting" },
  { value: "other", label: "Other" },
];

const TRANSPORT_OPTIONS = [
  { value: "public_bus", label: "Public bus" },
  { value: "courier", label: "Courier" },
  { value: "own_vehicle", label: "Own vehicle" },
  { value: "hand_carried", label: "Hand-carried" },
];

const RECEIPT_TONE: Record<string, string> = {
  pending: "amber",
  complete: "green",
  shortfall: "red",
};

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface StoreT {
  id: number;
  code: string;
  name: string;
  store_type: string;
  state_name: string;
  gstin: number | null;
}

interface TransferLineT {
  id: number;
  sku_code: string;
  design: string;
  color: string;
  size: string;
  brand: string;
  season: string;
  item: string;
  hsn: string;
  qty_planned: number | null;
  qty_dispatched: number;
  qty_received: number;
  qty_in_transit: number;
  unit_cost_paise: number;
}

interface ReceiptT {
  id: number;
  received_by: number | null;
  receipt_date: string;
  receipt_status: string;
  shortfall_notes: string;
}

interface TransferT {
  id: number;
  doc_number: string | null;
  docstatus: number;
  transfer_type: string;
  is_cross_state: boolean;
  source_store: number;
  source_store_code: string;
  source_store_name: string;
  destination_store: number;
  destination_store_code: string;
  destination_store_name: string;
  reason: string;
  transport_mode: string;
  transport_ref: string;
  dispatcher_name: string;
  expected_arrival_note: string;
  eway_bill_number: string;
  dispatch_date: string | null;
  dispatched_by: number | null;
  created_by: number | null;
  created_at: string;
  updated_at: string;
  dispatch_mismatch: boolean;
  lines: TransferLineT[];
  receipt: ReceiptT | null;
}

// ---------------------------------------------------------------------------
// List
// ---------------------------------------------------------------------------

export function TransferListPage() {
  const [params, setParams] = useSearchParams();
  const { user } = useAuth();
  const tab = params.get("type") === "store_split" ? "store_split" : "inter_store";
  const writable = canWriteTransfer(user);

  const { data, loading } = useList<TransferT>(`/outbound/transfers?type=${tab}`);

  function setTab(next: string) {
    setParams((p) => { p.set("type", next); return p; });
  }

  return (
    <div className="page-pad">
      <div className="toolbar">
        <div>
          <p className="eyebrow">Outbound · Transfers</p>
          <h1 className="h1 h2-rust">Stock Transfers</h1>
        </div>
        <div className="spacer" />
        {writable && (
          <Link className="btn btn-cta" to="/transfer/new" data-testid="new-transfer-btn">
            <Plus size={16} /> New transfer
          </Link>
        )}
      </div>

      <div className="mode-toggle" data-testid="transfer-type-toggle" style={{ maxWidth: 520, marginBottom: 18 }}>
        <button
          type="button"
          className={`mode-btn ${tab === "inter_store" ? "active" : ""}`}
          onClick={() => setTab("inter_store")}
          data-testid="transfer-tab-inter"
        >
          <ArrowRight size={16} /> Inter-store
        </button>
        <button
          type="button"
          className={`mode-btn ${tab === "store_split" ? "active" : ""}`}
          onClick={() => setTab("store_split")}
          data-testid="transfer-tab-split"
        >
          <Boxes size={16} /> Store split (WH → store)
        </button>
      </div>

      {loading ? (
        <p className="lead">Loading…</p>
      ) : data.length === 0 ? (
        <div className="card section-card" data-testid="transfer-empty">
          No {tab === "store_split" ? "store split" : "inter-store"} transfers yet.
        </div>
      ) : (
        <div className="table-wrap">
          <table className="data" data-testid="transfer-table">
            <thead>
              <tr>
                <th>Doc #</th>
                <th>From</th>
                <th>To</th>
                <th>Reason</th>
                <th className="num">Lines</th>
                <th>Cross-state</th>
                <th>Status</th>
                <th>Receipt</th>
                <th>Date</th>
              </tr>
            </thead>
            <tbody>
              {data.map((t) => (
                <tr key={t.id} data-testid={`transfer-row-${t.id}`}>
                  <td>
                    <Link to={`/transfer/${t.id}`} className="link-cell mono" data-testid={`transfer-link-${t.id}`}>
                      <b>{t.doc_number || `Draft #${t.id}`}</b>
                    </Link>
                  </td>
                  <td><b className="mono">{t.source_store_code}</b></td>
                  <td><b className="mono">{t.destination_store_code}</b></td>
                  <td>{REASON_OPTIONS.find((r) => r.value === t.reason)?.label || t.reason || "—"}</td>
                  <td className="num">{t.lines.length}</td>
                  <td>
                    {t.is_cross_state ? (
                      <span className="chip chip-amber">Cross-state</span>
                    ) : (
                      <span className="chip chip-grey">Same state</span>
                    )}
                  </td>
                  <td><DocPill ds={t.docstatus} /></td>
                  <td>
                    {t.receipt ? (
                      <span className={`chip chip-${RECEIPT_TONE[t.receipt.receipt_status] ?? "grey"}`}>
                        {t.receipt.receipt_status}
                      </span>
                    ) : t.docstatus === 1 ? (
                      <span className="chip chip-amber">In transit</span>
                    ) : (
                      "—"
                    )}
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
// Create
// ---------------------------------------------------------------------------

interface DraftPlanLine {
  sku_code: string;
  qty_planned: number | string;
}
const emptyLine = (): DraftPlanLine => ({ sku_code: "", qty_planned: "" });

export function TransferNewPage() {
  const navigate = useNavigate();
  const { user } = useAuth();
  const { data: stores } = useList<StoreT>("/masters/stores");

  const storeLocked = user?.scope_type === "store" && (user?.stores?.length ?? 0) >= 1;
  const lockedStore = storeLocked ? user!.stores[0] : null;

  const [sourceId, setSourceId] = useState<string>(lockedStore ? String(lockedStore.id) : "");
  const [destId, setDestId] = useState("");
  const [transferType, setTransferType] = useState("inter_store");
  const [reason, setReason] = useState("");
  const [transportMode, setTransportMode] = useState("");
  const [transportRef, setTransportRef] = useState("");
  const [dispatcherName, setDispatcherName] = useState("");
  const [expectedArrival, setExpectedArrival] = useState("");
  const [ewayBill, setEwayBill] = useState("");
  const [lines, setLines] = useState<DraftPlanLine[]>([]);
  const [error, setError] = useState("");
  const [saving, setSaving] = useState(false);

  // Determine cross-state from selected stores
  const isCrossState = useMemo(() => {
    if (!sourceId || !destId) return false;
    const src = stores.find((s) => String(s.id) === sourceId);
    const dst = stores.find((s) => String(s.id) === destId);
    if (!src || !dst) return false;
    return src.gstin !== dst.gstin;
  }, [sourceId, destId, stores]);

  function setLine(i: number, key: keyof DraftPlanLine, val: string) {
    setLines((ls) => ls.map((l, idx) => (idx === i ? { ...l, [key]: val } : l)));
  }

  async function save() {
    setError("");
    if (!sourceId) { setError("Select a source store."); return; }
    if (!destId) { setError("Select a destination store."); return; }
    if (sourceId === destId) { setError("Source and destination must differ."); return; }
    if (isCrossState && !ewayBill.trim()) { setError("E-way bill number is required for cross-state transfers."); return; }
    const payloadLines = lines
      .filter((l) => l.sku_code && Number(l.qty_planned) > 0)
      .map((l) => ({ sku_code: l.sku_code.trim(), qty_planned: Number(l.qty_planned) }));
    if (lines.some((l) => l.sku_code && !(Number(l.qty_planned) > 0))) {
      setError("Every plan line needs a quantity of at least 1.");
      return;
    }
    setSaving(true);
    try {
      const { data } = await api.post("/outbound/transfers", {
        source_store: Number(sourceId),
        destination_store: Number(destId),
        transfer_type: transferType,
        reason,
        transport_mode: transportMode,
        transport_ref: transportRef,
        dispatcher_name: dispatcherName,
        expected_arrival_note: expectedArrival,
        eway_bill_number: ewayBill,
        lines: payloadLines,
      });
      navigate(`/transfer/${data.id}`);
    } catch (e) {
      setError(apiErrorMessage(e));
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="page-pad">
      <Link to="/transfer" className="btn" style={{ marginBottom: 16 }} data-testid="transfer-back-link">
        <ArrowLeft size={15} /> Transfers
      </Link>
      <h1 className="h1 h2-rust" style={{ marginBottom: 18 }}>New transfer</h1>

      <div className="card section-card">
        <p className="eyebrow">Step 1 · Locations</p>
        <div className="form-row" style={{ marginTop: 10 }}>
          <div className="field">
            <label>Source store / warehouse</label>
            {storeLocked && lockedStore ? (
              <div className="store-lock" data-testid="transfer-source-locked">
                {lockedStore.code} · {lockedStore.name}
              </div>
            ) : (
              <select className="select" value={sourceId} onChange={(e) => setSourceId(e.target.value)} data-testid="transfer-source-select">
                <option value="">Select source…</option>
                {stores.map((s) => (
                  <option key={s.id} value={s.id}>{s.code} · {s.name} {s.store_type === "warehouse" ? "(WH)" : ""}</option>
                ))}
              </select>
            )}
          </div>
          <div className="field">
            <label>Destination store / warehouse</label>
            <select className="select" value={destId} onChange={(e) => setDestId(e.target.value)} data-testid="transfer-dest-select">
              <option value="">Select destination…</option>
              {stores.filter((s) => String(s.id) !== sourceId).map((s) => (
                <option key={s.id} value={s.id}>{s.code} · {s.name} {s.store_type === "warehouse" ? "(WH)" : ""}</option>
              ))}
            </select>
          </div>
          <div className="field">
            <label>Transfer type</label>
            <select className="select" value={transferType} onChange={(e) => setTransferType(e.target.value)} data-testid="transfer-type-select">
              <option value="inter_store">Inter-store</option>
              <option value="store_split">Store split (WH → store)</option>
            </select>
          </div>
          <div className="field">
            <label>Reason</label>
            <select className="select" value={reason} onChange={(e) => setReason(e.target.value)} data-testid="transfer-reason-select">
              <option value="">Select reason…</option>
              {REASON_OPTIONS.map((r) => (
                <option key={r.value} value={r.value}>{r.label}</option>
              ))}
            </select>
          </div>
        </div>
        {isCrossState && (
          <div className="warn-note" style={{ marginTop: 14 }} data-testid="cross-state-warning">
            <AlertTriangle size={14} style={{ verticalAlign: "middle", marginRight: 6 }} />
            Cross-state transfer (Bihar ↔ Jharkhand) — <b>E-way bill is required</b>.
          </div>
        )}
      </div>

      <div className="card section-card">
        <p className="eyebrow">Step 2 · Transport details</p>
        <div className="form-row" style={{ marginTop: 10 }}>
          <div className="field">
            <label>Transport mode</label>
            <select className="select" value={transportMode} onChange={(e) => setTransportMode(e.target.value)} data-testid="transfer-transport-mode">
              <option value="">Select mode…</option>
              {TRANSPORT_OPTIONS.map((t) => (
                <option key={t.value} value={t.value}>{t.label}</option>
              ))}
            </select>
          </div>
          <div className="field">
            <label>Bus / courier AWB / vehicle plate</label>
            <input className="input" value={transportRef} onChange={(e) => setTransportRef(e.target.value)} placeholder="Transport ID" data-testid="transfer-transport-ref" />
          </div>
          <div className="field">
            <label>Dispatcher name</label>
            <input className="input" value={dispatcherName} onChange={(e) => setDispatcherName(e.target.value)} placeholder="Who is dispatching?" data-testid="transfer-dispatcher" />
          </div>
          <div className="field">
            <label>Expected arrival</label>
            <input className="input" value={expectedArrival} onChange={(e) => setExpectedArrival(e.target.value)} placeholder="e.g. Tomorrow by 2 PM" data-testid="transfer-expected-arrival" />
          </div>
          {isCrossState && (
            <div className="field">
              <label>E-way bill number *</label>
              <input className="input" value={ewayBill} onChange={(e) => setEwayBill(e.target.value)} placeholder="Required for cross-state" data-testid="transfer-eway-bill" />
            </div>
          )}
        </div>
      </div>

      <div className="card section-card">
        <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 10 }}>
          <div>
            <p className="eyebrow">Step 3 · Plan (optional)</p>
            <h3 className="h3">Planned lines</h3>
          </div>
          <button type="button" className="btn" onClick={() => setLines((l) => [...l, emptyLine()])} data-testid="add-transfer-line">
            <Plus size={15} /> Add plan line
          </button>
        </div>
        <p className="lead" style={{ marginBottom: 10 }}>
          The plan is what dispatch scans <b>against</b> — the scanned pieces are the only
          quantities that move stock. Leave it empty to build the transfer by scanning the
          carton at dispatch (store → store).
        </p>
        {lines.length > 0 && (
          <table className="lines-table" data-testid="transfer-lines">
            <thead>
              <tr>
                <th style={{ width: "50%" }}>Barcode / SKU</th>
                <th className="num">Planned qty</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {lines.map((l, i) => (
                <tr key={i}>
                  <td><input value={l.sku_code} onChange={(e) => setLine(i, "sku_code", e.target.value)} data-testid={`tl-sku-${i}`} /></td>
                  <td><input className="num" value={l.qty_planned} onChange={(e) => setLine(i, "qty_planned", e.target.value)} data-testid={`tl-qty-${i}`} /></td>
                  <td><button type="button" className="line-del" onClick={() => setLines((ls) => ls.filter((_, idx) => idx !== i))} data-testid={`delete-tl-${i}`}><Trash2 size={15} /></button></td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>

      {error && <div className="login-error" style={{ maxWidth: 540 }} data-testid="transfer-create-error">{error}</div>}
      <button className="btn btn-primary btn-lg" disabled={saving} onClick={save} data-testid="save-transfer-btn">
        <Truck size={16} /> {saving ? "Saving…" : "Create transfer (draft)"}
      </button>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Detail
// ---------------------------------------------------------------------------

function lineLabel(l: TransferLineT): string {
  return [l.design, l.color, l.size].filter(Boolean).join(" · ") || l.brand || "—";
}

export function TransferDetailPage() {
  const { id } = useParams();
  const { user } = useAuth();
  const { data: t, loading } = useDoc<TransferT>(`/outbound/transfers/${id}`);
  const writable = canWriteTransfer(user);
  const [scanMode, setScanMode] = useState<"" | "dispatch" | "receive">("");
  const [posting, setPosting] = useState(false);
  const [scanError, setScanError] = useState("");

  if (loading || !t) return <div className="page-pad"><p className="lead">Loading…</p></div>;

  const canDispatch = t.docstatus === 0 && writable;
  const canReceive = t.docstatus === 1 && !t.receipt && writable;
  const hasPlan = t.lines.some((l) => l.qty_planned != null);

  // Dispatch scans against the plan (or builds the lines when there is none);
  // receive scans against what was sent. The scans are the only quantities.
  const dispatchTargets: ScanTarget[] = t.lines
    .filter((l) => l.qty_planned != null)
    .map((l) => ({ barcode: l.sku_code, label: lineLabel(l), expected: l.qty_planned }));
  const receiveTargets: ScanTarget[] = t.lines
    .filter((l) => l.qty_dispatched > 0)
    .map((l) => ({ barcode: l.sku_code, label: lineLabel(l), expected: l.qty_dispatched }));

  async function lookupAtSource(barcode: string): Promise<ScanTarget | null> {
    try {
      const { data } = await api.get(
        `/outbound/scan-lookup?store=${t!.source_store}&barcode=${encodeURIComponent(barcode)}`,
      );
      return {
        barcode: data.barcode,
        label: [data.design, data.color, data.size].filter(Boolean).join(" · ") || data.brand,
        expected: null,
        available: data.available_qty,
      };
    } catch {
      return null;
    }
  }

  async function postScans(action: "dispatch" | "receive", scans: Record<string, number>) {
    setScanError("");
    setPosting(true);
    try {
      await api.post(`/outbound/transfers/${t!.id}/${action}`, {
        scans: Object.entries(scans).map(([barcode, qty]) => ({ barcode, qty })),
      });
      window.location.reload();
    } catch (e) {
      setScanError(apiErrorMessage(e));
      setPosting(false);
    }
  }

  const totalDispatched = t.lines.reduce((s, l) => s + l.qty_dispatched, 0);
  const totalReceived = t.lines.reduce((s, l) => s + l.qty_received, 0);
  const totalInTransit = t.docstatus === 1 ? totalDispatched - totalReceived : 0;

  return (
    <div className="page-pad">
      <Link to="/transfer" className="btn" style={{ marginBottom: 16 }} data-testid="transfer-detail-back">
        <ArrowLeft size={15} /> Transfers
      </Link>
      <div className="toolbar">
        <div>
          <p className="eyebrow">{t.doc_number || `Draft #${t.id}`}</p>
          <h1 className="h1">{t.source_store_code} → {t.destination_store_code}</h1>
          <p className="lead">
            {t.source_store_name} → {t.destination_store_name}
            {t.reason ? ` · ${REASON_OPTIONS.find((r) => r.value === t.reason)?.label || t.reason}` : ""}
          </p>
        </div>
        <div className="spacer" />
        <DocPill ds={t.docstatus} />
        {t.is_cross_state && <span className="chip chip-amber">Cross-state</span>}
        <span className="chip chip-navy">{TRANSFER_TYPE_LABEL[t.transfer_type] ?? t.transfer_type}</span>
        {t.docstatus === 1 && t.dispatch_mismatch && (
          <span className="chip chip-amber" data-testid="dispatch-mismatch-chip">Plan mismatch</span>
        )}
        {canDispatch && (
          <button
            type="button"
            className="btn btn-cta"
            onClick={() => { setScanError(""); setScanMode("dispatch"); }}
            data-testid="dispatch-transfer-btn"
          >
            <Send size={15} /> Scan &amp; dispatch
          </button>
        )}
        {canReceive && (
          <button
            type="button"
            className="btn btn-cta"
            onClick={() => { setScanError(""); setScanMode("receive"); }}
            data-testid="receive-transfer-toggle"
          >
            <PackageCheck size={15} /> Scan &amp; receive
          </button>
        )}
      </div>

      {scanMode === "dispatch" && (
        <ScanScreen
          mode="DISPATCH"
          docLabel={t.doc_number || `Draft #${t.id}`}
          routeLabel={`${t.source_store_code} → ${t.destination_store_code}`}
          targets={dispatchTargets}
          lookup={hasPlan ? undefined : lookupAtSource}
          confirmLabel="Confirm dispatch"
          busy={posting}
          error={scanError}
          onConfirm={(scans) => void postScans("dispatch", scans)}
          onClose={() => setScanMode("")}
        />
      )}
      {scanMode === "receive" && (
        <ScanScreen
          mode="RECEIVE"
          docLabel={t.doc_number || `Draft #${t.id}`}
          routeLabel={`${t.source_store_code} → ${t.destination_store_code}`}
          targets={receiveTargets}
          strictExpected
          confirmLabel="Confirm receipt"
          busy={posting}
          error={scanError}
          onConfirm={(scans) => void postScans("receive", scans)}
          onClose={() => setScanMode("")}
        />
      )}

      {/* Stats row */}
      <div className="form-row" style={{ marginBottom: 18 }}>
        <div className="card section-card">
          <p className="eyebrow">Transport</p>
          <h3 className="h3">{TRANSPORT_OPTIONS.find((o) => o.value === t.transport_mode)?.label || t.transport_mode || "—"}</h3>
          {t.transport_ref && <p className="lead" style={{ marginTop: 4 }}>{t.transport_ref}</p>}
        </div>
        <div className="card section-card">
          <p className="eyebrow">Dispatcher</p>
          <h3 className="h3">{t.dispatcher_name || "—"}</h3>
          {t.expected_arrival_note && <p className="lead" style={{ marginTop: 4 }}>{t.expected_arrival_note}</p>}
        </div>
        <div className="card section-card">
          <p className="eyebrow">Dispatched / Received</p>
          <h3 className="h3">{totalDispatched} / {totalReceived} pcs</h3>
          {totalInTransit > 0 && (
            <p className="lead" style={{ marginTop: 4 }} data-testid="in-transit-count">
              <b>{totalInTransit} pcs in transit</b>
            </p>
          )}
        </div>
        <div className="card section-card">
          <p className="eyebrow">Date</p>
          <h3 className="h3">{fmtDate(t.created_at)}</h3>
        </div>
      </div>

      {t.eway_bill_number && (
        <div className="card section-card" style={{ marginBottom: 18 }}>
          <p className="eyebrow">E-way bill</p>
          <h3 className="h3 mono">{t.eway_bill_number}</h3>
        </div>
      )}

      {/* Receipt info */}
      {t.receipt && (
        <div className="card section-card" style={{ marginBottom: 18 }} data-testid="transfer-receipt-info">
          <p className="eyebrow">Receipt</p>
          <div style={{ display: "flex", gap: 16, alignItems: "center" }}>
            <span className={`chip chip-${RECEIPT_TONE[t.receipt.receipt_status] ?? "grey"}`}>
              {t.receipt.receipt_status}
            </span>
            <span className="lead">{fmtDate(t.receipt.receipt_date)}</span>
            {t.receipt.shortfall_notes && <span className="lead">{t.receipt.shortfall_notes}</span>}
          </div>
        </div>
      )}

      {/* Lines table — quantities are scan-derived, never typed */}
      <div className="table-wrap">
        <table className="data" data-testid="transfer-detail-lines">
          <thead>
            <tr>
              <th>SKU</th>
              <th>Design</th>
              <th>Size</th>
              <th>Colour</th>
              <th>Brand</th>
              <th className="num">Planned</th>
              <th className="num">Dispatched</th>
              <th className="num">Received</th>
              <th className="num">In transit</th>
              <th className="num">Cost</th>
            </tr>
          </thead>
          <tbody>
            {t.lines.map((l) => (
              <tr key={l.id}>
                <td><b className="mono">{l.sku_code}</b></td>
                <td>{l.design || "—"}</td>
                <td>{l.size || "—"}</td>
                <td>{l.color || "—"}</td>
                <td>{l.brand || "—"}</td>
                <td className="num">{l.qty_planned ?? "—"}</td>
                <td className="num">
                  {l.qty_dispatched}
                  {t.docstatus === 1 && l.qty_planned != null && l.qty_planned !== l.qty_dispatched && (
                    <span className="chip chip-amber" style={{ marginLeft: 6 }}>≠ plan</span>
                  )}
                </td>
                <td className="num">{l.qty_received}</td>
                <td className="num">
                  {t.docstatus === 1 && l.qty_in_transit > 0 ? (
                    <b data-testid={`line-in-transit-${l.id}`}>{l.qty_in_transit}</b>
                  ) : (
                    "—"
                  )}
                </td>
                <td className="num">{l.unit_cost_paise ? <Money paise={l.unit_cost_paise} /> : "—"}</td>
              </tr>
            ))}
            {t.lines.length === 0 && (
              <tr>
                <td colSpan={10} style={{ textAlign: "center", opacity: 0.7 }}>
                  No lines yet — this transfer builds its lines by scanning at dispatch.
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}
