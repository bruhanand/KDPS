// Distribution grid — Ops Head enters qty-per-store for stock that has arrived
// at a warehouse, and this bulk-creates one draft `store_split` transfer per
// destination store. Nothing new posts underneath it: every draft goes through
// the same approval → scan-and-dispatch → receive pipeline as a transfer raised
// one at a time on "Send Stock" — this screen only saves the Ops Head from
// doing that N times for one arrived batch.
import { useMemo, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { ArrowLeft, CheckCircle2, Plus, RefreshCw, Send, Trash2, XCircle } from "lucide-react";

import { api, apiErrorMessage } from "../lib/api";
import { useList } from "../lib/hooks";
import { PageHeader } from "../components/PageHeader";

interface StoreT {
  id: number;
  code: string;
  name: string;
  store_type: string;
  gstin: number;
  is_partner: boolean;
  is_active: boolean;
}

interface StockRow {
  store_code: string;
  sku_code: string;
  design: string;
  color: string;
  size: string;
  brand: string;
  qty: number;
  is_own: boolean;
}

interface GridRow {
  sku_code: string;
  label: string;
  available: number;
  qtyByDest: Record<string, string>;
}

function rowTotal(row: GridRow): number {
  return Object.values(row.qtyByDest).reduce((s, v) => s + (Number(v) || 0), 0);
}

/** A starting point, not a decision: split what's available as evenly as the
 *  arithmetic allows across the stores picked so far, so the grid opens with a
 *  sane guess instead of a wall of blanks — Ops Head edits any cell freely
 *  from there. The remainder (available % stores) goes to the earliest-picked
 *  stores, which is as good a tie-break as any and at least a stable one. */
function equalSplit(available: number, destIds: string[]): Record<string, string> {
  if (destIds.length === 0 || available <= 0) return {};
  const base = Math.floor(available / destIds.length);
  const remainder = available % destIds.length;
  const out: Record<string, string> = {};
  destIds.forEach((d, i) => {
    const qty = base + (i < remainder ? 1 : 0);
    if (qty > 0) out[d] = String(qty);
  });
  return out;
}

export function DistributionGridPage() {
  const navigate = useNavigate();
  const { data: stores } = useList<StoreT>("/masters/stores");
  const warehouses = useMemo(() => stores.filter((s) => s.store_type === "warehouse"), [stores]);

  const [sourceId, setSourceId] = useState("");
  const [destIds, setDestIds] = useState<string[]>([]);
  const [ewayBills, setEwayBills] = useState<Record<string, string>>({});
  const [term, setTerm] = useState("");
  const [results, setResults] = useState<StockRow[]>([]);
  const [searching, setSearching] = useState(false);
  const [rows, setRows] = useState<GridRow[]>([]);
  const [error, setError] = useState("");
  const [saving, setSaving] = useState(false);
  const [outcome, setOutcome] = useState<{ dest: string; ok: boolean; detail: string }[] | null>(null);

  const source = stores.find((s) => String(s.id) === sourceId) || null;
  // Every other active store is a candidate destination — a partner franchisee
  // is not excluded, that is the whole point of the flag (#see Setup → Stores).
  const destinationOptions = useMemo(
    () => stores.filter((s) => s.is_active && String(s.id) !== sourceId && s.store_type === "store"),
    [stores, sourceId],
  );

  function toggleDest(id: string) {
    setDestIds((ds) => (ds.includes(id) ? ds.filter((d) => d !== id) : [...ds, id]));
  }

  function crossState(dest: StoreT): boolean {
    return !!source && source.gstin !== dest.gstin;
  }

  async function search() {
    if (!source || !term.trim()) { setResults([]); return; }
    setSearching(true);
    try {
      const { data } = await api.get<{ rows: StockRow[] }>(
        `/outbound/stock-search?store=${source.code}&q=${encodeURIComponent(term.trim())}`,
      );
      setResults(data.rows.filter((r) => r.qty > 0));
    } catch {
      setResults([]);
    } finally {
      setSearching(false);
    }
  }

  function addRow(r: StockRow) {
    if (rows.some((row) => row.sku_code === r.sku_code)) return;
    setRows((rs) => [
      ...rs,
      {
        sku_code: r.sku_code,
        label: [r.design, r.color, r.size].filter(Boolean).join(" · ") || r.brand,
        available: r.qty,
        qtyByDest: equalSplit(r.qty, destIds),
      },
    ]);
    setResults([]);
    setTerm("");
  }

  function removeRow(sku: string) {
    setRows((rs) => rs.filter((r) => r.sku_code !== sku));
  }

  function resplitRow(sku: string) {
    setRows((rs) =>
      rs.map((r) => (r.sku_code === sku ? { ...r, qtyByDest: equalSplit(r.available, destIds) } : r)),
    );
  }

  function setQty(sku: string, dest: string, val: string) {
    setRows((rs) =>
      rs.map((r) => (r.sku_code === sku ? { ...r, qtyByDest: { ...r.qtyByDest, [dest]: val } } : r)),
    );
  }

  async function submit() {
    setError("");
    setOutcome(null);
    if (!source) { setError("Select a source warehouse."); return; }
    if (destIds.length === 0) { setError("Select at least one destination store."); return; }
    for (const row of rows) {
      if (rowTotal(row) > row.available) {
        setError(`${row.sku_code}: allocated (${rowTotal(row)}) exceeds available (${row.available}).`);
        return;
      }
    }
    const activeDests = destIds.filter((d) => rows.some((r) => Number(r.qtyByDest[d]) > 0));
    if (activeDests.length === 0) { setError("Enter at least one quantity for a selected store."); return; }
    for (const d of activeDests) {
      const dest = destinationOptions.find((s) => String(s.id) === d);
      if (dest && crossState(dest) && !(ewayBills[d] || "").trim()) {
        setError(`${dest.code} is cross-state — an e-way bill number is required for it.`);
        return;
      }
    }

    setSaving(true);
    const results = await Promise.allSettled(
      activeDests.map((d) => {
        const dest = destinationOptions.find((s) => String(s.id) === d)!;
        const lines = rows
          .map((r) => ({ sku_code: r.sku_code, qty_planned: Number(r.qtyByDest[d]) || 0 }))
          .filter((l) => l.qty_planned > 0);
        return api.post("/outbound/transfers", {
          source_store: source.id,
          destination_store: dest.id,
          transfer_type: source.store_type === "warehouse" ? "store_split" : "inter_store",
          reason: "warehouse_allocation",
          eway_bill_number: ewayBills[d] || "",
          lines,
        }).then((r) => ({ dest: dest.code, ok: true, detail: r.data.doc_number || `Draft #${r.data.id}` }));
      }),
    );
    setOutcome(
      results.map((r, i) => {
        const dest = destinationOptions.find((s) => String(s.id) === activeDests[i])!;
        return r.status === "fulfilled"
          ? r.value
          : { dest: dest.code, ok: false, detail: apiErrorMessage((r as PromiseRejectedResult).reason) };
      }),
    );
    setSaving(false);
  }

  return (
    <div className="page-pad">
      <Link to="/transfer" className="btn" style={{ marginBottom: 16 }} data-testid="distribution-back-link">
        <ArrowLeft size={15} /> Transfers
      </Link>
      <PageHeader
        title="Distribution grid"
        lead="Split one arrived batch across many stores in one pass — enter qty per store, and each store gets its own draft transfer to approve, dispatch and receive as usual."
      />

      {outcome && (
        <div className="card section-card" style={{ marginBottom: 18 }} data-testid="distribution-outcome">
          <p className="eyebrow">Drafts created</p>
          {outcome.map((o) => (
            <div key={o.dest} style={{ display: "flex", gap: 8, alignItems: "center", marginTop: 6 }} data-testid={`distribution-outcome-${o.dest}`}>
              {o.ok ? <CheckCircle2 size={15} color="var(--green)" /> : <XCircle size={15} color="var(--red)" />}
              <b className="mono">{o.dest}</b> — {o.detail}
            </div>
          ))}
          <div className="toolbar" style={{ marginTop: 14 }}>
            <button className="btn btn-cta" onClick={() => navigate("/transfer")} data-testid="distribution-view-transfers">
              View transfers
            </button>
          </div>
        </div>
      )}

      <div className="card section-card">
        <p className="eyebrow">Step 1 · Source warehouse</p>
        <select
          className="select"
          style={{ marginTop: 10, maxWidth: 320 }}
          value={sourceId}
          onChange={(e) => { setSourceId(e.target.value); setDestIds([]); setRows([]); setOutcome(null); }}
          data-testid="distribution-source-select"
        >
          <option value="">Select warehouse…</option>
          {warehouses.map((w) => <option key={w.id} value={w.id}>{w.code} · {w.name}</option>)}
        </select>
      </div>

      {source && (
        <div className="card section-card">
          <p className="eyebrow">Step 2 · Destination stores</p>
          <div style={{ display: "flex", flexWrap: "wrap", gap: 10, marginTop: 10 }}>
            {destinationOptions.map((s) => (
              <label key={s.id} className="check-row" data-testid={`distribution-dest-${s.code}`}>
                <input type="checkbox" checked={destIds.includes(String(s.id))} onChange={() => toggleDest(String(s.id))} />
                {s.code}
                {s.is_partner && <span className="chip chip-amber" style={{ marginLeft: 4 }}>Partner</span>}
              </label>
            ))}
          </div>
          {destIds.some((d) => { const s = destinationOptions.find((x) => String(x.id) === d); return s && crossState(s); }) && (
            <div style={{ marginTop: 14 }}>
              <p className="eyebrow">E-way bill (cross-state destinations)</p>
              <div style={{ display: "flex", gap: 10, flexWrap: "wrap", marginTop: 8 }}>
                {destIds.map((d) => {
                  const s = destinationOptions.find((x) => String(x.id) === d);
                  if (!s || !crossState(s)) return null;
                  return (
                    <input
                      key={d}
                      className="input"
                      placeholder={`${s.code} e-way bill no.`}
                      value={ewayBills[d] || ""}
                      onChange={(e) => setEwayBills({ ...ewayBills, [d]: e.target.value })}
                      data-testid={`distribution-ewaybill-${s.code}`}
                    />
                  );
                })}
              </div>
            </div>
          )}
        </div>
      )}

      {source && destIds.length > 0 && (
        <div className="card section-card">
          <p className="eyebrow">Step 3 · Add arrived SKUs</p>
          <div style={{ display: "flex", gap: 10, marginTop: 10 }}>
            <input
              className="input"
              placeholder="Search barcode, design, brand…"
              value={term}
              onChange={(e) => setTerm(e.target.value)}
              onKeyDown={(e) => e.key === "Enter" && void search()}
              data-testid="distribution-sku-search"
            />
            <button className="btn" onClick={() => void search()} disabled={searching} data-testid="distribution-sku-search-btn">
              {searching ? "Searching…" : "Search"}
            </button>
          </div>
          {results.length > 0 && (
            <div className="table-wrap" style={{ marginTop: 10 }}>
              <table className="data">
                <tbody>
                  {results.map((r) => (
                    <tr key={r.sku_code} data-testid={`distribution-result-${r.sku_code}`}>
                      <td><b className="mono">{r.sku_code}</b></td>
                      <td>{[r.design, r.color, r.size].filter(Boolean).join(" · ") || r.brand}</td>
                      <td className="num">{r.qty} available</td>
                      <td><button className="btn btn-sm" onClick={() => addRow(r)} data-testid={`distribution-add-${r.sku_code}`}><Plus size={13} /> Add</button></td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}

          {rows.length > 0 && (
            <div className="table-wrap" style={{ marginTop: 18 }}>
              <p className="muted-cell" style={{ marginBottom: 8 }}>
                Every row opens with an even split across the stores you picked — edit any cell, or
                <RefreshCw size={11} style={{ verticalAlign: "-1px", margin: "0 3px" }} />
                re-split a row back to even.
              </p>
              <table className="data" data-testid="distribution-grid-table">
                <thead>
                  <tr>
                    <th>SKU</th>
                    <th>Item</th>
                    <th className="num">Available</th>
                    {destIds.map((d) => {
                      const s = destinationOptions.find((x) => String(x.id) === d);
                      return <th key={d} className="num">{s?.code}</th>;
                    })}
                    <th className="num">Allocated</th>
                    <th />
                  </tr>
                </thead>
                <tbody>
                  {rows.map((row) => {
                    const total = rowTotal(row);
                    const over = total > row.available;
                    return (
                      <tr key={row.sku_code} data-testid={`distribution-row-${row.sku_code}`}>
                        <td><b className="mono">{row.sku_code}</b></td>
                        <td>{row.label}</td>
                        <td className="num">{row.available}</td>
                        {destIds.map((d) => (
                          <td key={d} className="num">
                            <input
                              className="input"
                              style={{ width: 70, textAlign: "right" }}
                              inputMode="numeric"
                              value={row.qtyByDest[d] || ""}
                              onChange={(e) => setQty(row.sku_code, d, e.target.value)}
                              data-testid={`distribution-qty-${row.sku_code}-${d}`}
                            />
                          </td>
                        ))}
                        <td className="num">
                          <b style={over ? { color: "var(--red)" } : undefined}>{total}</b>
                        </td>
                        <td>
                          <button
                            type="button"
                            className="btn btn-sm"
                            title="Re-split this row evenly"
                            onClick={() => resplitRow(row.sku_code)}
                            data-testid={`distribution-resplit-${row.sku_code}`}
                          >
                            <RefreshCw size={13} />
                          </button>
                          <button className="btn btn-sm" onClick={() => removeRow(row.sku_code)} data-testid={`distribution-remove-${row.sku_code}`}>
                            <Trash2 size={13} />
                          </button>
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          )}

          {error && <p className="warn-note" style={{ marginTop: 14 }} data-testid="distribution-error">{error}</p>}

          <div className="toolbar" style={{ marginTop: 18 }}>
            <span className="spacer" />
            <button
              type="button"
              className="btn btn-cta"
              disabled={saving || rows.length === 0}
              onClick={() => void submit()}
              data-testid="distribution-submit"
            >
              <Send size={15} /> {saving ? "Creating drafts…" : "Create transfers"}
            </button>
          </div>
        </div>
      )}
    </div>
  );
}

export default DistributionGridPage;
