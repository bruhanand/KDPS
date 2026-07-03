import { useEffect, useMemo, useState } from "react";
import { Link, useNavigate, useParams, useSearchParams } from "react-router-dom";
import {
  AlertTriangle,
  ArrowLeft,
  CheckCircle2,
  Download,
  FileSpreadsheet,
  FileUp,
  Filter,
  ListChecks,
  Lock,
  Pencil,
  Receipt,
  RefreshCw,
  RotateCcw,
  Save,
  Send,
  Sparkles,
  Undo2,
  Wand2,
  X,
} from "lucide-react";

import { useAuth } from "../auth/AuthContext";
import { Combobox } from "../components/Combobox";
import { InboundQueueCard, useInboundQueue } from "../components/InboundQueueCard";
import { api, apiErrorMessage } from "../lib/api";
import { useList } from "../lib/hooks";
import "./Booking.css";
import "./PtMapper.css";

const KDPS_COLUMNS = [
  "SEASON", "BRAND", "COLOR", "GENDER", "SUB CATEGORY", "TYPE", "ITEM", "FIT",
  "SIZE", "BARCODE", "DESIGN", "HSN", "QTY", "MRP", "BASIC", "P RATE",
  "INPUT TAX", "OUTPUT TAX", "NAG", "MARGIN", "SUGGESTED SUB CATEGORY", "SUGGESTED TYPE",
];
const NUM_COLS = ["QTY", "MRP", "BASIC", "P RATE", "INPUT TAX", "OUTPUT TAX", "NAG", "MARGIN"];

// KDPS column → ControlledValue dimension: these cells edit as a Master-Sheet
// dropdown, never free text (the Excel data-validation behaviour).
const COL_DIM: Record<string, string> = {
  SEASON: "season", BRAND: "brand", COLOR: "color", GENDER: "gender",
  "SUB CATEGORY": "sub_category", TYPE: "type", ITEM: "item", FIT: "fit", SIZE: "size",
  "INPUT TAX": "gst", "OUTPUT TAX": "gst",
};
// Derived / engine-suggestion columns — recomputed server-side, not hand-edited.
const READONLY_COLS = new Set(["NAG", "MARGIN", "SUGGESTED SUB CATEGORY", "SUGGESTED TYPE"]);
// Dimensions that resolve through a Lookup — so a fix on them can be "remembered"
// as a brand-scoped rule (matches learning.LEARNABLE_DIMS on the backend).
const LEARNABLE_DIMS = new Set(["season", "brand", "color", "gender", "fit", "size"]);
// Provenance → glance level: alias/rule/inferred = a judgement worth a look (amber),
// manual = a human decision (blue); direct/derived are trusted (no mark).
const GLANCE_PROV = new Set(["alias", "rule", "inferred"]);

interface VocabT {
  dimensions: Record<string, string[]>;
  item_taxonomy: Record<string, { sub_category: string; type: string }>;
}
const EMPTY_VOCAB: VocabT = { dimensions: {}, item_taxonomy: {} };

function useVocab(): VocabT {
  const [vocab, setVocab] = useState<VocabT>(EMPTY_VOCAB);
  useEffect(() => {
    api.get("/ptmapper/controlled").then((r) => setVocab(r.data)).catch(() => {});
  }, []);
  return vocab;
}

// Deterministic pre-fill suggestions (pg_trgm + exact lookups) for a raw value —
// Master values only, floated to the top of the dropdown; never auto-committed.
function useSuggestions(dimension: string, q: string, brand = ""): string[] {
  const [vals, setVals] = useState<string[]>([]);
  useEffect(() => {
    if (!dimension || !q) {
      setVals([]);
      return;
    }
    const params = new URLSearchParams({ dimension, q });
    if (brand) params.set("brand", brand);
    api
      .get(`/ptmapper/suggest?${params.toString()}`)
      .then((r) => setVals((r.data.suggestions ?? []).map((s: any) => s.value)))
      .catch(() => setVals([]));
  }, [dimension, q, brand]);
  return vals;
}

const FILE_TONE: Record<string, string> = { ready: "green", needs_review: "amber", failed: "red" };
const STAGE_TONE: Record<string, string> = { mapping: "blue", sent: "amber", posted: "green" };

interface PtFileT {
  id: number;
  original_filename: string;
  source: string;
  brand_guess: string;
  profile_code: string;
  profile_name: string;
  archetype: string;
  status: string;
  status_label: string;
  stage: string;
  stage_label: string;
  manually_edited: boolean;
  sent_at: string | null;
  posted_at: string | null;
  inward_doc_number: string;
  booking: number | null;
  booking_number: string;
  grn: number | null;
  grn_number: string;
  row_count: number;
  blank_cell_count: number;
  unresolved_count: number;
  error: string;
  created_at: string;
}

// A received GRN as the invoice-first picker needs it (D3): only arrivals that
// carry an invoice can anchor a brand PT.
interface GrnPickT {
  id: number;
  number: string;
  vendor_name: string;
  store_code: string;
  invoice_number: string;
  created_at: string;
}

