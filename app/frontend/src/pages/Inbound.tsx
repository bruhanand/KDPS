import { useEffect, useMemo, useState } from "react";
import { Link, useNavigate, useParams, useSearchParams } from "react-router-dom";
import {
  ArrowLeft,
  Boxes,
  FileSpreadsheet,
  FileUp,
  Lock,
  PackageCheck,
  Plus,
  Sparkles,
  Store as StoreIcon,
  Trash2,
} from "lucide-react";

import { api, apiErrorMessage } from "../lib/api";
import { useAuth } from "../auth/AuthContext";
import { useDoc, useList } from "../lib/hooks";
import { useMakePt } from "../components/InboundQueueCard";
import { ListSearchBar } from "../components/SearchBox";
import "./Booking.css";
import { PageHeader } from "../components/PageHeader";

const GRN_TONE: Record<string, string> = {
  received: "green",
  sent_to_ho: "amber",
  inwarded: "blue",
};

// Who may start a PT from an arrival — mirrors the backend MAPPING_STEWARD_ROLES.
const PT_MAKER_ROLES = new Set(["warehouse", "data_steward", "ho_ops", "owner", "it_admin"]);

function GrnPill({ status, label }: { status: string; label?: string }) {
  return <span className={`chip chip-${GRN_TONE[status] ?? "grey"} status-pill`}>{label ?? status}</span>;
}

interface GrnPtFileT {
  id: number;
  original_filename: string;
  source: string;
  stage: string;
  stage_label: string;
  doc_number: string | null;
  blank_cell_count: number;
  row_count: number;
}

interface StoreT {
  id: number;
  code: string;
  name: string;
  store_type: string;
  state_name: string;
}
interface PendingBookingT {
  id: number;
  number: string;
  brand_name: string;
  vendor_name: string;
  season_code: string;
  destination_store: number | null;
  destination_store_name: string | null;
  booked_total: number;
  received_total: number;
  lines: {
    id: number;
    style_code: string;
    size: string;
    description: string;
    booked_qty: number;
    received_qty: number;
  }[];
}
interface GrnListItemT {
  id: number;
  number: string;
  booking_number: string | null;
  vendor_name: string;
  store_code: string;
  store_name: string;
  received_at: string;
  status: string;
  status_label: string;
  is_direct: boolean;
  invoice_number: string;
  received_total: number;
  created_at: string;
}

function fmtDate(iso: string): string {
  return new Date(iso).toLocaleDateString("en-IN", { day: "numeric", month: "short", year: "numeric" });
}

export type ReceiveFlow = "branded" | "nonbranded";

/** The receive flows the unit you are standing in actually has (#228).
 *
 *  Only branded goods arrive at a store - the server refuses a non-branded
 *  receipt anywhere but a warehouse - so at a store the choice is not hidden,
 *  it does not exist. A warehouse takes both. No single active unit (an owner
 *  on "All units") keeps both too: the choice is still real there, and the
 *  server decides the rest at the store the receipt names.
 *
 *  Written as "only a warehouse gets the second flow", not "only a store loses
 *  it": KDPS has two unit types today, and a third one added later (an office)
 *  must inherit the narrower screen, not the wider one. */
export function receiveFlows(activeStore: { store_type: string } | null): ReceiveFlow[] {
  if (!activeStore) return ["branded", "nonbranded"];
  return activeStore.store_type === "warehouse" ? ["branded", "nonbranded"] : ["branded"];
}

/** The flow the URL asks for, clamped to the ones this unit has. Clamped rather
 *  than merely defaulted: switching from the warehouse to a store leaves
 *  `?tab=nonbranded` behind in the URL, and honouring it would put a store
 *  person back on a flow their screen no longer offers. */
export function activeFlow(flows: ReceiveFlow[], tabParam: string | null): ReceiveFlow {
  const asked: ReceiveFlow = tabParam === "nonbranded" ? "nonbranded" : "branded";
  return flows.includes(asked) ? asked : "branded";
}

