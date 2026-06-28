import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { Boxes, IndianRupee, Layers, ScrollText } from "lucide-react";

import { api, apiErrorMessage } from "../lib/api";
import "./Booking.css";
import "./PtMapper.css";

type Group = "sku" | "brand" | "store";

interface RowT {
  store_code: string;
  store_name: string;
  brand: string;
  design: string;
  color: string;
  size: string;
  item: string;
  season: string;
  sku_code: string;
  net_qty: number;
  skus: number;
  net_value_rupees: string;
}

interface OnHandT {
  group_by: Group;
  summary: { units_on_hand: number; value_rupees: string; lines: number };
  rows: RowT[];
}

const TABS: { key: Group; label: string }[] = [
  { key: "sku", label: "By SKU" },
  { key: "brand", label: "By Brand" },
  { key: "store", label: "By Store" },
];

export default function StockOnHand() {
  const [group, setGroup] = useState<Group>("sku");
  const [data, setData] = useState<OnHandT | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  useEffect(() => {
    setLoading(true);
    setError("");
    api.get(`/stockledger/on-hand?group_by=${group}`)
      .then((r) => setData(r.data))
      .catch((e) => setError(apiErrorMessage(e)))
      .finally(() => setLoading(false));
  }, [group]);

  const cards = [
    { icon: Boxes, label: "Units on hand", value: data?.summary.units_on_hand ?? 0 },
    { icon: IndianRupee, label: "Stock value (₹)", value: data?.summary.value_rupees ?? "0.00" },
    { icon: Layers, label: group === "store" ? "Stores" : group === "brand" ? "Brands" : "SKU lines", value: data?.summary.lines ?? 0 },
  ];

  return (
    <div className="page-pad">
      <div className="toolbar">
        <div>
          <p className="eyebrow">Ledgers · live net position from the stock ledger</p>
          <h1 className="h1 h2-rust">Stock on Hand</h1>
        </div>
        <div className="spacer" />
        <Link className="btn" to="/ledgers/stock" data-testid="stock-ledger-link"><ScrollText size={16} /> Stock Ledger</Link>
      </div>

      <div className="seg" data-testid="onhand-tabs">
        {TABS.map((t) => (
          <button
            key={t.key}
            className={`seg-btn ${group === t.key ? "active" : ""}`}
            onClick={() => setGroup(t.key)}
            data-testid={`onhand-tab-${t.key}`}
          >
            {t.label}
          </button>
        ))}
      </div>

      <div className="stat-grid" data-testid="onhand-summary">
        {cards.map((c) => (
          <div className="card stat-card" key={c.label}>
            <c.icon size={18} style={{ color: "var(--rust)" }} />
            <div className="stat-value mono">{c.value}</div>
            <div className="stat-label">{c.label}</div>
          </div>
        ))}
      </div>

      {loading ? (
        <p className="lead">Loading…</p>
      ) : error ? (
        <div className="warn-note" data-testid="onhand-error">{error}</div>
      ) : !data || data.rows.length === 0 ? (
        <div className="card section-card" data-testid="onhand-empty">
          No stock on hand yet. Post a PT file from Patna (PT Mapper → Push into system) to build inventory.
        </div>
      ) : (
        <div className="table-wrap kdps-scroll" style={{ marginTop: 16 }}>
          <table className="data kdps-table" data-testid="onhand-table">
            <thead>
              <tr>
                {group === "sku" && (
                  <>
                    <th>Barcode (SKU)</th><th>Brand</th><th>Design</th><th>Colour</th>
                    <th>Size</th><th>Item</th><th>Season</th><th>Store</th>
                  </>
                )}
                {group === "brand" && (<><th>Brand</th><th>Store</th><th className="num">SKUs</th></>)}
                {group === "store" && (<><th>Store</th><th>Name</th><th className="num">SKUs</th></>)}
                <th className="num">Units</th>
                <th className="num">Value ₹</th>
              </tr>
            </thead>
            <tbody>
              {data.rows.map((r, i) => (
                <tr key={i} data-testid={`onhand-row-${i}`}>
                  {group === "sku" && (
                    <>
                      <td className="mono">{r.sku_code}</td><td>{r.brand}</td><td>{r.design}</td>
                      <td>{r.color}</td><td>{r.size}</td><td>{r.item}</td><td>{r.season}</td>
                      <td>{r.store_code}</td>
                    </>
                  )}
                  {group === "brand" && (<><td><b>{r.brand}</b></td><td>{r.store_code}</td><td className="num">{r.skus}</td></>)}
                  {group === "store" && (<><td className="mono">{r.store_code}</td><td>{r.store_name}</td><td className="num">{r.skus}</td></>)}
                  <td className="num" style={{ fontWeight: 700 }}>{r.net_qty}</td>
                  <td className="num mono">{r.net_value_rupees}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
