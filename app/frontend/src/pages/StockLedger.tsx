import { useEffect, useMemo, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { Boxes, IndianRupee, Layers, PackageCheck, ScrollText } from "lucide-react";

import { api } from "../lib/api";
import "./Booking.css";
import "./PtMapper.css";

interface EntryT {
  id: number;
  created_at: string;
  doc_number: string;
  kind: string;
  kind_label: string;
  store_code: string;
  sku_code: string;
  design: string;
  color: string;
  size: string;
  brand: string;
  season: string;
  item: string;
  qty: number;
  value_rupees: string;
  source_file: string;
  booking_number: string;
}

interface SummaryT {
  entries: number;
  net_qty: number;
  net_value_rupees: string;
  distinct_skus: number;
  distinct_documents: number;
}

export default function StockLedger() {
  const [params] = useSearchParams();
  const docFilter = params.get("doc") || "";
  const fileFilter = params.get("file") || "";
  const [entries, setEntries] = useState<EntryT[]>([]);
  const [summary, setSummary] = useState<SummaryT | null>(null);
  const [loading, setLoading] = useState(true);
  const [page, setPage] = useState(1);
  const [count, setCount] = useState(0);
  const [hasNext, setHasNext] = useState(false);
  const PAGE_SIZE = 50;

  useEffect(() => setPage(1), [docFilter, fileFilter]);

  useEffect(() => {
    setLoading(true);
    const q = new URLSearchParams();
    if (fileFilter) q.set("pt_file", fileFilter);
    else if (docFilter) q.set("doc_number", docFilter);
    q.set("page", String(page));
    q.set("page_size", String(PAGE_SIZE));
    Promise.all([
      api.get(`/stockledger/entries?${q.toString()}`).then((r) => {
        setEntries(r.data.results);
        setCount(r.data.count);
        setHasNext(Boolean(r.data.next));
      }),
      api.get(`/stockledger/summary`).then((r) => setSummary(r.data)),
    ]).finally(() => setLoading(false));
  }, [docFilter, fileFilter, page]);

  const cards = useMemo(
    () => [
      { icon: ScrollText, label: "Ledger entries", value: summary?.entries ?? 0 },
      { icon: Boxes, label: "Net units on hand", value: summary?.net_qty ?? 0 },
      { icon: IndianRupee, label: "Net stock value (₹)", value: summary?.net_value_rupees ?? "0.00" },
      { icon: Layers, label: "Distinct SKUs", value: summary?.distinct_skus ?? 0 },
    ],
    [summary],
  );

  return (
    <div className="page-pad">
      <div className="toolbar">
        <div>
          <p className="eyebrow">Ledgers · append-only (corrections are reversing entries)</p>
          <h1 className="h1 h2-rust">Stock Ledger</h1>
        </div>
        <div className="spacer" />
        <Link className="btn" to="/ledgers/stock-on-hand" data-testid="stock-on-hand-link"><PackageCheck size={16} /> Stock on Hand</Link>
      </div>

      <div className="stat-grid" data-testid="stock-summary">
        {cards.map((c) => (
          <div className="card stat-card" key={c.label}>
            <c.icon size={18} style={{ color: "var(--rust)" }} />
            <div className="stat-value mono">{c.value}</div>
            <div className="stat-label">{c.label}</div>
          </div>
        ))}
      </div>

      {(docFilter || fileFilter) && (
        <div className="ai-note" data-testid="stock-doc-filter" style={{ marginTop: 12 }}>
          {fileFilter
            ? <>Showing all stock movements (inward + any reversals) for this PT file.</>
            : <>Showing entries for voucher <b className="mono">{docFilter}</b>.</>}
        </div>
      )}

      {loading ? (
        <p className="lead">Loading…</p>
      ) : entries.length === 0 ? (
        <div className="card section-card" data-testid="stock-empty">
          No stock postings yet. Post a PT file from Patna (PT Mapper → Push into system) to write the first inward.
        </div>
      ) : (
        <div className="table-wrap kdps-scroll" style={{ marginTop: 16 }}>
          <table className="data kdps-table" data-testid="stock-entries-table">
            <thead>
              <tr>
                <th>Voucher</th>
                <th>Type</th>
                <th>Store</th>
                <th>Barcode (SKU)</th>
                <th>Brand</th>
                <th>Design</th>
                <th>Colour</th>
                <th>Size</th>
                <th>Item</th>
                <th>Season</th>
                <th className="num">Qty</th>
                <th className="num">Value ₹</th>
                <th>Booking</th>
              </tr>
            </thead>
            <tbody>
              {entries.map((e) => (
                <tr key={e.id} data-testid={`stock-entry-${e.id}`}>
                  <td className="mono">{e.doc_number}</td>
                  <td>
                    <span className={`chip chip-${e.kind === "pt_inward" ? "green" : "red"}`}>{e.kind_label}</span>
                  </td>
                  <td>{e.store_code}</td>
                  <td className="mono">{e.sku_code}</td>
                  <td>{e.brand}</td>
                  <td>{e.design}</td>
                  <td>{e.color}</td>
                  <td>{e.size}</td>
                  <td>{e.item}</td>
                  <td>{e.season}</td>
                  <td className="num" style={{ color: e.qty < 0 ? "var(--red, #c0392b)" : "inherit", fontWeight: 700 }}>{e.qty}</td>
                  <td className="num mono">{e.value_rupees}</td>
                  <td>{e.booking_number || "—"}</td>
                </tr>
              ))}
            </tbody>
          </table>
          <div className="pager" data-testid="stock-pager">
            <span className="pager-info">
              Showing {(page - 1) * PAGE_SIZE + 1}–{(page - 1) * PAGE_SIZE + entries.length} of {count}
            </span>
            <div className="spacer" />
            <button className="btn btn-sm" disabled={page <= 1} onClick={() => setPage((p) => p - 1)} data-testid="stock-prev">Prev</button>
            <span className="pager-page">Page {page}</span>
            <button className="btn btn-sm" disabled={!hasNext} onClick={() => setPage((p) => p + 1)} data-testid="stock-next">Next</button>
          </div>
        </div>
      )}
    </div>
  );
}