export function InboundPage() {
  const [params, setParams] = useSearchParams();
  const { activeStore } = useAuth();
  const flows = receiveFlows(activeStore);
  const tab = activeFlow(flows, params.get("tab"));
  const kind = tab === "nonbranded" ? "non_branded" : "branded";

  const [q, setQ] = useState("");
  const { data: grns, loading } = useList<GrnListItemT>("/inbound/grns", { kind, q });
  const { data: pending } = useList<PendingBookingT>("/inbound/pending");

  function setTab(next: ReceiveFlow) {
    setParams((p) => {
      p.set("tab", next);
      return p;
    });
  }

  return (
    <div className="page-pad">
      <PageHeader
        actions={
          <Link
            className="btn btn-cta"
            to={`/receive/new?kind=${tab}`}
            data-testid="new-receipt-btn"
          >
            <Plus size={16} /> New receipt
          </Link>
        }
      />

      {/* No "(at store)" / "(at warehouse)" any more: the topbar already says
          which unit you are standing in, and the toggle is only drawn where both
          flows exist. */}
      {flows.length > 1 && (
        <div className="mode-toggle" data-testid="receive-tab-toggle" style={{ maxWidth: 520, marginBottom: 18 }}>
          <button
            type="button"
            className={`mode-btn ${tab === "branded" ? "active" : ""}`}
            onClick={() => setTab("branded")}
            data-testid="receive-tab-branded"
          >
            <StoreIcon size={16} /> Branded
          </button>
          <button
            type="button"
            className={`mode-btn ${tab === "nonbranded" ? "active" : ""}`}
            onClick={() => setTab("nonbranded")}
            data-testid="receive-tab-nonbranded"
          >
            <Boxes size={16} /> Non-branded
          </button>
        </div>
      )}

      {tab === "branded" && pending.length > 0 && (
        <div className="section-card card">
          <p className="eyebrow">Awaiting receipt</p>
          <h3 className="h3" style={{ marginBottom: 12 }}>Pending bookings</h3>
          <div className="card-grid" data-testid="pending-bookings-grid">
            {pending.map((b) => {
              const remaining = b.booked_total - b.received_total;
              return (
                <Link
                  key={b.id}
                  to={`/receive/new?booking=${b.id}`}
                  className="card bk-card"
                  data-testid={`pending-booking-${b.number}`}
                >
                  <div className="bk-card-top">
                    <span className="bk-num">{b.number}</span>
                    <span className="chip chip-amber status-pill">{remaining} pcs left</span>
                  </div>
                  <div className="bk-brand">{b.brand_name}</div>
                  <div className="bk-meta">
                    {b.vendor_name} · {b.season_code}
                    {b.destination_store_name ? ` · → ${b.destination_store_name}` : " · → Warehouse"}
                  </div>
                  <div className="receive-cta"><PackageCheck size={15} /> Receive against this booking</div>
                </Link>
              );
            })}
          </div>
        </div>
      )}

      <ListSearchBar
        value={q}
        onChange={setQ}
        placeholder="Search receipts — GRN number, vendor, brand"
        label="Search receipts"
        testId="grn-search"
        noun="receipt"
        count={grns.length}
        loading={loading}
      />

      {loading ? (
        <p className="lead">Loading…</p>
      ) : grns.length === 0 ? (
        <div className="card section-card" data-testid="grn-empty">
          {q
            ? `No receipt matches “${q}”.`
            : tab === "branded"
              ? "No branded goods received yet. Start a new receipt against a booking."
              : "No non-branded goods received yet. Start a direct receipt at a warehouse."}
        </div>
      ) : (
        <div className="table-wrap">
          <table className="data" data-testid="grn-table">
            <thead>
              <tr>
                <th>GRN</th>
                <th>Source</th>
                <th>Vendor</th>
                <th>Store</th>
                <th className="num">Received</th>
                <th>Status</th>
                <th>Date</th>
              </tr>
            </thead>
            <tbody>
              {grns.map((g) => (
                <tr key={g.id} data-testid={`grn-row-${g.number}`}>
                  <td>
                    <Link to={`/receive/${g.id}`} className="link-cell mono" data-testid={`grn-detail-link-${g.number}`}>
                      <b>{g.number}</b>
                    </Link>
                  </td>
                  <td>
                    {g.is_direct ? (
                      <span className="chip chip-purple">Direct</span>
                    ) : (
                      <span className="mono" style={{ fontSize: 12.5 }}>{g.booking_number}</span>
                    )}
                  </td>
                  <td>{g.vendor_name || "—"}</td>
                  <td>
                    <b className="mono">{g.store_code}</b>
                    <span className={`chip chip-${g.received_at === "warehouse" ? "navy" : "green"}`} style={{ marginLeft: 8 }}>
                      {g.received_at}
                    </span>
                  </td>
                  <td className="num">{g.received_total}</td>
                  <td><GrnPill status={g.status} label={g.status_label} /></td>
                  <td>{fmtDate(g.created_at)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

interface ReceiveLine {
  booking_line_id: number | null;
  style_code: string;
  size: string;
  color: string;
  barcode: string;
  booked_qty?: number;
  received_qty: number | string;
  damaged_qty: number | string;
  is_variance?: boolean;
  remark: string;
}
const emptyReceiveLine = (): ReceiveLine => ({
  booking_line_id: null,
  style_code: "",
  size: "",
  color: "",
  barcode: "",
  received_qty: "",
  damaged_qty: "",
  remark: "",
});

function aiToLine(a: any): ReceiveLine {
  return {
    booking_line_id: null,
    style_code: a.style_code || "",
    size: a.size || "",
    color: a.color || "",
    barcode: a.barcode || "",
    received_qty: a.quantity ?? "",
    damaged_qty: "",
    remark: "",
  };
}

export function InboundNewPage() {
  const navigate = useNavigate();
  const [params] = useSearchParams();
  const { user } = useAuth();

  const { data: pending } = useList<PendingBookingT>("/inbound/pending");
  const { data: stores } = useList<StoreT>("/masters/stores");

  // Non-branded goods are received directly at a warehouse — no booking, warehouse-only.
  const isNonBranded = params.get("kind") === "nonbranded";
  const storeOptions = useMemo(
    () => (isNonBranded ? stores.filter((s) => s.store_type === "warehouse") : stores),
    [stores, isNonBranded],
  );

  const storeLocked = user?.scope_type === "store" && (user?.stores?.length ?? 0) >= 1;
  const lockedStore = storeLocked ? user!.stores[0] : null;

  // Non-branded intake is warehouse-only (the backend fail-closes on it). A store-scoped
  // user is pinned to their own store, which may not be a warehouse — spot it here so they
  // get a clear message instead of a raw 400 on submit.
  const nonBrandedStoreInvalid =
    isNonBranded && !!lockedStore && lockedStore.store_type !== "warehouse";

  // Non-branded is always a direct receipt; branded opens in booking mode only when a
  // booking id was passed in the URL.
  let initialMode: "booking" | "direct" = "direct";
  if (!isNonBranded && params.get("booking")) initialMode = "booking";
  const [mode, setMode] = useState<"booking" | "direct">(initialMode);
  const [bookingId, setBookingId] = useState(params.get("booking") ?? "");
  const [storeId, setStoreId] = useState<string>(lockedStore ? String(lockedStore.id) : "");
  const [vendorName, setVendorName] = useState("");
  const [invoiceNumber, setInvoiceNumber] = useState("");
  const [invoiceFileId, setInvoiceFileId] = useState<number | null>(null);
  const [lines, setLines] = useState<ReceiveLine[]>([emptyReceiveLine()]);

  const [reading, setReading] = useState(false);
  const [aiNote, setAiNote] = useState("");
  const [warn, setWarn] = useState("");
  const [error, setError] = useState("");
  const [saving, setSaving] = useState(false);

  const selectedBooking = useMemo(
    () => pending.find((b) => String(b.id) === String(bookingId)) ?? null,
    [pending, bookingId],
  );

  // Prefill receive lines + store from the chosen booking.
  useEffect(() => {
    if (mode !== "booking" || !selectedBooking) return;
    setLines(
      selectedBooking.lines.map((l) => ({
        booking_line_id: l.id,
        style_code: l.style_code,
        size: l.size,
        color: "",
        barcode: "",
        booked_qty: l.booked_qty,
        received_qty: Math.max(0, l.booked_qty - l.received_qty),
        damaged_qty: "",
        remark: "",
      })),
    );
    if (selectedBooking.destination_store && !storeLocked) {
      setStoreId(String(selectedBooking.destination_store));
    }
  }, [selectedBooking, mode, storeLocked]);

  function setLine(i: number, key: keyof ReceiveLine, val: string) {
    setLines((ls) => ls.map((l, idx) => (idx === i ? { ...l, [key]: val } : l)));
  }

  function switchMode(next: "booking" | "direct") {
    setMode(next);
    setWarn("");
    setAiNote("");
    setError("");
    if (next === "direct") {
      setBookingId("");
      setLines([emptyReceiveLine()]);
    }
  }

  async function handleInvoice(file: File) {
    setReading(true);
    setWarn("");
    setAiNote("");
    setError("");
    const form = new FormData();
    form.append("file", file);
    try {
      const { data } = await api.post("/inbound/invoice-draft", form);
      setInvoiceFileId(data.invoice_file_id ?? null);
      if (data.invoice_number) setInvoiceNumber(data.invoice_number);
      if (mode === "direct" && !bookingId) {
        if (data.vendor_name && !vendorName) setVendorName(data.vendor_name);
        const got: ReceiveLine[] = (data.lines || []).map(aiToLine);
        if (got.length) setLines(got);
        setAiNote(
          `Gemini read ${got.length} line(s)${data.confidence ? ` · confidence ${Math.round(data.confidence * 100)}%` : ""}. Count physically and confirm.`,
        );
      } else {
        // booking mode: match AI lines onto the booking lines, append the rest as variances.
        const ai = (data.lines || []) as any[];
        setLines((prev) => {
          const next = prev.map((l) => ({ ...l }));
          const leftover: ReceiveLine[] = [];
          for (const a of ai) {
            const idx = next.findIndex(
              (l) =>
                l.style_code.toLowerCase() === String(a.style_code || "").toLowerCase() &&
                String(l.size || "").toLowerCase() === String(a.size || "").toLowerCase(),
            );
            if (idx >= 0) {
              if (a.quantity != null) next[idx].received_qty = a.quantity;
              if (a.color) next[idx].color = a.color;
              if (a.barcode) next[idx].barcode = a.barcode;
            } else {
              leftover.push({ ...aiToLine(a), is_variance: true });
            }
          }
          return [...next, ...leftover];
        });
        setAiNote(`Invoice attached. Gemini matched ${ai.length} line(s) onto the booking — review counts before confirming.`);
      }
    } catch (e: any) {
      setInvoiceFileId(e?.response?.data?.invoice_file_id ?? null);
      setWarn(e?.response?.data?.detail || "Could not read the invoice — attach it and count the lines manually.");
    } finally {
      setReading(false);
    }
  }

  async function save() {
    setError("");
    if (nonBrandedStoreInvalid) {
      setError("Non-branded goods can only be received at a warehouse. Use the branded tab, or have an admin receive this at a warehouse.");
      return;
    }
    if (!storeId) {
      setError("Pick the store/warehouse where goods were received.");
      return;
    }
    if (mode === "booking" && !bookingId) {
      setError("Pick the booking you are receiving against.");
      return;
    }
    const payloadLines = lines
      .filter((l) => l.style_code && (Number(l.received_qty) > 0 || Number(l.damaged_qty) > 0))
      .map((l) => ({
        booking_line_id: l.booking_line_id,
        style_code: l.style_code,
        size: l.size,
        color: l.color,
        barcode: l.barcode,
        received_qty: Number(l.received_qty) || 0,
        damaged_qty: Number(l.damaged_qty) || 0,
        is_variance: Boolean(l.is_variance),
        remark: l.remark,
      }));
    if (!payloadLines.length) {
      setError("Add at least one line with a received or damaged quantity.");
      return;
    }
    setSaving(true);
    try {
      const { data } = await api.post("/inbound/grns", {
        store_id: Number(storeId),
        kind: isNonBranded ? "non_branded" : "branded",
        booking_id: mode === "booking" && bookingId ? Number(bookingId) : null,
        vendor_name: mode === "direct" ? vendorName : "",
        invoice_number: invoiceNumber,
        invoice_file_id: invoiceFileId,
        lines: payloadLines,
      });
      navigate(`/receive/${data.id}`);
    } catch (e) {
      setError(apiErrorMessage(e));
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="page-pad">
      <Link
        to={`/receive?tab=${isNonBranded ? "nonbranded" : "branded"}`}
        className="btn"
        style={{ marginBottom: 16 }}
        data-testid="receive-back-link"
      >
        <ArrowLeft size={15} /> Stock Receive
      </Link>
      <h1 className="h1 h2-rust" style={{ marginBottom: 18 }}>
        New {isNonBranded ? "non-branded" : "branded"} receipt
      </h1>

      <div className="card section-card">
        <p className="eyebrow">
          Step 1 · What are you receiving?
          {isNonBranded && <span className="chip chip-navy" style={{ marginLeft: 8 }}>Non-branded · warehouse</span>}
        </p>
        {!isNonBranded && (
          <div className="mode-toggle" data-testid="receipt-mode-toggle">
            <button
              type="button"
              className={`mode-btn ${mode === "booking" ? "active" : ""}`}
              onClick={() => switchMode("booking")}
              data-testid="mode-booking"
            >
              <Boxes size={16} /> Against a booking
            </button>
            <button
              type="button"
              className={`mode-btn ${mode === "direct" ? "active" : ""}`}
              onClick={() => switchMode("direct")}
              data-testid="mode-direct"
            >
              <PackageCheck size={16} /> Direct receipt (no booking)
            </button>
          </div>
        )}

        {mode === "booking" ? (
          <div className="field" style={{ marginTop: 14, maxWidth: 480 }}>
            <label>Booking</label>
            <select
              className="select"
              value={bookingId}
              onChange={(e) => setBookingId(e.target.value)}
              data-testid="receive-booking-select"
            >
              <option value="">Select a pending booking…</option>
              {pending.map((b) => (
                <option key={b.id} value={b.id}>
                  {b.number} · {b.brand_name} · {b.booked_total - b.received_total} pcs left
                </option>
              ))}
            </select>
            {pending.length === 0 && (
              <p className="lead" style={{ fontSize: 13, marginTop: 6 }}>
                No pending bookings for you. Use a direct receipt instead.
              </p>
            )}
          </div>
        ) : (
          <div className="field" style={{ marginTop: 14, maxWidth: 480 }}>
            <label>Vendor / brand (free text)</label>
            <input
              className="input"
              value={vendorName}
              onChange={(e) => setVendorName(e.target.value)}
              placeholder="e.g. Levi's India Pvt Ltd"
              data-testid="receive-vendor-name"
            />
          </div>
        )}
      </div>

      <div className="card section-card">
        <p className="eyebrow">Step 2 · Where &amp; against what</p>
        <div className="form-row" style={{ marginTop: 10 }}>
          <div className="field">
            <label>Receiving store / warehouse</label>
            {storeLocked && lockedStore ? (
              <>
                <div className="store-lock" data-testid="receive-store-locked">
                  <Lock size={14} /> {lockedStore.code} · {lockedStore.name}
                </div>
                {nonBrandedStoreInvalid && (
                  <p className="warn-note" style={{ marginTop: 6 }} data-testid="nonbranded-store-warn">
                    Non-branded goods are received only at a warehouse — this store can't be used here.
                  </p>
                )}
              </>
            ) : (
              <select
                className="select"
                value={storeId}
                onChange={(e) => setStoreId(e.target.value)}
                data-testid="receive-store-select"
              >
                <option value="">{isNonBranded ? "Select warehouse…" : "Select store / warehouse…"}</option>
                {storeOptions.map((s) => (
                  <option key={s.id} value={s.id}>
                    {s.code} · {s.name} {s.store_type === "warehouse" ? "(WH)" : ""}
                  </option>
                ))}
              </select>
            )}
          </div>
          <div className="field">
            <label>Invoice number</label>
            <input
              className="input"
              value={invoiceNumber}
              onChange={(e) => setInvoiceNumber(e.target.value)}
              placeholder="Supplier invoice no."
              data-testid="receive-invoice-number"
            />
          </div>
        </div>

        <p className="eyebrow" style={{ marginTop: 18 }}>Invoice / packing list (optional)</p>
        <label className="dropzone" data-testid="invoice-dropzone">
          <input
            type="file"
            hidden
            accept="image/*,.pdf,.xlsx,.xls,.csv"
            onChange={(e) => e.target.files && handleInvoice(e.target.files[0])}
            data-testid="invoice-file-input"
          />
          {reading ? (
            <span><Sparkles size={18} /> Reading invoice with Gemini…</span>
          ) : invoiceFileId ? (
            <span><FileUp size={18} /> Invoice attached · upload a different file</span>
          ) : (
            <span><FileUp size={18} /> Drop the invoice photo / PDF / Excel to prefill counts</span>
          )}
        </label>
        {aiNote && <div className="ai-note" data-testid="invoice-ai-note"><Sparkles size={14} /> {aiNote}</div>}
        {warn && <div className="warn-note" data-testid="invoice-ai-warn">{warn}</div>}
      </div>

      <div className="card section-card">
        <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 10 }}>
          <div>
            <p className="eyebrow">Step 3 · Count the goods</p>
            <h3 className="h3">Received lines</h3>
          </div>
          <button type="button" className="btn" onClick={() => setLines((l) => [...l, { ...emptyReceiveLine(), is_variance: mode === "booking" }])} data-testid="add-receive-line">
            <Plus size={15} /> Add line
          </button>
        </div>
        <table className="lines-table" data-testid="receive-lines">
          <thead>
            <tr>
              <th style={{ width: "22%" }}>Style code</th>
              <th>Size</th>
              <th>Colour</th>
              <th>Barcode</th>
              {mode === "booking" && <th className="num">Booked</th>}
              <th className="num">Received</th>
              <th className="num">Damaged</th>
              <th />
            </tr>
          </thead>
          <tbody>
            {lines.map((l, i) => (
              <tr key={i} className={l.is_variance ? "variance-row" : ""}>
                <td>
                  <input value={l.style_code} onChange={(e) => setLine(i, "style_code", e.target.value)} data-testid={`rl-style-${i}`} />
                  {l.is_variance && <span className="variance-tag">variance</span>}
                </td>
                <td><input value={l.size} onChange={(e) => setLine(i, "size", e.target.value)} data-testid={`rl-size-${i}`} /></td>
                <td><input value={l.color} onChange={(e) => setLine(i, "color", e.target.value)} data-testid={`rl-color-${i}`} /></td>
                <td><input value={l.barcode} onChange={(e) => setLine(i, "barcode", e.target.value)} data-testid={`rl-barcode-${i}`} /></td>
                {mode === "booking" && <td className="num booked-cell">{l.booked_qty ?? "—"}</td>}
                <td><input className="num" value={l.received_qty} onChange={(e) => setLine(i, "received_qty", e.target.value)} data-testid={`rl-received-${i}`} /></td>
                <td><input className="num" value={l.damaged_qty} onChange={(e) => setLine(i, "damaged_qty", e.target.value)} data-testid={`rl-damaged-${i}`} /></td>
                <td><button type="button" className="line-del" onClick={() => setLines((ls) => ls.filter((_, idx) => idx !== i))} data-testid={`delete-receive-line-${i}`}><Trash2 size={15} /></button></td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {error && <div className="login-error" style={{ maxWidth: 480 }} data-testid="receive-error">{error}</div>}
      <button className="btn btn-primary btn-lg" disabled={saving || nonBrandedStoreInvalid} onClick={save} data-testid="confirm-grn">
        <StoreIcon size={16} /> {saving ? "Saving…" : "Confirm receipt (GRN)"}
      </button>
    </div>
  );
}

interface GrnDetailT {
  id: number;
  number: string;
  booking_number: string | null;
  vendor_name: string;
  store_code: string;
  store_name: string;
  received_at: string;
  status: string;
  status_label: string;
  is_direct: boolean;
  invoice_number: string;
  notes: string;
  received_total: number;
  created_at: string;
  pt_files: GrnPtFileT[];
  lines: {
    id: number;
    style_code: string;
    size: string;
    color: string;
    barcode: string;
    received_qty: number;
    damaged_qty: number;
    is_variance: boolean;
    remark: string;
  }[];
}

const PT_STAGE_TONE: Record<string, string> = {
  mapping: "blue",
  sent: "amber",
  posted: "green",
  reversed: "grey",
};

export function GrnDetailPage() {
  const { id } = useParams();
  const { user } = useAuth();
  const { data: g, loading } = useDoc<GrnDetailT>(`/inbound/grns/${id}`);
  const { makePt, makingId, error: makeError } = useMakePt();
  if (loading || !g) return <div className="page-pad"><p className="lead">Loading…</p></div>;
  const canMakePt = PT_MAKER_ROLES.has(user?.role?.code ?? "");
  const livePt = (g.pt_files ?? []).find((p) => p.stage !== "reversed") ?? null;
  return (
    <div className="page-pad">
      <Link to="/receive" className="btn" style={{ marginBottom: 16 }} data-testid="grn-detail-back-link">
        <ArrowLeft size={15} /> Stock Receive
      </Link>
      <div className="toolbar">
        <div>
          <p className="eyebrow">{g.number}</p>
          <h1 className="h1">{g.vendor_name || "Direct receipt"}</h1>
          <p className="lead">
            {g.store_code} · {g.store_name}
            {g.booking_number ? ` · booking ${g.booking_number}` : " · no booking"}
            {g.invoice_number ? ` · invoice ${g.invoice_number}` : ""}
          </p>
        </div>
        <div className="spacer" />
        {g.is_direct && <span className="chip chip-purple">Direct</span>}
        <GrnPill status={g.status} label={g.status_label} />
        {canMakePt && !livePt && (
          <button
            type="button"
            className="btn btn-cta"
            disabled={makingId === g.id}
            onClick={() => makePt(g.id)}
            data-testid="grn-make-pt"
          >
            <FileSpreadsheet size={15} /> {makingId === g.id ? "Making…" : "Make PT file"}
          </button>
        )}
      </div>
      {makeError && <div className="warn-note" data-testid="grn-make-pt-error">{makeError}</div>}

      {(g.pt_files ?? []).length > 0 && (
        <div className="card section-card" data-testid="grn-pt-files">
          <p className="eyebrow">PT files for this arrival</p>
          {g.pt_files.map((p) => (
            <div key={p.id} style={{ display: "flex", gap: 10, alignItems: "center", padding: "6px 0" }}>
              <FileSpreadsheet size={14} style={{ color: "var(--rust)" }} />
              <Link to={`/receive/pt/${p.id}`} className="link-cell" data-testid={`grn-pt-link-${p.id}`}>
                <b>{p.original_filename}</b>
              </Link>
              {p.doc_number && <span className="mono" style={{ fontSize: 12.5 }}>{p.doc_number}</span>}
              <span className={`chip chip-${PT_STAGE_TONE[p.stage] ?? "grey"}`}>{p.stage_label}</span>
              {p.stage !== "posted" && p.blank_cell_count > 0 && (
                <span className="chip chip-grey">{p.blank_cell_count} blank cells</span>
              )}
            </div>
          ))}
        </div>
      )}

      <div className="form-row" style={{ marginBottom: 18 }}>
        <div className="card section-card"><p className="eyebrow">Received at</p><h3 className="h3" style={{ textTransform: "capitalize" }}>{g.received_at}</h3></div>
        <div className="card section-card"><p className="eyebrow">Total received</p><h3 className="h3">{g.received_total} pcs</h3></div>
        <div className="card section-card"><p className="eyebrow">Date</p><h3 className="h3">{fmtDate(g.created_at)}</h3></div>
      </div>

      <div className="table-wrap">
        <table className="data" data-testid="grn-detail-lines">
          <thead>
            <tr>
              <th>Style</th><th>Size</th><th>Colour</th><th>Barcode</th>
              <th className="num">Received</th><th className="num">Damaged</th><th>Remark</th>
            </tr>
          </thead>
          <tbody>
            {g.lines.map((l) => (
              <tr key={l.id} className={l.is_variance ? "variance-row" : ""}>
                <td>
                  <b className="mono">{l.style_code}</b>
                  {l.is_variance && <span className="variance-tag">variance</span>}
                </td>
                <td>{l.size || "—"}</td>
                <td>{l.color || "—"}</td>
                <td className="mono" style={{ fontSize: 12.5 }}>{l.barcode || "—"}</td>
                <td className="num">{l.received_qty}</td>
                <td className="num">{l.damaged_qty || "—"}</td>
                <td>{l.remark || "—"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
