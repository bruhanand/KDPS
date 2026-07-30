import { useState } from "react";
import { AlertTriangle, RefreshCw } from "lucide-react";

import { PageHeader } from "../../components/PageHeader";
import { Money, formatDateTime } from "../../lib/format";
import { SyncLight } from "../../till/SyncLight";
import { useTill } from "../../till/TillProvider";
import { slabFor, splitLine } from "../../till/pricing";
import type { BillDraft } from "../../till/types";
import "./Till.css";

// ---------------------------------------------------------------------------
// Till & Sync - what the counter holds, and what it still owes head office (#180)
// ---------------------------------------------------------------------------
//
// The till spine's own surface. The billing screen (#181) sits on top of this
// layer and shows the same sync light in its header; this page is where a store
// person, or whoever they ring, can see the whole of it: what came down, what is
// waiting to go up, which bill number we are on, and - the one thing that ever
// needs a human - a bill the server would not take.
//
// Nothing here is money the person can change. There is no edit affordance on a
// queued bill by construction: it is printed, it is paid for, and the only two
// honest outcomes are that the server takes it or that somebody is told about it.

export default function TillPage() {
  const { engine, till } = useTill();

  if (!engine || !till) return <NoCounter />;

  return (
    <div className="page-pad">
      <PageHeader
        lead="What this counter holds offline, and what it still owes head office."
        actions={
          <div className="till-actions">
            <SyncLight />
            <button
              type="button"
              className="btn"
              data-testid="till-sync-now"
              disabled={till.busy}
              onClick={() => void engine.syncNow()}
            >
              <RefreshCw size={15} className={till.busy ? "till-spin" : ""} />
              {till.busy ? "Syncing…" : "Sync now"}
            </button>
          </div>
        }
      />

      {till.status.colour !== "green" && (
        <p
          className={till.status.colour === "red" ? "till-alert" : "warn-note"}
          data-testid="till-status-reason"
        >
          {till.status.colour === "red" && <AlertTriangle size={15} />}
          {till.status.reason}
        </p>
      )}

      {till.halt && (
        <div className="card till-halt" data-testid="till-halt">
          <h2 className="h3">Bill {till.halt.doc_number} was not accepted</h2>
          <p className="till-halt-why">{till.halt.message}</p>
          <p className="muted-cell">
            Nothing has been lost - the bill is still here, and every bill behind it is
            waiting on this one. Selling continues on the next number. Refused at{" "}
            {formatDateTime(till.halt.at)} · {till.halt.code}
          </p>
          <button
            type="button"
            className="btn"
            data-testid="till-halt-retry"
            onClick={() => void engine.retryHalted()}
          >
            Try this bill again
          </button>
        </div>
      )}

      <div className="till-grid">
        <section className="card till-card">
          <h2 className="h3">This counter</h2>
          <Row label="Store" value={till.storeCode} />
          <Row label="Next bill number" value={till.nextNumber} testId="till-next-number" />
          <Row
            label="Price list last synced"
            value={till.syncedAt ? formatDateTime(till.syncedAt) : "Never"}
          />
          <Row label="Connection" value={till.online ? "Online" : "Offline"} />
        </section>

        <section className="card till-card">
          <h2 className="h3">Head office has</h2>
          {till.register ? (
            <>
              <Row label="Financial year" value={till.register.fy} />
              <Row
                label="Last bill accepted"
                value={String(till.register.last_accepted_seq)}
                testId="till-register-last"
              />
              <Row
                label="Bill series open"
                value={till.register.series_open ? "Yes" : "No - bills will not sync"}
              />
              <Row
                label="Numbers never received"
                value={
                  till.register.hole_count
                    ? `${till.register.hole_count} (${till.register.holes.slice(0, 8).join(", ")}${
                        till.register.hole_count > 8 ? "…" : ""
                      })`
                    : "None"
                }
              />
            </>
          ) : (
            <p className="muted-cell">Not asked yet - sync to find out.</p>
          )}
        </section>

        <section className="card till-card">
          <h2 className="h3">Held locally</h2>
          <Row label="Pieces (barcode × season)" value={String(till.counts.items)} />
          <Row label="Stock rows" value={String(till.counts.stock)} />
          <Row label="Offers" value={String(till.counts.offers)} />
          <Row label="Credit notes" value={String(till.counts.creditNotes)} />
          <Row label="Salesmen" value={String(till.counts.salesmen)} />
          <Row label="Managers who can authorise" value={String(till.counts.managers)} />
          <Row label="Tax slabs" value={String(till.counts.gstSlabs)} />
        </section>
      </div>

      <h2 className="h3 till-queue-heading">
        Waiting to sync <span className="chip">{till.pending}</span>
      </h2>
      {till.queue.length === 0 ? (
        <p className="muted-cell" data-testid="till-queue-empty">
          Nothing waiting. Every bill this counter has printed is with head office.
        </p>
      ) : (
        <div className="table-wrap">
          <table className="data" data-testid="till-queue">
            <thead>
              <tr>
                <th>Bill</th>
                <th>Billed at</th>
                <th>Lines</th>
                <th className="num">Net</th>
                <th className="num">Tries</th>
                <th>Last answer</th>
              </tr>
            </thead>
            <tbody>
              {till.queue.map((bill) => (
                <tr key={bill.idempotency_uuid}>
                  <td>{bill.doc_number}</td>
                  <td>{formatDateTime(bill.billed_at)}</td>
                  <td>{bill.lines.length}</td>
                  <td className="num">
                    <Money paise={bill.totals.net_paise} />
                  </td>
                  <td className="num">{bill.attempts}</td>
                  <td className="muted-cell">{bill.last_error || "not tried yet"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      <TestBill />
    </div>
  );
}

function Row({ label, value, testId }: { label: string; value: string; testId?: string }) {
  return (
    <div className="till-row">
      <span className="till-row-label">{label}</span>
      <span className="till-row-value" data-testid={testId}>
        {value}
      </span>
    </div>
  );
}

function NoCounter() {
  return (
    <div className="page-pad">
      <PageHeader lead="The offline counter, its local copy and its bill queue." />
      <p className="warn-note" data-testid="till-no-counter">
        This login is not a counter. A till signs in as one store: the local price list, the
        credit notes and the manager authorisations all belong to a single shop, so a login
        that can see several has no till to show.
      </p>
    </div>
  );
}

/**
 * Prove the spine without the billing screen.
 *
 * The whole of #180 is demonstrable in one click: number a bill locally, watch it
 * queue, watch it drain into a real Sale on the server. It is a development
 * affordance and it is fenced as one - a button that writes a bill nobody sold
 * has no business on a shop floor, so it is compiled out of a production build
 * rather than merely hidden.
 */
function TestBill() {
  const { engine, till } = useTill();
  const [note, setNote] = useState("");
  const [working, setWorking] = useState(false);
  if (!import.meta.env.DEV || !engine || !till) return null;

  async function queueOne() {
    if (!engine) return;
    setWorking(true);
    try {
      const draft = await fixtureBill(engine);
      const bill = await engine.commit(draft);
      setNote(`Queued ${bill.doc_number}.`);
    } catch (error) {
      setNote(error instanceof Error ? error.message : String(error));
    } finally {
      setWorking(false);
    }
  }

  return (
    <section className="card till-card till-dev">
      <h2 className="h3">Development only</h2>
      <p className="muted-cell">
        Numbers one piece from the local price list at its ticket price, queues it, and lets
        the sync engine take it to the server - the whole spine, without the billing screen.
      </p>
      <button
        type="button"
        className="btn"
        data-testid="till-test-bill"
        disabled={working}
        onClick={() => void queueOne()}
      >
        {working ? "Queueing…" : "Queue a test bill"}
      </button>
      {note && <p className="till-dev-note" data-testid="till-test-bill-note">{note}</p>}
    </section>
  );
}

/** One clean cash sale of whatever the counter has, priced the way the till
 *  prices: ticket price inclusive, tax taken out of it, tender equal to the net. */
async function fixtureBill(engine: NonNullable<ReturnType<typeof useTill>["engine"]>) {
  const item = await engine.db.items.filter((row) => (row.mrp_paise ?? 0) > 0).first();
  if (!item) throw new Error("No priced piece in the local copy yet - sync first.");
  const slabs = await engine.db.gstSlabs.toArray();
  const salesman = await engine.db.salesmen.orderBy("id").first();
  const net = item.mrp_paise as number;
  const billedAt = new Date().toISOString();
  const split = splitLine(net, 1, slabFor(slabs, item.hsn, billedAt.slice(0, 10)));
  const draft: BillDraft = {
    billed_at: billedAt,
    customer: { name: "", mobile: "", gstin: "" },
    lines: [
      {
        line_no: 1,
        direction: "sale",
        barcode: item.barcode,
        season: item.season,
        qty: 1,
        mrp_paise: net,
        disc_paise: 0,
        net_paise: net,
        gst_rate: split.rate,
        gst_paise: split.gst_paise,
        salesman: salesman?.id ?? null,
        offer_evidence: {},
      },
    ],
    tenders: [{ mode: "cash", amount_paise: net }],
    totals: {
      gross_paise: net,
      discount_paise: 0,
      net_paise: net,
      gst_paise: split.gst_paise,
      round_paise: 0,
    },
  };
  return draft;
}
