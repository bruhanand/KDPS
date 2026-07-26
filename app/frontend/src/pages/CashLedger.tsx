import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { ArrowDownCircle, ArrowUpCircle, Plus, RotateCcw, Wallet, X } from "lucide-react";

import { useAuth } from "../auth/AuthContext";
import { userCan } from "../shell/navConfig";
import { api, apiErrorMessage } from "../lib/api";
import "./Booking.css";
import "./PtMapper.css";
import { PageHeader } from "../components/PageHeader";

interface AccountT {
  account: string;
  balance_rupees: string;
  entries: number;
}
interface EntryT {
  id: number;
  created_at: string;
  doc_number: string;
  kind: string;
  kind_label: string;
  account: string;
  amount_rupees: string;
  description: string;
  vendor_name: string;
}

export default function CashLedger() {
  const { user } = useAuth();
  // Mirrors the server gate exactly (`finledger.IsBooksKeeper` = money:manage),
  // read from the same section payload rather than a role list of our own.
  const isFinance = userCan(user, "money", "manage");

  const [summary, setSummary] = useState<{ total_rupees: string; accounts: AccountT[] }>();
  const [entries, setEntries] = useState<EntryT[]>([]);
  const [page, setPage] = useState(1);
  const [count, setCount] = useState(0);
  const [hasNext, setHasNext] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  const [open, setOpen] = useState(false);
  const [form, setForm] = useState({ direction: "in", amount: "", account: "CASH", description: "" });
  const PAGE_SIZE = 50;

  function loadAll() {
    api.get("/finledger/cash/summary").then((r) => setSummary(r.data));
    const q = new URLSearchParams({ page: String(page), page_size: String(PAGE_SIZE) });
    api.get(`/finledger/cash/entries?${q}`).then((r) => {
      setEntries(r.data.results);
      setCount(r.data.count);
      setHasNext(Boolean(r.data.next));
    });
  }
  useEffect(loadAll, [page]);

  async function submit() {
    setBusy(true);
    setError("");
    try {
      await api.post("/finledger/cash/movement", {
        direction: form.direction,
        amount: form.amount,
        account: form.account || "CASH",
        description: form.description,
      });
      setOpen(false);
      setForm({ direction: "in", amount: "", account: "CASH", description: "" });
      setPage(1);
      loadAll();
    } catch (e) {
      setError(apiErrorMessage(e));
    } finally {
      setBusy(false);
    }
  }

  async function reverse(id: number) {
    setBusy(true);
    try {
      await api.post(`/finledger/cash/entries/${id}/reverse`, {});
      loadAll();
    } catch (e) {
      setError(apiErrorMessage(e));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="page-pad" data-testid="cash-ledger-page">
      <PageHeader
        lead="Cash and bank movements. Append-only: a correction is a reversing entry."
        actions={
          isFinance && (
            <button className="btn btn-cta" onClick={() => { setOpen(true); setError(""); }} data-testid="cl-record-btn"><Plus size={15} /> Record Movement</button>
          )
        }
      />

      <div className="stat-grid" data-testid="cl-summary">
        <div className="card stat-card"><Wallet size={18} style={{ color: "var(--rust)" }} /><div className="stat-value mono" data-testid="cl-total">{summary?.total_rupees ?? "0.00"}</div><div className="stat-label">Total cash on hand (₹)</div></div>
        {(summary?.accounts ?? []).map((a) => (
          <div className="card stat-card" key={a.account}>
            <Wallet size={18} style={{ color: "var(--navy)" }} />
            <div className="stat-value mono">{a.balance_rupees}</div>
            <div className="stat-label">{a.account} ({a.entries})</div>
          </div>
        ))}
      </div>

      {open && (
        <div className="card section-card" data-testid="cl-form" style={{ marginTop: 16 }}>
          <div className="toolbar" style={{ marginBottom: 12 }}>
            <h3 className="h3">Record cash movement</h3>
            <div className="spacer" />
            <button className="btn btn-sm" onClick={() => setOpen(false)} data-testid="cl-cancel"><X size={14} /> Cancel</button>
          </div>
          <div className="form-grid">
            <select className="select" value={form.direction} onChange={(e) => setForm({ ...form, direction: e.target.value })} data-testid="cl-direction-select">
              <option value="in">Receipt (cash in)</option>
              <option value="out">Payment (cash out)</option>
            </select>
            <input className="input" type="number" placeholder="Amount ₹" value={form.amount} onChange={(e) => setForm({ ...form, amount: e.target.value })} data-testid="cl-amount-input" />
            <select className="select" value={form.account} onChange={(e) => setForm({ ...form, account: e.target.value })} data-testid="cl-account-input">
              <option value="CASH">CASH</option>
              <option value="BANK">BANK</option>
              <option value="UPI">UPI</option>
            </select>
            <input className="input" placeholder="Description" value={form.description} onChange={(e) => setForm({ ...form, description: e.target.value })} data-testid="cl-desc-input" />
            <button className="btn btn-cta" disabled={busy || !form.amount} onClick={submit} data-testid="cl-submit"><Plus size={15} /> Save</button>
          </div>
          {error && <div className="warn-note" style={{ marginTop: 10 }} data-testid="cl-error">{error}</div>}
        </div>
      )}

      <h3 className="h3" style={{ margin: "22px 0 8px" }}>All movements</h3>
      {entries.length === 0 ? (
        <div className="card section-card" data-testid="cl-entries-empty">No cash movements yet.</div>
      ) : (
        <div className="table-wrap">
          <table className="data" data-testid="cl-entries-table">
            <thead><tr><th>Voucher</th><th>Type</th><th>Account</th><th>Description</th><th className="num">Amount ₹</th><th /></tr></thead>
            <tbody>
              {entries.map((e) => (
                <tr key={e.id} data-testid={`cl-entry-row-${e.id}`}>
                  <td className="mono">{e.doc_number}</td>
                  <td>
                    <span className={`chip chip-${e.kind === "receipt" ? "green" : e.kind === "payment" ? "amber" : "red"}`}>
                      {e.kind === "receipt" ? <ArrowDownCircle size={12} style={{ verticalAlign: "-2px" }} /> : e.kind === "payment" ? <ArrowUpCircle size={12} style={{ verticalAlign: "-2px" }} /> : null} {e.kind_label}
                    </span>
                  </td>
                  <td className="mono">{e.account}</td>
                  <td>{e.description}{e.vendor_name ? ` · ${e.vendor_name}` : ""}</td>
                  <td className="num mono" style={{ fontWeight: 700, color: Number(e.amount_rupees) < 0 ? "var(--rust)" : "inherit" }}>{e.amount_rupees}</td>
                  <td>{isFinance && e.kind !== "reversal" && (
                    <button className="btn btn-sm" disabled={busy} onClick={() => reverse(e.id)} data-testid={`cl-reverse-${e.id}`}><RotateCcw size={13} /> Reverse</button>
                  )}</td>
                </tr>
              ))}
            </tbody>
          </table>
          <div className="pager" data-testid="cl-pager">
            <span className="pager-info">Showing {(page - 1) * PAGE_SIZE + 1}–{(page - 1) * PAGE_SIZE + entries.length} of {count}</span>
            <div className="spacer" />
            <button className="btn btn-sm" disabled={page <= 1} onClick={() => setPage((p) => p - 1)} data-testid="cl-prev">Prev</button>
            <span className="pager-page">Page {page}</span>
            <button className="btn btn-sm" disabled={!hasNext} onClick={() => setPage((p) => p + 1)} data-testid="cl-next">Next</button>
          </div>
        </div>
      )}
      <Link to="/money/vendor" className="btn" style={{ marginTop: 18 }}>← Vendor Ledger</Link>
    </div>
  );
}
