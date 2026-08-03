// Partner dues — what each partner store owes, summed off the Purchase-Price
// figure every transfer to it already carries (`partner_billing_value_paise`).
// Reads the same figure regardless of `BillingPolicy.mode` (Rule 12): whether
// or not that figure ever reached the ledger, this report means the same
// thing, since nothing here is netted against a payment — there is no partner
// payment/settlement flow yet, so "owed" is simply the running total billed.
import { useState, Fragment } from "react";
import { Link } from "react-router-dom";
import { ChevronDown, ChevronRight } from "lucide-react";

import { PageHeader } from "../components/PageHeader";
import { Money } from "../lib/format";
import { useDoc } from "../lib/hooks";

interface DueTransfer {
  id: number;
  doc_number: string | null;
  source_store_code: string;
  dispatch_date: string | null;
  partner_billing_value_paise: number;
}

interface DueStore {
  store_id: number;
  store_code: string;
  store_name: string;
  total_owed_paise: number;
  transfer_count: number;
  last_dispatch_date: string | null;
  transfers: DueTransfer[];
}

interface PartnerDuesResponse {
  stores: DueStore[];
  total_owed_paise: number;
  billing_mode: "informational" | "gl_posting";
}

function fmtDate(iso: string | null): string {
  return iso ? new Date(iso).toLocaleDateString("en-IN") : "—";
}

export function PartnerDuesPage() {
  const { data: resp, loading } = useDoc<PartnerDuesResponse>("/outbound/partner-dues");
  const [open, setOpen] = useState<number | null>(null);
  const stores = resp?.stores ?? [];

  return (
    <div className="page-pad">
      <PageHeader lead="What every partner store owes so far, at Purchase Price — the same figure each transfer to it already shows on its own detail page. Nothing here is a payment ledger yet: this is a running total billed, not netted against anything received." />
      {loading ? (
        <p>Loading…</p>
      ) : stores.length === 0 ? (
        <p className="muted-cell" data-testid="partner-dues-empty">
          No partner store has been billed yet — mark a store "Partner" in Setup → Stores, then dispatch a
          transfer to it.
        </p>
      ) : (
        <>
          <div className="card section-card" style={{ marginBottom: 18 }}>
            <p className="eyebrow">Total owed, all partner stores</p>
            <h2 className="h2"><Money paise={resp!.total_owed_paise} /></h2>
            <p className="muted-cell">
              Billing policy is currently{" "}
              <b>{resp!.billing_mode === "gl_posting" ? "posting a receivable" : "informational only"}</b> —{" "}
              <Link to="/money/partner-billing">change it here</Link>.
            </p>
          </div>
          <div className="table-wrap">
            <table className="data" data-testid="partner-dues-table">
              <thead>
                <tr>
                  <th />
                  <th>Store</th>
                  <th className="num">Owed</th>
                  <th className="num">Transfers</th>
                  <th>Last dispatch</th>
                </tr>
              </thead>
              <tbody>
                {stores.map((s) => {
                  const expanded = open === s.store_id;
                  return (
                    <Fragment key={s.store_id}>
                      <tr data-testid={`partner-due-row-${s.store_code}`}>
                        <td>
                          <button
                            type="button"
                            className="btn btn-sm"
                            onClick={() => setOpen(expanded ? null : s.store_id)}
                            data-testid={`partner-due-toggle-${s.store_code}`}
                            aria-expanded={expanded}
                          >
                            {expanded ? <ChevronDown size={13} /> : <ChevronRight size={13} />}
                          </button>
                        </td>
                        <td><b className="mono">{s.store_code}</b> — {s.store_name}</td>
                        <td className="num"><b><Money paise={s.total_owed_paise} /></b></td>
                        <td className="num">{s.transfer_count}</td>
                        <td>{fmtDate(s.last_dispatch_date)}</td>
                      </tr>
                      {expanded && (
                        <tr>
                          <td />
                          <td colSpan={4}>
                            <table className="data" data-testid={`partner-due-detail-${s.store_code}`}>
                              <thead>
                                <tr><th>Transfer</th><th>From</th><th>Dispatched</th><th className="num">Billed</th></tr>
                              </thead>
                              <tbody>
                                {s.transfers.map((t) => (
                                  <tr key={t.id}>
                                    <td>
                                      <Link to={`/transfer/${t.id}`} className="mono">
                                        {t.doc_number || `Draft #${t.id}`}
                                      </Link>
                                    </td>
                                    <td>{t.source_store_code}</td>
                                    <td>{fmtDate(t.dispatch_date)}</td>
                                    <td className="num"><Money paise={t.partner_billing_value_paise} /></td>
                                  </tr>
                                ))}
                              </tbody>
                            </table>
                          </td>
                        </tr>
                      )}
                    </Fragment>
                  );
                })}
              </tbody>
            </table>
          </div>
        </>
      )}
    </div>
  );
}

export default PartnerDuesPage;
