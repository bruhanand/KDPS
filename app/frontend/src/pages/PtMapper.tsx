import { useEffect, useMemo, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
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
  row_count: number;
  blank_cell_count: number;
  unresolved_count: number;
  error: string;
  created_at: string;
}

export function PtMapperPage() {
  const navigate = useNavigate();
  const { data: files, loading, reload } = useList<PtFileT>("/ptmapper/files");
  const { data: reviews } = useList<any>("/ptmapper/review?status=open");
  const { data: proposals } = useList<any>("/ptmapper/proposals?status=proposed");
  const vocab = useVocab();
  const [uploading, setUploading] = useState(false);
  const [error, setError] = useState("");
  const [ctxBrand, setCtxBrand] = useState("");
  const [ctxDate, setCtxDate] = useState("");

  async function handleFile(file: File) {
    setUploading(true);
    setError("");
    const form = new FormData();
    form.append("file", file);
    if (ctxBrand) form.append("brand", ctxBrand);
    if (ctxDate) form.append("invoice_date", ctxDate);
    try {
      const { data } = await api.post("/ptmapper/files", form);
      reload();
      navigate(`/documents/pt-mapper/${data.id}`);
    } catch (e) {
      setError(apiErrorMessage(e));
    } finally {
      setUploading(false);
    }
  }

  return (
    <div className="page-pad">
      <div className="toolbar">
        <div>
          <p className="eyebrow">Documents · Warehouse (Ranchi) → Patna HO</p>
          <h1 className="h1 h2-rust">PT File Mapper</h1>
        </div>
        <div className="spacer" />
        <Link className="btn" to="/documents/pt-mapper/proposals" data-testid="proposals-link">
          <Sparkles size={16} /> Learning proposals
          {proposals.length > 0 && <span className="chip chip-green" style={{ marginLeft: 6 }}>{proposals.length}</span>}
        </Link>
        <Link className="btn" to="/documents/pt-mapper/review" data-testid="review-queue-link">
          <ListChecks size={16} /> Unmapped queue
          {reviews.length > 0 && <span className="chip chip-amber" style={{ marginLeft: 6 }}>{reviews.length}</span>}
        </Link>
      </div>

      <div className="card section-card">
        <p className="eyebrow">Convert a brand PT file → KDPS format</p>
        <h3 className="h3" style={{ marginBottom: 4 }}>Deterministic mapping · no AI</h3>
        <p className="lead" style={{ marginBottom: 14, fontSize: 13.5 }}>
          Upload a brand's PT file (.xlsx / .xls / .xlsb / .csv). Columns are mapped by table;
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

      {loading ? (
        <p className="lead">Loading…</p>
      ) : files.length === 0 ? (
        <div className="card section-card" data-testid="pt-files-empty">No files mapped yet.</div>
      ) : (
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
  };
  rows: PtRowT[];
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
      <Link to="/documents/pt-mapper" className="btn" style={{ marginBottom: 16 }}><ArrowLeft size={15} /> PT Mapper</Link>
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
            <button className="btn" onClick={rerunWithContext} disabled={busy} data-testid="ptfile-rerun"><RefreshCw size={15} className={busy ? "spin" : ""} /> Re-run</button>
            <button className="btn" onClick={() => setShowRerun((s) => !s)} data-testid="ptfile-context-toggle" title="Brand / invoice date the file itself doesn't carry">Context{(ctxBrand || ctxDate) ? " ·" : ""}</button>
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
                        return (
                          <td key={c} className={NUM_COLS.includes(c) ? "num" : ""}>
                            <input
                              className="cell-input"
                              value={current}
                              onChange={(e) => editCell(r.id, c, e.target.value)}
                              data-testid={`pt-cell-${r.id}-${c.replace(/\s+/g, "_")}`}
                            />
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
      <Link to="/documents/pt-mapper" className="btn" style={{ marginBottom: 16 }}><ArrowLeft size={15} /> PT Mapper</Link>
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