function PtFileTable({ files, empty }: { files: PtFileT[]; empty: string }) {
  if (files.length === 0) {
    return <div className="card section-card" data-testid="pt-files-empty">{empty}</div>;
  }
  return (
    <div className="table-wrap">
      <table className="data" data-testid="pt-files-table">
        <thead>
          <tr>
            <th>File</th>
            <th>Profile</th>
            <th className="num">Rows</th>
            <th className="num">Unmapped</th>
            <th>Mapping</th>
            <th>Workflow</th>
            <th />
          </tr>
        </thead>
        <tbody>
          {files.map((f) => (
            <tr key={f.id} data-testid={`pt-file-row-${f.id}`}>
              <td>
                <FileSpreadsheet size={15} style={{ verticalAlign: "-2px", marginRight: 6, color: "var(--rust)" }} />
                <b>{f.original_filename}</b>
                {f.grn && <span className="chip chip-navy" style={{ marginLeft: 6 }}>GRN {f.grn_number || `#${f.grn}`}</span>}
              </td>
              <td>
                {f.profile_name || "—"}
                {f.archetype && <span className="chip chip-navy" style={{ marginLeft: 6 }}>{f.archetype}</span>}
              </td>
              <td className="num">{f.row_count}</td>
              <td className="num">
                {f.unresolved_count > 0 ? <span className="chip chip-amber">{f.unresolved_count}</span> : <span className="chip chip-green">0</span>}
              </td>
              <td><span className={`chip chip-${FILE_TONE[f.status] ?? "grey"}`}>{f.status_label}</span></td>
              <td><span className={`chip chip-${STAGE_TONE[f.stage] ?? "grey"}`} data-testid={`pt-file-stage-${f.id}`}>{f.stage_label}</span></td>
              <td>
                <Link className="btn btn-sm" to={`/documents/pt-mapper/${f.id}`} data-testid={`pt-file-view-${f.id}`}>Open</Link>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function fmtDate(iso: string): string {
  return new Date(iso).toLocaleDateString("en-IN", { day: "numeric", month: "short", year: "numeric" });
}

/** PT File Mapper — branded brand-PT → KDPS. Invoice-first entry (D3): pick the
 *  received invoice, then upload the brand PT so it is linked to that GRN. */
function MapperTab({ files, reload }: { files: PtFileT[]; reload: () => void }) {
  const navigate = useNavigate();
  const { data: grns } = useList<GrnPickT>("/inbound/grns");
  const vocab = useVocab();
  const [uploading, setUploading] = useState(false);
  const [error, setError] = useState("");
  const [ctxBrand, setCtxBrand] = useState("");
  const [ctxDate, setCtxDate] = useState("");
  // "" = still picking an invoice; "none" = mapping without one (escape hatch);
  // otherwise the chosen GRN id. Non-empty → the section is in mapping mode.
  const [selectedGrn, setSelectedGrn] = useState("");

  const invoiceGrns = useMemo(
    () => grns.filter((g) => (g.invoice_number || "").trim() !== ""),
    [grns],
  );
  const mapping = selectedGrn !== "";
  const grnId = selectedGrn && selectedGrn !== "none" ? selectedGrn : "";
  const chosen = useMemo(
    () => invoiceGrns.find((g) => String(g.id) === grnId) ?? null,
    [invoiceGrns, grnId],
  );

  async function handleFile(file: File) {
    setUploading(true);
    setError("");
    const form = new FormData();
    form.append("file", file);
    if (ctxBrand) form.append("brand", ctxBrand);
    if (ctxDate) form.append("invoice_date", ctxDate);
    if (grnId) form.append("grn", grnId);
    try {
      const { data } = await api.post("/ptmapper/files", form);
      reload();
      navigate(`/documents/pt-mapper/${data.id}`);
    } catch (e: any) {
      // The GRN already carries a live PT — jump straight to it rather than error.
      const existing = e?.response?.data?.pt_file_id;
      if (existing) {
        navigate(`/documents/pt-mapper/${existing}`);
        return;
      }
      setError(apiErrorMessage(e));
    } finally {
      setUploading(false);
    }
  }

  return (
    <>
      {!mapping ? (
        <div className="card section-card">
          <p className="eyebrow">Step 1 · Select the received invoice</p>
          <h3 className="h3" style={{ marginBottom: 4 }}>Which arrival is this brand PT for?</h3>
          <p className="lead" style={{ marginBottom: 14, fontSize: 13.5 }}>
            Pick the invoice you received in Stock Receive — the mapped PT is linked to that GRN so
            the goods and their pricing stay tied to the same arrival.
          </p>
          <div className="field" style={{ maxWidth: 520 }}>
            <label>Received invoice</label>
            <select
              className="select"
              value={grnId}
              onChange={(e) => setSelectedGrn(e.target.value)}
              data-testid="mapper-invoice-select"
            >
              <option value="">Select a received invoice…</option>
              {invoiceGrns.map((g) => (
                <option key={g.id} value={g.id}>
                  {g.number} · inv {g.invoice_number} · {g.vendor_name || "Direct"} · {g.store_code} · {fmtDate(g.created_at)}
                </option>
              ))}
            </select>
            {invoiceGrns.length === 0 && (
              <p className="lead" style={{ fontSize: 13, marginTop: 6 }}>
                No received invoices yet. Receive goods with an invoice in Stock Receive first, or map without one.
              </p>
            )}
          </div>
          <div style={{ display: "flex", gap: 10, marginTop: 14 }}>
            <button
              className="btn btn-cta"
              disabled={!grnId}
              onClick={() => setSelectedGrn(grnId || "")}
              data-testid="mapper-enter-mapping"
            >
              <Receipt size={15} /> Map this invoice
            </button>
            <button
              className="btn"
              onClick={() => setSelectedGrn("none")}
              data-testid="mapper-map-without-invoice"
            >
              Map without an invoice
            </button>
          </div>
        </div>
      ) : (
        <div className="card section-card">
          <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 6 }}>
            <p className="eyebrow" style={{ margin: 0 }}>
              Step 2 · Convert the brand PT → KDPS format
            </p>
            <div className="spacer" />
            {chosen ? (
              <span className="chip chip-navy" data-testid="mapper-selected-invoice">
                {chosen.number} · inv {chosen.invoice_number}
              </span>
            ) : (
              <span className="chip chip-grey" data-testid="mapper-no-invoice">No invoice linked</span>
            )}
            <button className="btn btn-sm" onClick={() => setSelectedGrn("")} data-testid="mapper-change-invoice">
              Change
            </button>
          </div>
          <h3 className="h3" style={{ marginBottom: 4 }}>Deterministic mapping · no AI</h3>
          <p className="lead" style={{ marginBottom: 14, fontSize: 13.5 }}>
            Upload the brand's PT file (.xlsx / .xls / .xlsb / .csv). Columns are mapped by table;
            anything the tables don't yet cover lands in the unmapped queue for a one-time human decision.
            Review &amp; edit the result, then send it to Patna to post into the system.
          </p>
          <div className="upload-context" data-testid="pt-upload-context">
            <div className="upload-context-field">
              <label className="upload-context-label">Brand (if the file names none)</label>
              <Combobox
                value={ctxBrand}
                options={vocab.dimensions.brand ?? []}
                onChange={setCtxBrand}
                placeholder="Optional — Master brand…"
                testId="pt-upload-brand"
              />
            </div>
            <div className="upload-context-field">
              <label className="upload-context-label">Invoice date (if the file has none)</label>
              <input
                type="date"
                className="input"
                value={ctxDate}
                onChange={(e) => setCtxDate(e.target.value)}
                data-testid="pt-upload-date"
              />
            </div>
          </div>
          <label className="dropzone" data-testid="pt-upload-dropzone">
            <input type="file" hidden accept=".xlsx,.xls,.xlsb,.csv" onChange={(e) => e.target.files && handleFile(e.target.files[0])} />
            {uploading ? (
              <span><RefreshCw size={18} className="spin" /> Mapping…</span>
            ) : (
              <span><FileUp size={18} /> Drop a brand PT file (.xlsx / .xls / .xlsb / .csv), or click to choose</span>
            )}
          </label>
          {error && <div className="warn-note" data-testid="pt-upload-error">{error}</div>}
        </div>
      )}

      <PtFileTable files={files} empty="No brand PT files mapped yet." />
    </>
  );
}

/** PT File Making — non-branded invoice → PT authoring. Hosts the "arrivals
 *  awaiting PT" work queue + the "Make PT file" button (moved off Stock Receive). */
function MakingTab({ files }: { files: PtFileT[] }) {
  const { queue } = useInboundQueue();
  return (
    <>
      {queue && <InboundQueueCard queue={queue} />}
      <PtFileTable files={files} empty="No PT files made from arrivals yet." />
    </>
  );
}

export function PtMapperPage() {
  const { data: files, loading, reload } = useList<PtFileT>("/ptmapper/files");
  const { data: reviews } = useList<any>("/ptmapper/review?status=open");
  const { data: proposals } = useList<any>("/ptmapper/proposals?status=proposed");
  const [params, setParams] = useSearchParams();
  const tab = params.get("tab") === "making" ? "making" : "mapper";

  function setTab(next: "mapper" | "making") {
    setParams((p) => {
      p.set("tab", next);
      return p;
    });
  }

  const brandFiles = useMemo(() => files.filter((f) => f.source !== "invoice"), [files]);
  const makingFiles = useMemo(() => files.filter((f) => f.source === "invoice"), [files]);

  return (
    <div className="page-pad">
      <div className="toolbar">
        <div>
          <p className="eyebrow">Documents · Warehouse (Ranchi) → Patna HO</p>
          <h1 className="h1 h2-rust">PT File Operation</h1>
        </div>
        <div className="spacer" />
        {tab === "mapper" && (
          <>
            <Link className="btn" to="/documents/pt-mapper/proposals" data-testid="proposals-link">
              <Sparkles size={16} /> Learning proposals
              {proposals.length > 0 && <span className="chip chip-green" style={{ marginLeft: 6 }}>{proposals.length}</span>}
            </Link>
            <Link className="btn" to="/documents/pt-mapper/review" data-testid="review-queue-link">
              <ListChecks size={16} /> Unmapped queue
              {reviews.length > 0 && <span className="chip chip-amber" style={{ marginLeft: 6 }}>{reviews.length}</span>}
            </Link>
          </>
        )}
      </div>

      <div className="mode-toggle" data-testid="pt-tab-toggle" style={{ maxWidth: 520, marginBottom: 18 }}>
        <button
          type="button"
          className={`mode-btn ${tab === "mapper" ? "active" : ""}`}
          onClick={() => setTab("mapper")}
          data-testid="pt-tab-mapper"
        >
          <FileSpreadsheet size={16} /> PT File Mapper
        </button>
        <button
          type="button"
          className={`mode-btn ${tab === "making" ? "active" : ""}`}
          onClick={() => setTab("making")}
          data-testid="pt-tab-making"
        >
          <Wand2 size={16} /> PT File Making
        </button>
      </div>

      {loading ? (
        <p className="lead">Loading…</p>
      ) : tab === "mapper" ? (
        <MapperTab files={brandFiles} reload={reload} />
      ) : (
        <MakingTab files={makingFiles} />
      )}
    </div>
  );
}

interface PtRowT {
  id: number;
  line_no: number;
  data: Record<string, any>;
  blanks: string[];
  provenance: Record<string, string>;
  // {controlled column → raw source value the engine read}. Shown as a tooltip /
  // hint so a steward can see what the file actually said behind a mapped cell.
  raw: Record<string, any>;
}
interface PtFileDetailT extends PtFileT {
  meta: {
    sheet?: string; header_row?: number; source_rows?: number; headers?: string[];
    truncated?: boolean; row_limit?: number;
    manual_cells_dropped?: number;
    context?: { brand?: string; invoice_date?: string };
    grn_number?: string;
    invoice_number?: string;
    invoice_extract?: {
      invoice_number?: string | null; vendor_name?: string | null;
      confidence?: number | null; line_count?: number; cells_filled?: number;
    };
    invoice_extract_error?: string;
  };
  rows: PtRowT[];
}

interface SkuMatchT {
  barcode: string;
  design: string;
  color: string;
  size: string;
  brand: string;
  item: string;
  hsn: string;
  mrp: number | null;
}

// The authored (from-GRN) grid's cockpit: what is filled vs missing, and the
// one-tap fills the D2 design locked — P/M/E colour tiers (Q28), Free Size (Q29),
// deterministic pricing (Q7). Shown only for source=invoice files.
const AUTHORING_COLS = ["SEASON", "BRAND", "COLOR", "SIZE", "GENDER", "ITEM", "BARCODE", "MRP", "P RATE"];

function AuthoringPanel({
  file,
  busy,
  canAct,
  onQuickFill,
  onPrice,
}: {
  file: PtFileDetailT;
  busy: boolean;
  canAct: boolean;
  onQuickFill: (column: string, value: string) => void;
  onPrice: (marginPct: string) => void;
}) {
  const [marginPct, setMarginPct] = useState("");
  const missing = useMemo(() => {
    const counts: Record<string, number> = {};
    for (const c of AUTHORING_COLS) {
      counts[c] = file.rows.filter((r) => String(r.data[c] ?? "").trim() === "").length;
    }
    return counts;
  }, [file]);
  const extract = file.meta?.invoice_extract;
  return (
    <div className="card section-card" data-testid="pt-authoring-panel" style={{ marginTop: 12 }}>
      <p className="eyebrow">Authored from {file.grn_number || file.meta?.grn_number || "GRN"} · fill &amp; price</p>
      <div style={{ display: "flex", flexWrap: "wrap", gap: 8, margin: "8px 0" }} data-testid="pt-fill-status">
        {AUTHORING_COLS.map((c) => (
          <span key={c} className={`chip chip-${missing[c] === 0 ? "green" : "amber"}`} data-testid={`pt-fill-${c.replace(/\s+/g, "_")}`}>
            {c}: {file.rows.length - missing[c]}/{file.rows.length}
          </span>
        ))}
      </div>
      {extract && (
        <div className="ai-note" data-testid="pt-extract-note">
          <Sparkles size={14} /> Gemini read the invoice
          {extract.line_count != null ? ` (${extract.line_count} lines)` : ""} and prefilled{" "}
          {extract.cells_filled ?? 0} cell(s)
          {extract.confidence ? ` · confidence ${Math.round((extract.confidence ?? 0) * 100)}%` : ""}.
          Prefills are marked for a glance — verify before sending.
        </div>
      )}
      {file.meta?.invoice_extract_error && (
        <div className="warn-note" data-testid="pt-extract-error">
          Invoice could not be AI-read ({file.meta.invoice_extract_error}) — fill the money columns by hand.
        </div>
      )}
      {(missing.BARCODE > 0 || missing.SEASON > 0) && (
        <div className="warn-note" data-testid="pt-send-blockers">
          <AlertTriangle size={14} /> Before this PT can go to Patna: every row needs a <b>barcode</b>
          {missing.BARCODE > 0 ? ` (${missing.BARCODE} missing)` : " ✓"} and a <b>season</b>
          {missing.SEASON > 0 ? ` (${missing.SEASON} missing)` : " ✓"}.
        </div>
      )}
      {canAct && (
        <div style={{ display: "flex", flexWrap: "wrap", gap: 8, alignItems: "center", marginTop: 10 }}>
          <span className="bulk-label">Quick fill blanks:</span>
          {["PREMIUM", "MEDIUM", "ECONOMY"].map((tier) => (
            <button
              key={tier}
              className="btn btn-sm"
              disabled={busy || missing.COLOR === 0}
              onClick={() => onQuickFill("COLOR", tier)}
              title={`Set COLOR=${tier} on the ${missing.COLOR} rows without a colour (price-tier colours, Q28)`}
              data-testid={`pt-quickfill-${tier}`}
            >
              {tier.charAt(0)}·{tier.slice(1).toLowerCase()}
            </button>
          ))}
          <button
            className="btn btn-sm"
            disabled={busy || missing.SIZE === 0}
            onClick={() => onQuickFill("SIZE", "FREE SIZE")}
            title={`Set SIZE=FREE SIZE on the ${missing.SIZE} rows without a size`}
            data-testid="pt-quickfill-freesize"
          >
            Free Size
          </button>
          <span style={{ width: 12 }} />
          <span className="bulk-label">Price {missing.MRP} unpriced row(s):</span>
          <input
            className="input"
            style={{ width: 110 }}
            placeholder="margin % (opt)"
            value={marginPct}
            onChange={(e) => setMarginPct(e.target.value)}
            data-testid="pt-price-margin"
          />
          <button
            className="btn btn-cta btn-sm"
            disabled={busy || missing.MRP === 0}
            onClick={() => onPrice(marginPct)}
            title="MRP = (rate + 1.1% transport) × (1 + margin), grossed up with the GST slab — deterministic, category margin unless overridden"
            data-testid="pt-price-run"
          >
            <Wand2 size={14} /> Price blank rows
          </button>
        </div>
      )}
    </div>
  );
}

function StageStepper({ stage }: { stage: string }) {
  const steps = [
    { key: "mapping", label: "Warehouse mapping" },
    { key: "sent", label: "Sent to Patna" },
    { key: "posted", label: "Posted to system" },
  ];
  const idx = steps.findIndex((s) => s.key === stage);
  return (
    <div className="stage-stepper" data-testid="pt-stage-stepper">
      {steps.map((s, i) => (
        <div key={s.key} className={`stage-step ${i <= idx ? "done" : ""} ${i === idx ? "current" : ""}`}>
          <span className="stage-dot">{i < idx ? <CheckCircle2 size={13} /> : i + 1}</span>
          <span>{s.label}</span>
        </div>
      ))}
    </div>
  );
}

export function PtFileDetailPage() {
  const { id } = useParams();
  const { user } = useAuth();
  const role = user?.role?.code ?? "";
  const isAdmin = role === "owner" || role === "it_admin";
  const isWarehouse = role === "warehouse" || isAdmin;
  const isPatna = role === "accounts" || isAdmin;

  const [file, setFile] = useState<PtFileDetailT | null>(null);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [editMode, setEditMode] = useState(false);
  const [draft, setDraft] = useState<Record<number, Record<string, string>>>({});
  // {`${rowId}|${col}`: true} — cells the operator ticked "remember" (learn on send).
  const [rememberSet, setRememberSet] = useState<Record<string, boolean>>({});
  // {`${dim}|${raw}|${brand}`: Master values} — pre-fill hints for blank cells.
  const [cellSuggest, setCellSuggest] = useState<Record<string, string[]>>({});
  const [error, setError] = useState("");
  const [bookings, setBookings] = useState<{ id: number; number: string; brand_name?: string }[]>([]);
  const [selectedBooking, setSelectedBooking] = useState("");
  const vocab = useVocab();
  const [blanksOnly, setBlanksOnly] = useState(false);
  const [bulkCol, setBulkCol] = useState("");
  const [bulkValue, setBulkValue] = useState("");
  const [bulkScope, setBulkScope] = useState<"blank" | "all">("blank");
  const [ctxBrand, setCtxBrand] = useState("");
  const [ctxDate, setCtxDate] = useState("");
  const [showRerun, setShowRerun] = useState(false);

  function load() {
    setLoading(true);
    api.get(`/ptmapper/files/${id}`).then((r) => {
      setFile(r.data);
      setCtxBrand(r.data?.meta?.context?.brand ?? "");
      setCtxDate(r.data?.meta?.context?.invoice_date ?? "");
    }).finally(() => setLoading(false));
  }
  useEffect(load, [id]);

  useEffect(() => {
    if (isPatna) api.get("/bookings").then((r) => setBookings(r.data)).catch(() => {});
  }, [isPatna]);

  // SKU-registry reuse (Q16): for authored files, look up rows with a blank
  // barcode by (design, size, brand) — "seen before → reuse barcode X" instead of
  // minting a duplicate identity. Keyed per row id; bounded like cellSuggest.
  const [skuHints, setSkuHints] = useState<Record<number, SkuMatchT>>({});
  useEffect(() => {
    if (!editMode || !file || file.source !== "invoice") return;
    const wanted = file.rows
      .filter((r) => !String(r.data.BARCODE ?? "").trim() && String(r.data.DESIGN ?? "").trim())
      .slice(0, 40);
    let alive = true;
    Promise.all(
      wanted.map(async (r) => {
        const params = new URLSearchParams({ design: String(r.data.DESIGN) });
        if (r.data.SIZE) params.set("size", String(r.data.SIZE));
        if (r.data.BRAND) params.set("brand", String(r.data.BRAND));
        try {
          const res = await api.get(`/masters/skus/lookup?${params.toString()}`);
          const match = (res.data.matches ?? [])[0];
          return match ? ([r.id, match] as const) : null;
        } catch {
          return null;
        }
      }),
    ).then((pairs) => {
      if (alive) setSkuHints(Object.fromEntries(pairs.filter(Boolean) as [number, SkuMatchT][]));
    });
    return () => {
      alive = false;
    };
  }, [editMode, file]);

  // On entering edit mode, fetch pre-fill suggestions for each distinct blank
  // (dimension, raw, brand) — bounded by distinct raw values, not by cells.
  useEffect(() => {
    if (!editMode || !file) return;
    const pairs = new Map<string, { dim: string; q: string; brand: string }>();
    for (const r of file.rows) {
      for (const c of r.blanks) {
        const dim = COL_DIM[c];
        if (!dim || !LEARNABLE_DIMS.has(dim)) continue;
        const raw = r.raw?.[c] != null ? String(r.raw[c]) : "";
        if (!raw) continue;
        const brand = r.data.BRAND ? String(r.data.BRAND) : "";
        pairs.set(`${dim}|${raw}|${brand}`, { dim, q: raw, brand });
      }
    }
    let alive = true;
    const entries = [...pairs.entries()].slice(0, 40);
    Promise.all(
      entries.map(async ([k, p]) => {
        const params = new URLSearchParams({ dimension: p.dim, q: p.q });
        if (p.brand) params.set("brand", p.brand);
        try {
          const r = await api.get(`/ptmapper/suggest?${params.toString()}`);
          return [k, (r.data.suggestions ?? []).map((s: any) => s.value)] as const;
        } catch {
          return [k, [] as string[]] as const;
        }
      }),
    ).then((res) => alive && setCellSuggest(Object.fromEntries(res)));
    return () => {
      alive = false;
    };
  }, [editMode, file]);

  const stage = file?.stage ?? "mapping";
  const canEdit = isWarehouse && stage === "mapping";
  const canPost = isPatna && stage === "sent";
  const canReverse = isPatna && stage === "posted";
  const canRecall = isPatna && stage === "sent";

  async function action(path: string, body?: any) {
    setBusy(true);
    setError("");
    try {
      const { data } = await api.post(`/ptmapper/files/${id}/${path}`, body ?? {});
      setFile(data);
    } catch (e) {
      setError(apiErrorMessage(e));
    } finally {
      setBusy(false);
    }
  }

  function editCell(rowId: number, col: string, value: string) {
    // Picking an ITEM auto-fills SUB CATEGORY + TYPE from the Master helper
    // columns (both stay editable afterwards).
    if (col === "ITEM" && value && vocab.item_taxonomy[value]) {
      const t = vocab.item_taxonomy[value];
      setDraft((d) => ({
        ...d,
        [rowId]: {
          ...(d[rowId] ?? {}),
          ITEM: value,
          ...(t.sub_category ? { "SUB CATEGORY": t.sub_category } : {}),
          ...(t.type ? { TYPE: t.type } : {}),
        },
      }));
      return;
    }
    setDraft((d) => ({ ...d, [rowId]: { ...(d[rowId] ?? {}), [col]: value } }));
  }

  async function applyBulkFill() {
    if (!bulkCol) return;
    setBusy(true);
    setError("");
    try {
      const { data } = await api.patch(`/ptmapper/files/${id}/rows`, {
        fills: [{ column: bulkCol, value: bulkValue, scope: bulkScope }],
      });
      setFile(data);
      setBulkCol("");
      setBulkValue("");
    } catch (e) {
      setError(apiErrorMessage(e));
    } finally {
      setBusy(false);
    }
  }

  async function quickFill(column: string, value: string) {
    setBusy(true);
    setError("");
    try {
      const { data } = await api.patch(`/ptmapper/files/${id}/rows`, {
        fills: [{ column, value, scope: "blank" }],
      });
      setFile(data);
    } catch (e) {
      setError(apiErrorMessage(e));
    } finally {
      setBusy(false);
    }
  }

  const [priceNote, setPriceNote] = useState("");
  async function priceBlankRows(marginPct: string) {
    setBusy(true);
    setError("");
    setPriceNote("");
    try {
      const body = marginPct.trim() ? { margin_pct: marginPct.trim() } : {};
      const { data } = await api.post(`/ptmapper/files/${id}/price`, body);
      setFile(data);
      const r = data.price_result;
      if (r) {
        setPriceNote(
          `Priced ${r.priced} row(s)${r.skipped?.length ? ` · ${r.skipped.length} skipped (no purchase rate)` : ""}.`,
        );
      }
    } catch (e) {
      setError(apiErrorMessage(e));
    } finally {
      setBusy(false);
    }
  }

  /** Reuse a registry SKU on an authored row: barcode always; colour/HSN/MRP only
   *  where the row is still blank (never clobber a counted/typed value). */
  function applySkuReuse(row: PtRowT, match: SkuMatchT) {
    const cur = (c: string) => draft[row.id]?.[c] ?? String(row.data[c] ?? "");
    setDraft((d) => ({
      ...d,
      [row.id]: {
        ...(d[row.id] ?? {}),
        BARCODE: match.barcode,
        ...(match.color && !cur("COLOR").trim() ? { COLOR: match.color } : {}),
        ...(match.hsn && !cur("HSN").trim() ? { HSN: match.hsn } : {}),
        ...(match.mrp != null && !cur("MRP").trim() ? { MRP: String(match.mrp) } : {}),
        ...(match.item && !cur("ITEM").trim() ? { ITEM: match.item } : {}),
      },
    }));
  }

  async function rerunWithContext() {
    setBusy(true);
    setError("");
    try {
      const { data } = await api.post(`/ptmapper/files/${id}/rerun`, {
        brand: ctxBrand,
        invoice_date: ctxDate,
      });
      setFile(data);
      setShowRerun(false);
    } catch (e) {
      setError(apiErrorMessage(e));
    } finally {
      setBusy(false);
    }
  }

  async function saveEdits() {
    const rows = Object.entries(draft).map(([rid, data]) => ({ id: Number(rid), data }));
    const remember = Object.entries(rememberSet)
      .filter(([, on]) => on)
      .map(([k]) => {
        const sep = k.indexOf("|");
        return { row_id: Number(k.slice(0, sep)), column: k.slice(sep + 1) };
      });
    if (rows.length === 0 && remember.length === 0) {
      setEditMode(false);
      return;
    }
    setBusy(true);
    setError("");
    try {
      const body: any = { rows };
      if (remember.length) body.remember = remember;
      const { data } = await api.patch(`/ptmapper/files/${id}/rows`, body);
      setFile(data);
      setDraft({});
      setRememberSet({});
      setEditMode(false);
    } catch (e) {
      setError(apiErrorMessage(e));
    } finally {
      setBusy(false);
    }
  }

  function cancelEdit() {
    setDraft({});
    setRememberSet({});
    setEditMode(false);
  }

  async function download(kind: "csv" | "xlsx") {
    const url = kind === "csv" ? `/ptmapper/files/${id}/export` : `/ptmapper/files/${id}/export.xlsx`;
    const res = await api.get(url, { responseType: "blob" });
    const href = URL.createObjectURL(res.data);
    const a = document.createElement("a");
    a.href = href;
    a.download = `KDPS-PT-${file?.original_filename.replace(/\.[^.]+$/, "") ?? id}.${kind}`;
    a.click();
    URL.revokeObjectURL(href);
  }

  const VISIBLE_CAP = 1000;
  const blankCounts = useMemo(() => {
    const counts: Record<string, number> = {};
    for (const r of file?.rows ?? []) for (const c of r.blanks) counts[c] = (counts[c] ?? 0) + 1;
    return counts;
  }, [file]);
  const rowsWithBlanks = useMemo(
    () => (file?.rows ?? []).filter((r) => r.blanks.length > 0).length,
    [file],
  );
  const visibleRows = useMemo(() => {
    const rows = file?.rows ?? [];
    const filtered = blanksOnly ? rows.filter((r) => r.blanks.length > 0) : rows;
    return filtered.slice(0, VISIBLE_CAP);
  }, [file, blanksOnly]);
  const truncated =
    (blanksOnly ? rowsWithBlanks : (file?.rows.length ?? 0)) > VISIBLE_CAP;

  if (loading || !file) return <div className="page-pad"><p className="lead">Loading…</p></div>;

  return (
    <div className="page-pad">
      <Link to="/documents/pt-mapper" className="btn" style={{ marginBottom: 16 }}><ArrowLeft size={15} /> PT File Operation</Link>
      <div className="toolbar">
        <div>
          <p className="eyebrow">{file.profile_name}{file.meta?.sheet ? ` · sheet ${file.meta.sheet}` : ""}</p>
          <h1 className="h1">{file.original_filename}</h1>
          <p className="lead" style={{ fontSize: 13.5 }}>
            {file.row_count} KDPS rows · header at row {(file.meta?.header_row ?? 0) + 1}
            {file.brand_guess ? ` · brand ${file.brand_guess}` : ""}
            {file.manually_edited ? " · hand-edited" : ""}
          </p>
        </div>
        <div className="spacer" />
        {file.source === "invoice" && (
          <span className="chip chip-purple" data-testid="ptfile-source-badge">Authored · non-brand</span>
        )}
        {file.grn && (
          <Link to={`/inbound/${file.grn}`} className="chip chip-navy" data-testid="ptfile-grn-chip">
            GRN {file.grn_number || file.meta?.grn_number || `#${file.grn}`}
          </Link>
        )}
        <span className={`chip chip-${FILE_TONE[file.status] ?? "grey"}`}>{file.status_label}</span>
        <span className={`chip chip-${STAGE_TONE[file.stage] ?? "grey"}`} data-testid="ptfile-stage-badge">{file.stage_label}</span>
      </div>

      <StageStepper stage={file.stage} />

      {file.meta?.truncated && (
        <div className="warn-note" data-testid="ptfile-source-truncated-banner" style={{ marginTop: 10 }}>
          <AlertTriangle size={14} /> This source file exceeds the {file.meta.row_limit ?? 8000}-row import cap — only the first {file.meta.row_limit ?? 8000} rows were read. Split the file and re-upload to map the remainder.
        </div>
      )}

      {(file.meta?.manual_cells_dropped ?? 0) > 0 && (
        <div className="warn-note" data-testid="ptfile-dropped-cells-banner" style={{ marginTop: 10 }}>
          <AlertTriangle size={14} /> {file.meta.manual_cells_dropped} hand-edited cell(s) couldn't be re-applied after the last re-map (their row moved or disappeared). Review the table and re-enter them if needed.
        </div>
      )}

      <div className="toolbar" style={{ marginTop: 8 }}>
        <button className="btn" onClick={() => download("xlsx")} data-testid="ptfile-export-xlsx"><Download size={15} /> Excel (KDPS)</button>
        <button className="btn" onClick={() => download("csv")} data-testid="ptfile-export"><Download size={15} /> CSV</button>
        <div className="spacer" />
        {canEdit && !editMode && (
          <>
            {file.source !== "invoice" && (
              <>
                <button className="btn" onClick={rerunWithContext} disabled={busy} data-testid="ptfile-rerun"><RefreshCw size={15} className={busy ? "spin" : ""} /> Re-run</button>
                <button className="btn" onClick={() => setShowRerun((s) => !s)} data-testid="ptfile-context-toggle" title="Brand / invoice date the file itself doesn't carry">Context{(ctxBrand || ctxDate) ? " ·" : ""}</button>
              </>
            )}
            <button className="btn" onClick={() => setEditMode(true)} data-testid="ptfile-edit"><Pencil size={15} /> Edit table</button>
            <button className="btn btn-cta" onClick={() => action("send")} disabled={busy} data-testid="ptfile-send"><Send size={15} /> Send to Patna</button>
          </>
        )}
        {canEdit && editMode && (
          <>
            <button className="btn" onClick={cancelEdit} disabled={busy} data-testid="ptfile-cancel"><X size={15} /> Cancel</button>
            <button className="btn btn-cta" onClick={saveEdits} disabled={busy} data-testid="ptfile-save"><Save size={15} /> Save changes</button>
          </>
        )}
        {canRecall && (
          <button className="btn" onClick={() => action("recall")} disabled={busy} data-testid="ptfile-recall"><Undo2 size={15} /> Send back</button>
        )}
        {canPost && (
          <>
            <select className="select" value={selectedBooking} onChange={(e) => setSelectedBooking(e.target.value)} data-testid="ptfile-booking-select" style={{ maxWidth: 240 }}>
              <option value="">Reconcile to booking… (optional)</option>
              {bookings.map((b) => (
                <option key={b.id} value={b.id}>{b.number}{b.brand_name ? ` · ${b.brand_name}` : ""}</option>
              ))}
            </select>
            <button className="btn btn-cta" onClick={() => action("post", selectedBooking ? { booking_id: Number(selectedBooking) } : {})} disabled={busy} data-testid="ptfile-post"><CheckCircle2 size={15} /> Push into system</button>
          </>
        )}
        {canReverse && (
          <button className="btn" onClick={() => action("reverse")} disabled={busy} data-testid="ptfile-reverse"><RotateCcw size={15} /> Reverse posting</button>
        )}
      </div>

      {showRerun && canEdit && !editMode && (
        <div className="card section-card ctx-panel" data-testid="ptfile-context-panel">
          <p className="eyebrow">Mapping context — used only where the file itself is silent</p>
          <div className="upload-context">
            <div className="upload-context-field">
              <label className="upload-context-label">Brand</label>
              <Combobox
                value={ctxBrand}
                options={vocab.dimensions.brand ?? []}
                onChange={setCtxBrand}
                placeholder="Master brand…"
                testId="ptfile-context-brand"
              />
            </div>
            <div className="upload-context-field">
              <label className="upload-context-label">Invoice date</label>
              <input type="date" className="input" value={ctxDate} onChange={(e) => setCtxDate(e.target.value)} data-testid="ptfile-context-date" />
            </div>
            <button className="btn btn-cta" onClick={rerunWithContext} disabled={busy} data-testid="ptfile-context-rerun">
              <RefreshCw size={15} className={busy ? "spin" : ""} /> Re-run with context
            </button>
          </div>
        </div>
      )}

      {error && <div className="warn-note" data-testid="ptfile-action-error">{error}</div>}
      {priceNote && <div className="ok-note" data-testid="ptfile-price-note"><CheckCircle2 size={14} /> {priceNote}</div>}

      {file.source === "invoice" && file.stage !== "posted" && file.stage !== "reversed" && (
        <AuthoringPanel
          file={file}
          busy={busy}
          canAct={canEdit}
          onQuickFill={quickFill}
          onPrice={priceBlankRows}
        />
      )}

      {file.status === "failed" ? (
        <div className="warn-note" data-testid="ptfile-error">{file.error}</div>
      ) : file.stage === "posted" ? (
        <div className="ok-note" data-testid="ptfile-posted-banner"><Lock size={14} /> Posted into the KDPS stock ledger
          {file.inward_doc_number ? <> as voucher <b className="mono">{file.inward_doc_number}</b></> : null}
          {file.booking_number ? <> · reconciled to booking <b>{file.booking_number}</b></> : null}
          {file.posted_at ? ` on ${new Date(file.posted_at).toLocaleString()}` : ""}. This record is locked.{" "}
          <Link to={`/ledgers/stock?file=${file.id}`} style={{ color: "inherit", textDecoration: "underline" }} data-testid="ptfile-ledger-link">View in Stock Ledger</Link>
        </div>
      ) : file.stage === "sent" ? (
        <div className="ai-note" data-testid="ptfile-sent-banner"><Send size={14} /> Sent to Patna HO for review &amp; posting. Patna can download the Excel and push it into the system.</div>
      ) : file.unresolved_count > 0 ? (
        <div className="ai-note" data-testid="ptfile-unresolved-banner">
          <AlertTriangle size={14} /> {file.unresolved_count} value(s) couldn't be mapped automatically.{" "}
          <Link to="/documents/pt-mapper/review" style={{ color: "inherit", textDecoration: "underline" }}>Resolve them in the unmapped queue</Link>, then re-run — or fill them in by hand with Edit.
        </div>
      ) : (
        <div className="ok-note" data-testid="ptfile-ready-banner"><CheckCircle2 size={14} /> Every derived field mapped to a KDPS value. Ready to send to Patna.</div>
      )}

      {file.rows.length > 0 && (
        <>
          <div className="toolbar" style={{ marginTop: 14, marginBottom: 0 }}>
            <button
              className={`btn ${blanksOnly ? "btn-cta" : ""}`}
              onClick={() => setBlanksOnly((b) => !b)}
              data-testid="ptfile-blanks-filter"
            >
              <Filter size={14} /> Only rows with blanks ({rowsWithBlanks})
            </button>
            <div className="spacer" />
            <div className="prov-legend" data-testid="ptfile-prov-legend">
              <span><i className="prov-swatch glance" /> mapped by judgement — glance</span>
              <span><i className="prov-swatch manual" /> hand-edited</span>
              <span><i className="prov-swatch blank" /> blank — needs a value</span>
            </div>
          </div>

          {editMode && (
            <div className="bulk-bar" data-testid="ptfile-bulk-bar">
              <Wand2 size={14} />
              <span className="bulk-label">Fill a whole column:</span>
              <select className="select" value={bulkCol} onChange={(e) => { setBulkCol(e.target.value); setBulkValue(""); }} data-testid="ptfile-bulk-col">
                <option value="">Column…</option>
                {Object.keys(COL_DIM).map((c) => <option key={c} value={c}>{c}</option>)}
              </select>
              {bulkCol && (
                <>
                  <div style={{ width: 230 }}>
                    <Combobox
                      value={bulkValue}
                      options={vocab.dimensions[COL_DIM[bulkCol]] ?? []}
                      onChange={setBulkValue}
                      placeholder={`Master ${bulkCol.toLowerCase()}…`}
                      testId="ptfile-bulk-value"
                    />
                  </div>
                  <select className="select" value={bulkScope} onChange={(e) => setBulkScope(e.target.value as "blank" | "all")} data-testid="ptfile-bulk-scope">
                    <option value="blank">only blank rows{blankCounts[bulkCol] ? ` (${blankCounts[bulkCol]})` : ""}</option>
                    <option value="all">all {file.rows.length} rows</option>
                  </select>
                  <button className="btn btn-cta btn-sm" onClick={applyBulkFill} disabled={busy || !bulkValue} data-testid="ptfile-bulk-apply">Apply</button>
                </>
              )}
              <div className="spacer" />
              <span className="remember-caption" data-testid="ptfile-remember-caption">
                <Sparkles size={12} /> Tick <b>remember</b> on a fix to teach the mapper — it learns when this PT is sent to Patna.
              </span>
            </div>
          )}

          <div className="table-wrap kdps-scroll" style={{ marginTop: 10 }}>
            {truncated && (
              <div className="ai-note" data-testid="ptfile-truncated-banner" style={{ marginBottom: 10 }}>
                <AlertTriangle size={14} /> Showing the first {VISIBLE_CAP} of {blanksOnly ? rowsWithBlanks : file.rows.length} rows for performance. Download the Excel/CSV for the complete set.
              </div>
            )}
            <table className="data kdps-table" data-testid="ptfile-rows-table">
              <thead>
                <tr>
                  <th>#</th>
                  {KDPS_COLUMNS.map((c) => (
                    <th key={c} className={NUM_COLS.includes(c) ? "num" : ""}>
                      {c}
                      {blankCounts[c] ? <span className="blank-count" title={`${blankCounts[c]} blank`}>{blankCounts[c]}</span> : null}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {visibleRows.map((r) => (
                  <tr key={r.id}>
                    <td className="mono" style={{ color: "var(--muted)" }}>{r.line_no}</td>
                    {KDPS_COLUMNS.map((c) => {
                      const current = draft[r.id]?.[c] ?? (r.data[c] === null || r.data[c] === undefined ? "" : String(r.data[c]));
                      const isBlank = r.blanks.includes(c) && !draft[r.id]?.[c];
                      const prov = draft[r.id]?.[c] !== undefined ? "manual" : (r.provenance?.[c] ?? "");
                      const dim = COL_DIM[c];
                      const rawVal = r.raw?.[c] === null || r.raw?.[c] === undefined ? "" : String(r.raw[c]);
                      const showRaw = rawVal !== "" && rawVal !== current;
                      if (editMode && READONLY_COLS.has(c)) {
                        return <td key={c} className={`${NUM_COLS.includes(c) ? "num " : ""}cell-readonly`}>{current}</td>;
                      }
                      if (editMode && dim) {
                        const rememberable = LEARNABLE_DIMS.has(dim) && rawVal !== "";
                        const rkey = `${r.id}|${c}`;
                        const brandScope = r.data.BRAND ? String(r.data.BRAND) : "";
                        const suggested = isBlank && rememberable ? cellSuggest[`${dim}|${rawVal}|${brandScope}`] : undefined;
                        return (
                          <td key={c} className={`${NUM_COLS.includes(c) ? "num " : ""}${isBlank ? "blank-edit-cell" : ""}`}>
                            <Combobox
                              value={current}
                              options={vocab.dimensions[dim] ?? []}
                              onChange={(v) => editCell(r.id, c, v)}
                              placeholder="—"
                              size="cell"
                              suggested={suggested}
                              testId={`pt-cell-${r.id}-${c.replace(/\s+/g, "_")}`}
                            />
                            {showRaw && <div className="raw-hint" title={`Source value the engine read: ${rawVal}`}>raw: {rawVal}</div>}
                            {rememberable && (
                              <label
                                className="remember-toggle"
                                title={`Learn ${rawVal} → this value for ${brandScope || "all brands"} when this PT is sent to Patna`}
                              >
                                <input
                                  type="checkbox"
                                  checked={!!rememberSet[rkey]}
                                  onChange={(e) => setRememberSet((s) => ({ ...s, [rkey]: e.target.checked }))}
                                  data-testid={`pt-remember-${r.id}-${c.replace(/\s+/g, "_")}`}
                                />
                                remember{brandScope ? ` · ${brandScope}` : ""}
                              </label>
                            )}
                          </td>
                        );
                      }
                      if (editMode) {
                        const hint = c === "BARCODE" && !current ? skuHints[r.id] : undefined;
                        return (
                          <td key={c} className={NUM_COLS.includes(c) ? "num" : ""}>
                            <input
                              className="cell-input"
                              value={current}
                              onChange={(e) => editCell(r.id, c, e.target.value)}
                              data-testid={`pt-cell-${r.id}-${c.replace(/\s+/g, "_")}`}
                            />
                            {hint && (
                              <button
                                type="button"
                                className="raw-hint"
                                style={{ cursor: "pointer", border: 0, background: "none", padding: 0, color: "var(--rust)" }}
                                onClick={() => applySkuReuse(r, hint)}
                                title={`Seen before as ${hint.barcode}${hint.mrp != null ? ` · MRP ₹${hint.mrp}` : ""} — reuse the registry identity (fills barcode + blank colour/HSN/MRP)`}
                                data-testid={`pt-sku-reuse-${r.id}`}
                              >
                                ↺ reuse {hint.barcode}
                              </button>
                            )}
                          </td>
                        );
                      }
                      const glance = !isBlank && current !== "" && GLANCE_PROV.has(prov);
                      const manual = !isBlank && current !== "" && prov === "manual";
                      return (
                        <td
                          key={c}
                          className={`${NUM_COLS.includes(c) ? "num " : ""}${isBlank ? "blank-cell" : ""}${glance ? "prov-glance" : ""}${manual ? "prov-manual" : ""}`}
                          title={showRaw ? `raw: ${rawVal}` : undefined}
                        >
                          {current === "" ? (isBlank ? "—" : "") : current}
                        </td>
                      );
                    })}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </>
      )}
    </div>
  );
}

const DIM_LABEL: Record<string, string> = {
  color: "Colour", size: "Size", brand: "Brand", season: "Season", fit: "Fit", taxonomy: "Taxonomy",
};
const SINGLE_DIMS = ["color", "size", "brand", "season", "fit"];

interface ReviewT {
  id: number;
  dimension: string;
  raw_value: string;
  context: { samples?: string[]; brands?: string[] };
  occurrences: number;
}

export function ReviewQueuePage() {
  const { data: items, loading, reload } = useList<ReviewT>("/ptmapper/review?status=open");
  const [vocab, setVocab] = useState<Record<string, string[]>>({});

  useEffect(() => {
    const dims = ["color", "size", "brand", "season", "item", "sub_category", "type", "gender", "fit"];
    Promise.all(
      dims.map((d) => api.get(`/ptmapper/controlled?dimension=${d}`).then((r) => [d, r.data.values] as [string, string[]])),
    ).then((pairs) => setVocab(Object.fromEntries(pairs)));
  }, []);

  return (
    <div className="page-pad">
      <Link to="/documents/pt-mapper" className="btn" style={{ marginBottom: 16 }}><ArrowLeft size={15} /> PT File Operation</Link>
      <h1 className="h1 h2-rust" style={{ marginBottom: 4 }}>Unmapped queue</h1>
      <p className="lead" style={{ marginBottom: 18, fontSize: 13.5 }}>
        Each entry is a raw brand value the tables don't know yet. Map it once — the engine remembers it for every future file.
      </p>

      {loading ? (
        <p className="lead">Loading…</p>
      ) : items.length === 0 ? (
        <div className="ok-note" data-testid="review-empty"><CheckCircle2 size={14} /> Queue is empty — every value maps to a KDPS value.</div>
      ) : (
        <div className="review-list" data-testid="review-list">
          {items.map((it) => (
            <ReviewRow key={it.id} item={it} vocab={vocab} onDone={reload} />
          ))}
        </div>
      )}
    </div>
  );
}

function ReviewRow({ item, vocab, onDone }: { item: ReviewT; vocab: Record<string, string[]>; onDone: () => void }) {
  const isSingle = SINGLE_DIMS.includes(item.dimension);
  const [target, setTarget] = useState("");
  const [grid, setGrid] = useState({ item: "", sub_category: "", type: "", gender: "", fit: "" });
  const [pattern, setPattern] = useState(item.raw_value.slice(0, 60));
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");

  const samples = useMemo(() => (item.context?.samples ?? []).slice(0, 2), [item]);
  // Scope the suggestion to a brand only when the resolution will be brand-scoped too
  // (the backend defaults a multi-brand item to a global rule); otherwise a brand-only
  // lookup could be suggested and then saved globally.
  const itemBrands = item.context?.brands ?? [];
  const itemBrand = itemBrands.length === 1 ? itemBrands[0] : "";
  const suggestions = useSuggestions(isSingle ? item.dimension : "", item.raw_value, itemBrand);
  const suggestedSet = useMemo(() => new Set(suggestions), [suggestions]);

  async function resolve() {
    setSaving(true);
    setError("");
    try {
      const body = isSingle ? { target_value: target } : { pattern, ...grid };
      await api.post(`/ptmapper/review/${item.id}/resolve`, body);
      onDone();
    } catch (e) {
      setError(apiErrorMessage(e));
      setSaving(false);
    }
  }

  async function ignore() {
    setSaving(true);
    try {
      await api.post(`/ptmapper/review/${item.id}/resolve`, { action: "ignore" });
      onDone();
    } catch {
      setSaving(false);
    }
  }

  return (
    <div className="card review-item" data-testid={`review-item-${item.id}`}>
      <div className="review-head">
        <span className={`chip chip-${item.dimension === "taxonomy" ? "purple" : "blue"}`}>{DIM_LABEL[item.dimension] ?? item.dimension}</span>
        <span className="review-raw mono">{item.raw_value}</span>
        <span className="chip chip-grey">{item.occurrences}×</span>
      </div>
      {samples.length > 0 && <div className="review-samples">e.g. {samples.join(" · ")}</div>}

      <div className="review-resolve">
        {isSingle ? (
          <>
            <select className="select" value={target} onChange={(e) => setTarget(e.target.value)} data-testid={`review-target-${item.id}`}>
              <option value="">Map to KDPS {DIM_LABEL[item.dimension]}…</option>
              {suggestions.length > 0 && (
                <optgroup label="Suggested">
                  {suggestions.map((v) => <option key={`s-${v}`} value={v}>★ {v}</option>)}
                </optgroup>
              )}
              {(vocab[item.dimension] ?? []).filter((v) => !suggestedSet.has(v)).map((v) => <option key={v} value={v}>{v}</option>)}
            </select>
            <button className="btn btn-primary" disabled={saving || !target} onClick={resolve} data-testid={`review-resolve-${item.id}`}>Resolve</button>
          </>
        ) : (
          <div className="tx-grid">
            <input className="input" value={pattern} onChange={(e) => setPattern(e.target.value)} placeholder="keyword pattern" data-testid={`tx-pattern-${item.id}`} />
            <select className="select" value={grid.item} onChange={(e) => setGrid((g) => ({ ...g, item: e.target.value }))} data-testid={`tx-item-${item.id}`}>
              <option value="">Item…</option>
              {(vocab.item ?? []).map((v) => <option key={v} value={v}>{v}</option>)}
            </select>
            <select className="select" value={grid.sub_category} onChange={(e) => setGrid((g) => ({ ...g, sub_category: e.target.value }))} data-testid={`tx-sub-${item.id}`}>
              <option value="">Sub category…</option>
              {(vocab.sub_category ?? []).map((v) => <option key={v} value={v}>{v}</option>)}
            </select>
            <select className="select" value={grid.type} onChange={(e) => setGrid((g) => ({ ...g, type: e.target.value }))} data-testid={`tx-type-${item.id}`}>
              <option value="">Type…</option>
              {(vocab.type ?? []).map((v) => <option key={v} value={v}>{v}</option>)}
            </select>
            <select className="select" value={grid.gender} onChange={(e) => setGrid((g) => ({ ...g, gender: e.target.value }))} data-testid={`tx-gender-${item.id}`}>
              <option value="">Gender…</option>
              {(vocab.gender ?? []).map((v) => <option key={v} value={v}>{v}</option>)}
            </select>
            <select className="select" value={grid.fit} onChange={(e) => setGrid((g) => ({ ...g, fit: e.target.value }))} data-testid={`tx-fit-${item.id}`}>
              <option value="">Fit…</option>
              {(vocab.fit ?? []).map((v) => <option key={v} value={v}>{v}</option>)}
            </select>
            <button className="btn btn-primary" disabled={saving || !grid.item} onClick={resolve} data-testid={`review-resolve-${item.id}`}>Resolve</button>
          </div>
        )}
        <button className="btn btn-sm" disabled={saving} onClick={ignore} data-testid={`review-ignore-${item.id}`}>Ignore</button>
      </div>
      {error && <div className="warn-note" style={{ marginTop: 8 }}>{error}</div>}
    </div>
  );
}
