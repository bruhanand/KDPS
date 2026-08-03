import { useMemo, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { ArrowLeft, FileUp, Plus, Send, Sparkles, Trash2, XCircle } from "lucide-react";

import { useAuth } from "../auth/AuthContext";
import { ListSearchBar } from "../components/SearchBox";
import { userCan } from "../shell/navConfig";
import { api, apiErrorMessage } from "../lib/api";
import { useDoc, useList } from "../lib/hooks";
import { Money } from "../lib/format";
import "./Booking.css";
import { PageHeader } from "../components/PageHeader";

const STATUS_TONE: Record<string, string> = {
  draft: "grey",
  booked: "green",
  partially_received: "amber",
  received: "blue",
  closed: "navy",
  cancelled: "red",
};

function StatusPill({ status, label }: { status: string; label?: string }) {
  return <span className={`chip chip-${STATUS_TONE[status] ?? "grey"} status-pill`}>{label ?? status}</span>;
}

interface BookingT {
  id: number;
  number: string;
  brand_name: string;
  vendor_name: string;
  season_code: string;
  season_name: string;
  status: string;
  status_label: string;
  destination_store_name: string | null;
  booked_total: number;
  received_total: number;
  open_qty: number;
  close_reason: string;
  closed_at: string | null;
  closed_by_name: string | null;
  ownership: string;
  return_terms: string;
  estimated_value_paise: number | null;
  vendor_ref: string;
  lines: BookingLineT[];
}
interface BookingLineT {
  id: number;
  style_code: string;
  size: string;
  description: string;
  booked_qty: number;
  mrp_paise: number | null;
  received_qty: number;
  inwarded_qty: number;
  store: number | null;
  store_name: string | null;
}

export function BookingsPage() {
  const { user } = useAuth();
  const [q, setQ] = useState("");
  const { data, loading } = useList<BookingT>("/bookings", { q });
  // Mirrors the server gate exactly (`vendors.CanPlaceBooking` = booking:operate),
  // read from the same section payload rather than a role list of our own. A
  // store holds `booking: view` (#130) - the list, never the create.
  const canPlace = userCan(user, "booking", "operate");
  return (
    <div className="page-pad">
      <PageHeader
        actions={
          canPlace && (
            <Link className="btn btn-cta" to="/booking/new" data-testid="new-booking-btn">
              <Plus size={16} /> New booking
            </Link>
          )
        }
      />

      <ListSearchBar
        value={q}
        onChange={setQ}
        placeholder="Search bookings — number, vendor, brand, season"
        label="Search bookings"
        testId="bookings-search"
        noun="booking"
        count={data.length}
        loading={loading}
      />

      {loading ? (
        <p className="lead">Loading…</p>
      ) : data.length === 0 ? (
        <div className="card section-card" data-testid="bookings-empty">
          {q
            ? `No booking matches “${q}”. Try the booking number, the vendor, the brand or the season.`
            : "No bookings yet. Create one from a vendor's receiving document."}
        </div>
      ) : (
        <div className="card-grid" data-testid="bookings-grid">
          {data.map((b) => {
            const pct = b.booked_total ? Math.round((b.received_total / b.booked_total) * 100) : 0;
            return (
              <Link key={b.id} to={`/booking/${b.id}`} className="card bk-card" data-testid={`booking-card-${b.number}`}>
                <div className="bk-card-top">
                  <span className="bk-num">{b.number}</span>
                  <StatusPill status={b.status} label={b.status_label} />
                </div>
                <div className="bk-brand">{b.brand_name}</div>
                <div className="bk-meta">{b.vendor_name} · {b.season_code}{b.destination_store_name ? ` · → ${b.destination_store_name}` : ""}</div>
                <div className="bk-prog">
                  <div className="bk-prog-bar"><div className="bk-prog-fill" style={{ width: `${pct}%` }} /></div>
                  <div className="bk-prog-meta"><span>{b.received_total} / {b.booked_total} pcs received</span><span>{pct}%</span></div>
                </div>
              </Link>
            );
          })}
        </div>
      )}
    </div>
  );
}

interface DraftLine {
  style_code: string;
  size: string;
  description: string;
  booked_qty: number | string;
  mrp: number | string;
  store: string;
}
const emptyLine = (): DraftLine => ({ style_code: "", size: "", description: "", booked_qty: "", mrp: "", store: "" });

export function BookingNewPage() {
  const navigate = useNavigate();
  const { data: vendors } = useList<any>("/vendors");
  const { data: brands } = useList<any>("/masters/brands");
  const { data: seasons } = useList<any>("/masters/seasons");
  const { data: stores } = useList<any>("/masters/stores");

  const [vendorId, setVendorId] = useState("");
  const [brandId, setBrandId] = useState("");
  const [seasonId, setSeasonId] = useState("");
  const [destId, setDestId] = useState("");
  const [vendorRef, setVendorRef] = useState("");
  const [lines, setLines] = useState<DraftLine[]>([emptyLine()]);
  const [sourceFileId, setSourceFileId] = useState<number | null>(null);
  const [reading, setReading] = useState(false);
  const [aiNote, setAiNote] = useState("");
  const [warn, setWarn] = useState("");
  const [error, setError] = useState("");
  const [saving, setSaving] = useState(false);

  function setLine(i: number, key: keyof DraftLine, val: string) {
    setLines((ls) => ls.map((l, idx) => (idx === i ? { ...l, [key]: val } : l)));
  }
  const brandVendors = useMemo(() => vendors, [vendors]);

  async function handleFile(file: File) {
    setReading(true);
    setWarn("");
    setAiNote("");
    setError("");
    const form = new FormData();
    form.append("file", file);
    try {
      const { data } = await api.post("/bookings/draft", form);
      setSourceFileId(data.source_file_id ?? null);
      const got: DraftLine[] = (data.lines || []).map((l: any) => ({
        style_code: l.style_code || "",
        size: l.size || "",
        description: l.description || "",
        booked_qty: l.quantity ?? "",
        mrp: l.mrp ?? "",
        store: "",
      }));
      if (got.length) setLines(got);
      // best-effort prefill
      if (data.brand) {
        const b = brands.find((x: any) => (x.name as string).toLowerCase().includes(String(data.brand).toLowerCase()));
        if (b) setBrandId(String(b.id));
      }
      if (data.season) {
        const s = seasons.find((x: any) => String(data.season).toLowerCase().includes(x.code.toLowerCase()) || x.name.toLowerCase().includes(String(data.season).toLowerCase()));
        if (s) setSeasonId(String(s.id));
      }
      if (data.vendor_ref) setVendorRef(data.vendor_ref);
      setAiNote(`Gemini read ${got.length} line(s)${data.confidence ? ` · confidence ${Math.round(data.confidence * 100)}%` : ""}. Review and confirm before saving.`);
    } catch (e: any) {
      setSourceFileId(e?.response?.data?.source_file_id ?? null);
      setWarn(e?.response?.data?.detail || "Could not read the file — please fill the lines manually.");
    } finally {
      setReading(false);
    }
  }

  async function save() {
    setError("");
    if (!vendorId || !brandId || !seasonId) {
      setError("Pick a vendor, brand and season.");
      return;
    }
    const payloadLines = lines
      .filter((l) => l.style_code && Number(l.booked_qty) > 0)
      .map((l) => ({
        style_code: l.style_code,
        size: l.size,
        description: l.description,
        booked_qty: Number(l.booked_qty),
        mrp: l.mrp === "" ? null : Number(l.mrp),
        store: l.store === "" ? null : Number(l.store),
      }));
    if (!payloadLines.length) {
      setError("Add at least one line with a style and quantity.");
      return;
    }
    setSaving(true);
    try {
      const { data } = await api.post("/bookings", {
        vendor: Number(vendorId),
        brand: Number(brandId),
        season: Number(seasonId),
        destination_store: destId ? Number(destId) : null,
        vendor_ref: vendorRef,
        source_file_id: sourceFileId,
        lines: payloadLines,
      });
      navigate(`/booking/${data.id}`);
    } catch (e) {
      setError(apiErrorMessage(e));
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="page-pad">
      <Link to="/booking" className="btn" style={{ marginBottom: 16 }}><ArrowLeft size={15} /> Bookings</Link>
      <h1 className="h1 h2-rust" style={{ marginBottom: 18 }}>New booking</h1>

      <div className="card section-card">
        <p className="eyebrow">Step 1 · Receiving document</p>
        <h3 className="h3" style={{ marginBottom: 12 }}>Upload &amp; let the agent draft it</h3>
        <label className="dropzone" data-testid="booking-dropzone">
          <input type="file" hidden accept="image/*,.pdf,.xlsx,.xls,.csv" onChange={(e) => e.target.files && handleFile(e.target.files[0])} />
          {reading ? (
            <span><Sparkles size={18} /> Reading with Gemini…</span>
          ) : (
            <span><FileUp size={18} /> Drop a PDF / photo / Excel, or click to choose</span>
          )}
        </label>
        {aiNote && <div className="ai-note" data-testid="ai-note"><Sparkles size={14} /> {aiNote}</div>}
        {warn && <div className="warn-note" data-testid="ai-warn">{warn}</div>}
      </div>

      <div className="card section-card">
        <p className="eyebrow">Step 2 · Header</p>
        <div className="form-row" style={{ marginTop: 10 }}>
          <div className="field"><label>Vendor</label>
            <select className="select" value={vendorId} onChange={(e) => setVendorId(e.target.value)} data-testid="booking-vendor">
              <option value="">Select vendor…</option>
              {brandVendors.map((v: any) => <option key={v.id} value={v.id}>{v.name}</option>)}
            </select>
          </div>
          <div className="field"><label>Brand</label>
            <select className="select" value={brandId} onChange={(e) => setBrandId(e.target.value)} data-testid="booking-brand">
              <option value="">Select brand…</option>
              {brands.map((b: any) => <option key={b.id} value={b.id}>{b.name}</option>)}
            </select>
          </div>
          <div className="field"><label>Season</label>
            <select className="select" value={seasonId} onChange={(e) => setSeasonId(e.target.value)} data-testid="booking-season">
              <option value="">Select season…</option>
              {seasons.map((s: any) => <option key={s.id} value={s.id}>{s.name}</option>)}
            </select>
          </div>
          <div className="field"><label>Default destination store (optional)</label>
            <select className="select" value={destId} onChange={(e) => setDestId(e.target.value)} data-testid="booking-dest">
              <option value="">Warehouse / unspecified</option>
              {stores.map((s: any) => <option key={s.id} value={s.id}>{s.code} · {s.name}</option>)}
            </select>
          </div>
          <div className="field"><label>Vendor reference</label>
            <input className="input" value={vendorRef} onChange={(e) => setVendorRef(e.target.value)} placeholder="PO / order no." data-testid="booking-ref" />
          </div>
        </div>
      </div>

      <div className="card section-card">
        <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 10 }}>
          <div><p className="eyebrow">Step 3 · Lines</p><h3 className="h3">Style · size · quantity</h3></div>
          <button className="btn" onClick={() => setLines((l) => [...l, emptyLine()])} data-testid="add-line"><Plus size={15} /> Add line</button>
        </div>
        <p className="hint" style={{ marginBottom: 10 }}>Leave a line's store blank to send it to the booking default destination.</p>
        <table className="lines-table" data-testid="booking-lines">
          <thead><tr><th style={{ width: "22%" }}>Style code</th><th>Size</th><th style={{ width: "22%" }}>Description</th><th>Qty</th><th>MRP ₹</th><th style={{ width: "20%" }}>Store</th><th /></tr></thead>
          <tbody>
            {lines.map((l, i) => (
              <tr key={i}>
                <td><input value={l.style_code} onChange={(e) => setLine(i, "style_code", e.target.value)} /></td>
                <td><input value={l.size} onChange={(e) => setLine(i, "size", e.target.value)} /></td>
                <td><input value={l.description} onChange={(e) => setLine(i, "description", e.target.value)} /></td>
                <td><input className="num" value={l.booked_qty} onChange={(e) => setLine(i, "booked_qty", e.target.value)} /></td>
                <td><input className="num" value={l.mrp} onChange={(e) => setLine(i, "mrp", e.target.value)} /></td>
                <td>
                  <select className="select" value={l.store} onChange={(e) => setLine(i, "store", e.target.value)} data-testid={`booking-line-store-${i}`}>
                    <option value="">Default</option>
                    {stores.map((s: any) => <option key={s.id} value={s.id}>{s.code}</option>)}
                  </select>
                </td>
                <td><button className="line-del" onClick={() => setLines((ls) => ls.filter((_, idx) => idx !== i))}><Trash2 size={15} /></button></td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {error && <div className="login-error" style={{ maxWidth: 480 }}>{error}</div>}
      <button className="btn btn-primary btn-lg" disabled={saving} onClick={save} data-testid="save-booking">
        {saving ? "Saving…" : "Confirm & book"}
      </button>
    </div>
  );
}

/** Short-close or cancel, for whoever holds the Booking *Approve* cell.
 *
 *  `Status.CLOSED` and `Status.CANCELLED` existed on the model from the first
 *  migration and nothing could ever reach them, so a season that delivered 40 of
 *  100 pieces stayed "Partially received" for ever and the open-order figure
 *  counted 60 pieces nobody was waiting for. The reason is mandatory: it is the
 *  answer to "why did the rest never come?" six months later. */
function EndBooking({ booking, onDone }: { booking: BookingT; onDone: () => void }) {
  const [open, setOpen] = useState(false);
  const [action, setAction] = useState<"close" | "cancel">("close");
  const [reason, setReason] = useState("");
  const [error, setError] = useState("");
  const [saving, setSaving] = useState(false);
  const nothingReceived = booking.received_total === 0;

  async function submit() {
    setSaving(true);
    setError("");
    try {
      await api.post(`/bookings/${booking.id}/close`, { action, reason });
      setOpen(false);
      setReason("");
      onDone();
    } catch (e) {
      setError(apiErrorMessage(e));
    } finally {
      setSaving(false);
    }
  }

  if (!open) {
    return (
      <button className="btn" onClick={() => setOpen(true)} data-testid="end-booking-btn">
        <XCircle size={15} /> Close booking
      </button>
    );
  }

  return (
    <div className="card section-card" style={{ marginBottom: 18 }} data-testid="end-booking-panel">
      <div className="toolbar" style={{ marginBottom: 10 }}>
        <div>
          <p className="eyebrow">Ending this booking</p>
          <h3 className="h3">
            {action === "cancel"
              ? "Cancel — nothing was received"
              : `Short-close — write off ${booking.open_qty} undelivered piece(s)`}
          </h3>
        </div>
        <div className="spacer" />
        <button className="btn btn-sm" onClick={() => setOpen(false)} data-testid="end-booking-cancel">Keep it open</button>
      </div>
      <div className="seg" style={{ marginBottom: 10 }}>
        <button
          className={`seg-btn ${action === "close" ? "active" : ""}`}
          onClick={() => setAction("close")}
          data-testid="end-action-close"
        >
          Short-close
        </button>
        <button
          className={`seg-btn ${action === "cancel" ? "active" : ""}`}
          onClick={() => setAction("cancel")}
          disabled={!nothingReceived}
          title={nothingReceived ? undefined : "Goods have already arrived — short-close it instead"}
          data-testid="end-action-cancel"
        >
          Cancel
        </button>
      </div>
      <input
        className="input"
        placeholder="Why is this booking ending? (e.g. season over, vendor short-shipped 60 pcs)"
        value={reason}
        onChange={(e) => setReason(e.target.value)}
        data-testid="end-booking-reason"
      />
      {error && <div className="warn-note" style={{ marginTop: 10 }} data-testid="end-booking-error">{error}</div>}
      <button
        className="btn btn-cta"
        style={{ marginTop: 12 }}
        disabled={reason.trim().length < 3 || saving}
        onClick={submit}
        data-testid="end-booking-confirm"
      >
        {saving ? "Recording…" : action === "cancel" ? "Cancel this booking" : "Short-close this booking"}
      </button>
    </div>
  );
}

/** Send a drafted booking for the Owner's signature (D11 §3).
 *
 *  The maker's last act on their own commitment. A booking used to be created
 *  `booked` outright, which made the Owner's `booking: approve` cell decide
 *  nothing; now the only road from draft to booked runs through the inbox. */
function SendBookingForApproval({ booking, onDone }: { booking: BookingT; onDone: () => void }) {
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");

  async function submit() {
    setSaving(true);
    setError("");
    try {
      await api.post(`/bookings/${booking.id}/request-approval`, {});
      onDone();
    } catch (e) {
      setError(apiErrorMessage(e));
    } finally {
      setSaving(false);
    }
  }

  return (
    <>
      <button
        className="btn btn-cta"
        disabled={saving}
        onClick={submit}
        data-testid="booking-send-approval"
      >
        <Send size={15} /> {saving ? "Sending…" : "Send for approval"}
      </button>
      {error && (
        <span className="warn-note" data-testid="booking-send-error">
          {error}
        </span>
      )}
    </>
  );
}

export function BookingDetailPage() {
  const { id } = useParams();
  const { user } = useAuth();
  const { data: b, loading, reload } = useDoc<BookingT>(`/bookings/${id}`);
  // Same rung the server checks (`vendors.CanCloseBooking` = booking:approve).
  const canEnd = userCan(user, "booking", "approve");
  // The maker's rung: whoever may place a booking may send their own for signing.
  const canSend = userCan(user, "booking", "operate");
  if (loading || !b) return <div className="page-pad"><p className="lead">Loading…</p></div>;
  const ended = b.status === "closed" || b.status === "cancelled";
  return (
    <div className="page-pad">
      <PageHeader
        title={b.brand_name}
        lead={`${b.number} · ${b.vendor_name} · ${b.season_name}${b.destination_store_name ? ` · → ${b.destination_store_name}` : ""}`}
        actions={
          <>
            <StatusPill status={b.status} label={b.status_label} />
            {b.status === "draft" && canSend && (
              <SendBookingForApproval booking={b} onDone={reload} />
            )}
            {!ended && b.status !== "draft" && b.status !== "submitted" && (
              <Link className="btn btn-cta" to={`/receive/new?booking=${b.id}`} data-testid="goto-receive"><FileUp size={15} /> Receive</Link>
            )}
            {!ended && canEnd && <EndBooking booking={b} onDone={reload} />}
          </>
        }
      />

      {b.status === "submitted" && (
        <div className="card section-card" style={{ marginBottom: 18 }} data-testid="booking-waiting-note">
          <p className="eyebrow">Waiting for a signature</p>
          <h3 className="h3">
            {b.estimated_value_paise ? <Money paise={b.estimated_value_paise} short /> : "This booking"} is in the approvals inbox
          </h3>
          <p className="lead">
            The Owner signs a commitment; the person who placed it cannot. Goods cannot be received
            against it until it is signed.
          </p>
        </div>
      )}

      {ended && (
        <div className="card section-card" style={{ marginBottom: 18 }} data-testid="booking-ended-note">
          <p className="eyebrow">{b.status === "cancelled" ? "Cancelled" : "Short-closed"}</p>
          <h3 className="h3">{b.close_reason || "No reason recorded"}</h3>
          <p className="lead">
            {b.closed_by_name ? `${b.closed_by_name} · ` : ""}
            {b.closed_at ? new Date(b.closed_at).toLocaleString("en-IN") : ""}
            {b.open_qty > 0 && b.status === "closed" ? ` · ${b.open_qty} piece(s) written off` : ""}
          </p>
        </div>
      )}

      <div className="form-row" style={{ marginBottom: 18 }}>
        <div className="card section-card"><p className="eyebrow">Commercial model</p><h3 className="h3" style={{ textTransform: "capitalize" }}>{b.ownership.replace("_", " ")} · {b.return_terms}</h3></div>
        <div className="card section-card"><p className="eyebrow">Booked</p><h3 className="h3">{b.booked_total} pcs</h3></div>
        <div className="card section-card"><p className="eyebrow">Received</p><h3 className="h3">{b.received_total} pcs</h3></div>
        <div className="card section-card"><p className="eyebrow">Est. order value</p><h3 className="h3">{b.estimated_value_paise ? <Money paise={b.estimated_value_paise} short /> : "—"}</h3></div>
      </div>

      <div className="table-wrap">
        <table className="data" data-testid="booking-detail-lines">
          <thead><tr><th>Style</th><th>Size</th><th>Description</th><th>Destination</th><th className="num">Booked</th><th className="num">Received</th><th className="num">Inwarded</th><th className="num">MRP</th></tr></thead>
          <tbody>
            {b.lines.map((l) => (
              <tr key={l.id}>
                <td><b className="mono">{l.style_code}</b></td>
                <td>{l.size}</td>
                <td>{l.description || "—"}</td>
                <td>{l.store_name ?? b.destination_store_name ?? "Warehouse"}</td>
                <td className="num">{l.booked_qty}</td>
                <td className="num">{l.received_qty}</td>
                <td className="num">{l.inwarded_qty}</td>
                <td className="num">{l.mrp_paise ? <Money paise={l.mrp_paise} /> : "—"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
