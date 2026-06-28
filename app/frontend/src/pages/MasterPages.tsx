import { useEffect, useState } from "react";
import type { ReactNode } from "react";

import { api } from "../lib/api";
import { CommercialBadge, StatusChip } from "../lib/format";

function useList<T>(url: string) {
  const [data, setData] = useState<T[]>([]);
  const [loading, setLoading] = useState(true);
  useEffect(() => {
    let live = true;
    api
      .get(url)
      .then((r) => live && setData(r.data))
      .finally(() => live && setLoading(false));
    return () => {
      live = false;
    };
  }, [url]);
  return { data, loading };
}

function Screen({
  eyebrow,
  title,
  count,
  children,
}: {
  eyebrow: string;
  title: string;
  count: number;
  children: ReactNode;
}) {
  return (
    <div className="page-pad">
      <p className="eyebrow">{eyebrow}</p>
      <h1 className="h1 h2-rust" style={{ marginBottom: 4 }}>{title}</h1>
      <p className="lead" style={{ marginBottom: 20 }}>{count} record{count === 1 ? "" : "s"}</p>
      {children}
    </div>
  );
}

interface Store {
  id: number;
  code: string;
  name: string;
  store_type: string;
  city: string;
  state_name: string;
  gstin_number: string;
}

export function StoresPage() {
  const { data } = useList<Store>("/masters/stores");
  return (
    <Screen eyebrow="Master data" title="Stores & Warehouses" count={data.length}>
      <div className="table-wrap">
        <table className="data" data-testid="stores-table">
          <thead>
            <tr>
              <th>Code</th>
              <th>Name</th>
              <th>Type</th>
              <th>City</th>
              <th>State</th>
              <th>GSTIN</th>
            </tr>
          </thead>
          <tbody>
            {data.map((s) => (
              <tr key={s.id} data-testid={`store-row-${s.code}`}>
                <td><b className="mono">{s.code}</b></td>
                <td>{s.name}</td>
                <td><StatusChip status={s.store_type} tone={s.store_type === "warehouse" ? "navy" : "green"} /></td>
                <td>{s.city || "—"}</td>
                <td><span className={`chip chip-${s.state_name === "Bihar" ? "amber" : "blue"}`}>{s.state_name}</span></td>
                <td className="mono" style={{ fontSize: 12.5 }}>{s.gstin_number}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </Screen>
  );
}

interface Brand {
  id: number;
  code: string;
  name: string;
  ownership: string;
  return_terms: string;
  commercial_label: string;
}

export function BrandsPage() {
  const { data } = useList<Brand>("/masters/brands");
  return (
    <Screen eyebrow="Master data" title="Brands" count={data.length}>
      <div className="table-wrap">
        <table className="data" data-testid="brands-table">
          <thead>
            <tr>
              <th>Brand</th>
              <th>Ownership</th>
              <th>Return terms</th>
              <th>Commercial model</th>
            </tr>
          </thead>
          <tbody>
            {data.map((b) => (
              <tr key={b.id} data-testid={`brand-row-${b.code}`}>
                <td><b>{b.name}</b></td>
                <td>{b.ownership === "owned" ? "KDPS-owned" : "Brand-owned"}</td>
                <td style={{ textTransform: "capitalize" }}>{b.return_terms}</td>
                <td><CommercialBadge label={b.commercial_label} /></td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </Screen>
  );
}

interface Season {
  id: number;
  code: string;
  name: string;
  status: string;
  sort_order: number;
}

export function SeasonsPage() {
  const { data } = useList<Season>("/masters/seasons");
  return (
    <Screen eyebrow="Master data" title="Season Calendar" count={data.length}>
      <div className="table-wrap">
        <table className="data" data-testid="seasons-table">
          <thead>
            <tr>
              <th>Code</th>
              <th>Name</th>
              <th>Status</th>
            </tr>
          </thead>
          <tbody>
            {data.map((s) => (
              <tr key={s.id} data-testid={`season-row-${s.code}`}>
                <td><b className="mono">{s.code}</b></td>
                <td>{s.name}</td>
                <td><StatusChip status={s.status} /></td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </Screen>
  );
}

interface Gstin {
  id: number;
  gstin: string;
  state_name: string;
  state_code: string;
  legal_entity_name: string;
}

export function GstinsPage() {
  const { data } = useList<Gstin>("/masters/gstins");
  return (
    <Screen eyebrow="Master data" title="GSTIN Registry" count={data.length}>
      <div className="table-wrap">
        <table className="data" data-testid="gstins-table">
          <thead>
            <tr>
              <th>GSTIN</th>
              <th>State</th>
              <th>State code</th>
              <th>Legal entity</th>
            </tr>
          </thead>
          <tbody>
            {data.map((g) => (
              <tr key={g.id} data-testid={`gstin-row-${g.state_code}`}>
                <td className="mono"><b>{g.gstin}</b></td>
                <td><span className={`chip chip-${g.state_name === "Bihar" ? "amber" : "blue"}`}>{g.state_name}</span></td>
                <td className="mono">{g.state_code}</td>
                <td>{g.legal_entity_name}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </Screen>
  );
}
