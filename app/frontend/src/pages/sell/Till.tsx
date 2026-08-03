import { useState } from "react";
import { Link } from "react-router-dom";
import {
  AlertTriangle,
  Check,
  HardDriveDownload,
  RefreshCw,
  Replace,
  Volume2,
  VolumeX,
} from "lucide-react";

import { PageHeader } from "../../components/PageHeader";
import { useAuth } from "../../auth/AuthContext";
import { api, apiErrorMessage } from "../../lib/api";
import { Money, formatDateTime } from "../../lib/format";
import { userCan } from "../../shell/navConfig";
import { SyncLight } from "../../till/SyncLight";
import { useTill } from "../../till/TillProvider";
import type { TillEngine, TillSnapshot } from "../../till/engine";
import { slabFor, splitLine } from "../../till/pricing";
import { playTone } from "../../till/sounds";
import type { BillDraft, HandoverState } from "../../till/types";
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
//
// It is also where a counter is put back together (#189), which is why the two
// recovery cards sit at the top rather than with the counts. Both of them move
// the number the next customer's bill will carry, so both are buttons somebody
// presses and neither happens on its own:
//
//   · **Recover this counter** - the browser threw the local database away, the
//     till is refusing to bill, and this takes the whole dataset again and asks
//     head office how far the store's series has got.
//   · **Move the counter to this machine** - the deliberate handover. A manager's
//     act, with a reason, and it hands back the bills the old machine never sent
//     so the store can key them in from the printed copies.

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

      {/* The page has already narrowed both to non-null, so the recovery cards
          take them as props rather than reaching for the context again - one
          way in, and no optional chaining over a value that cannot be null. */}
      {till.storageLost && <RecoverCounter engine={engine} busy={till.busy} />}

      <Handover engine={engine} till={till} />

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
          <Row label="Salesmen" value={String(till.counts.salesmen)} />
          <Row label="Managers who can authorise" value={String(till.counts.managers)} />
          <Row label="Tax slabs" value={String(till.counts.gstSlabs)} />
          <Row label="Customers known" value={String(till.counts.customers)} />
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

      <ScanSounds engine={engine} muted={till.muted} />
      <CounterPin />
      <TestBill />
    </div>
  );
}

/**
 * Putting a counter back together after the browser cleared its data (#189).
 *
 * Shown only when the till has actually noticed a loss, and it is the only way
 * out of that state: until this succeeds the Billing screen will not take a
 * bill, because a counter that does not know its own number would print one that
 * is already on a posted bill.
 *
 * The card says what the counter will be on afterwards rather than merely "done",
 * which is the whole of the acceptance criterion's "no silent counter reset" -
 * the number a store's bills carry has moved, and somebody should read it.
 */
function RecoverCounter({ engine, busy }: { engine: TillEngine; busy: boolean }) {
  const [failed, setFailed] = useState("");

  async function recover() {
    setFailed("");
    try {
      await engine.recover();
    } catch (error) {
      setFailed(messageOf(error));
    }
  }

  return (
    <section className="card till-recover" data-testid="till-recover">
      <h2 className="h3">
        <AlertTriangle size={16} /> This counter lost its local data
      </h2>
      <p className="till-halt-why">
        The browser cleared what this till had stored - the price list, and the bill number it
        was on. Nothing that had already synced is lost, but this device does not know where the
        store&rsquo;s bill numbers have got to, so it will not take a bill until it has asked.
      </p>
      <p className="muted-cell">
        Recovering takes the whole price list again and asks head office how far this
        store&rsquo;s bills have got. The next bill number will move; the screen will say what
        it moved to.
      </p>
      {failed && (
        <p className="till-alert" data-testid="till-recover-failed">
          <AlertTriangle size={15} />
          {failed}
        </p>
      )}
      <button
        type="button"
        className="btn btn-cta"
        data-testid="till-recover-go"
        disabled={busy}
        onClick={() => void recover()}
      >
        <HardDriveDownload size={15} />
        {busy ? "Recovering…" : "Recover this counter"}
      </button>
    </section>
  );
}

/**
 * The register handover, and the paper re-entry it leaves behind (#189, grill Q1).
 *
 * Two things in one card because they are one job with a gap in the middle: a
 * manager moves the store's counter onto this machine, and then somebody works
 * through the receipts the old machine printed and never sent.
 *
 * The list survives a reload and the ticks survive the queue draining, because
 * the work does: a drawer of forty receipts is an afternoon, and a list that
 * reset when a bill synced would have somebody keying the same one twice.
 *
 * The move itself is offered only to a manager - the same rung the server gates
 * it at - and the list is shown to whoever is standing here, because keying a
 * receipt back in is ordinary counter work.
 */
function Handover({ engine, till }: { engine: TillEngine; till: TillSnapshot }) {
  const { user } = useAuth();
  const [reason, setReason] = useState("");
  const [failed, setFailed] = useState("");
  const [said, setSaid] = useState("");
  const [asking, setAsking] = useState(false);
  const busy = till.busy;
  const mayHandOver = userCan(user, "sell", "approve");
  const handover = till.handover;

  if (!mayHandOver && !handover) return null;

  async function move() {
    setFailed("");
    setSaid("");
    try {
      await engine.handOver(reason.trim());
      setReason("");
      setAsking(false);
      // The counter's own number, not the one the server suggested. They are the
      // same in every ordinary case - and where they are not, it is because the
      // two clocks disagree about the financial year and the till has declined
      // to move (see `reconcileRegister`). Reporting the server's figure there
      // would tell somebody the counter had gone somewhere it had not.
      setSaid(
        "This machine is now the counter for this store. The next bill is " +
          `${engine.getSnapshot().nextNumber}.`,
      );
    } catch (error) {
      setFailed(messageOf(error));
    }
  }

  return (
    <section className="card till-handover" data-testid="till-handover">
      <h2 className="h3">Register handover</h2>

      {mayHandOver && !asking && (
        <>
          <p className="muted-cell">
            Use this when the counter machine has been replaced or will not come back. This
            device takes over the store&rsquo;s bill numbers, and whatever the old machine
            printed but never sent is listed here to be keyed back in from the printed copies.
          </p>
          <button
            type="button"
            className="btn"
            data-testid="till-handover-open"
            onClick={() => {
              setAsking(true);
              setSaid("");
            }}
          >
            <Replace size={15} />
            Move the counter to this machine
          </button>
        </>
      )}

      {mayHandOver && asking && (
        <>
          <p className="muted-cell">
            Say what happened. It is recorded against your name, and it is what explains the
            gap in this store&rsquo;s bill numbers to whoever asks later.
          </p>
          <div className="field">
            <label htmlFor="till-handover-reason">Why is the counter moving?</label>
            <input
              id="till-handover-reason"
              className="input"
              data-testid="till-handover-reason"
              autoComplete="off"
              disabled={busy}
              value={reason}
              onChange={(e) => setReason(e.target.value)}
            />
          </div>
          <div className="till-handover-actions">
            <button
              type="button"
              className="btn btn-cta"
              data-testid="till-handover-go"
              disabled={busy || !reason.trim()}
              onClick={() => void move()}
            >
              {busy ? "Moving…" : "Move the counter here"}
            </button>
            <button
              type="button"
              className="btn"
              disabled={busy}
              onClick={() => {
                setAsking(false);
                setFailed("");
              }}
            >
              Cancel
            </button>
          </div>
        </>
      )}

      {failed && (
        <p className="till-alert" data-testid="till-handover-failed">
          <AlertTriangle size={15} />
          {failed}
        </p>
      )}
      {said && (
        <p className="ok-note" data-testid="till-handover-said">
          {said}
        </p>
      )}

      {handover && <PaperReentry engine={engine} till={till} handover={handover} />}
    </section>
  );
}

/**
 * The drawer of printed bills the old machine never sent.
 *
 * Each one is a link into Billing rather than a form here: re-entering a bill is
 * billing - the same lines, the same salesman, the same tender - and a second,
 * simpler screen for it would be a second place where a bill can be got wrong.
 *
 * A number the response did not name is not a number nobody has to key in, so the
 * count is shown beside the list whenever the two differ (a machine dead at bill
 * 5,000 leaves more holes than a response should carry).
 *
 * The ticks come from what the till has actually keyed in, not from what is left
 * in the queue: a re-entered bill leaves the queue the moment head office takes
 * it, and a list that lost its ticks as the store worked would have somebody key
 * the same receipt in twice.
 */
function PaperReentry({
  engine,
  till,
  handover,
}: {
  engine: TillEngine;
  till: TillSnapshot;
  handover: HandoverState;
}) {
  const done = new Set(till.paperEntered);
  // The frozen list the handover named **and** whatever head office is still
  // missing now. Both, because neither alone is the job: the handover's list is
  // capped at 200, so a machine that died at bill 5,000 would strand the rest
  // out of reach - and the register's list is the live one, which drops a number
  // the moment a re-entry syncs, taking its tick with it.
  const outstanding = [...new Set([...handover.unsynced_hint, ...(till.register?.holes ?? [])])]
    .sort((a, b) => a - b)
    .filter((seq) => !done.has(seq));
  const ticked = handover.unsynced_hint.filter((seq) => done.has(seq));
  const listed = [...outstanding, ...ticked].sort((a, b) => a - b);
  const stillHidden = Math.max(0, (till.register?.hole_count ?? 0) - outstanding.length);

  return (
    <div className="till-reentry" data-testid="till-reentry">
      <h3 className="h3">Bills to key in from the printed copies</h3>
      <p className="muted-cell">
        Handed over {formatDateTime(handover.at)}. These numbers were printed on the old
        machine and never reached head office. Find each printed copy and enter it again under
        the same number - the customer keeps the one they have.
        {stillHidden > 0 && (
          <>
            {" "}
            {stillHidden} more are missing than can be listed at once; they appear here as these
            are entered and sync.
          </>
        )}
      </p>

      {listed.length === 0 ? (
        <p className="muted-cell" data-testid="till-reentry-none">
          Nothing left to enter - head office has every bill this list named.
        </p>
      ) : (
        <ul className="till-reentry-list">
          {listed.map((seq) => (
            <li key={seq} className={done.has(seq) ? "till-reentry-done" : ""}>
              <span className="till-reentry-no">Bill {seq}</span>
              {done.has(seq) ? (
                <span className="ok-note" data-testid={`till-reentry-done-${seq}`}>
                  <Check size={14} /> keyed in
                </span>
              ) : (
                <Link className="btn" data-testid={`till-reentry-${seq}`} to={`/sell?paper=${seq}`}>
                  Enter this bill
                </Link>
              )}
            </li>
          ))}
        </ul>
      )}

      <button
        type="button"
        className="btn"
        data-testid="till-reentry-clear"
        disabled={outstanding.length > 0}
        title={
          outstanding.length > 0
            ? "There are still bills on this list to key in."
            : "Put the list away - every bill on it has been entered."
        }
        onClick={() => void engine.clearHandover()}
      >
        {outstanding.length > 0 ? `${outstanding.length} still to enter` : "Put this list away"}
      </button>
    </div>
  );
}

function messageOf(error: unknown): string {
  return error instanceof Error ? error.message : String(error);
}

/**
 * A manager's own counter PIN (#182).
 *
 * It lives here rather than on the Billing screen because it is not part of
 * selling: it is the credential that lets this person stand behind a cashier's
 * exception, and it is set once and then left alone. Only somebody the counter
 * could actually be asked to trust sees the card at all - the server decides
 * that (`may_hold_till_pin`), and refuses the write besides.
 *
 * They type it themselves, and prove who they are with their own password. An
 * administrator who could set a manager's PIN could accept an exception in that
 * manager's name, which would leave the evidence on a bill worth nothing.
 */
function CounterPin() {
  const { user } = useAuth();
  const [pin, setPin] = useState("");
  const [password, setPassword] = useState("");
  const [saving, setSaving] = useState(false);
  const [said, setSaid] = useState("");
  const [failed, setFailed] = useState("");
  // Held here rather than re-read from `/me`: the only thing it changes is a
  // sentence, and the person who just set a PIN knows they have one.
  const [hasPin, setHasPin] = useState(Boolean(user?.has_till_pin));

  if (!user?.may_hold_till_pin) return null;

  async function save() {
    if (saving) return;
    setSaving(true);
    setSaid("");
    setFailed("");
    try {
      await api.put("/auth/me/till-pin", { pin, current_password: password });
      setPin("");
      setPassword("");
      setHasPin(true);
      setSaid("Your counter PIN is set. The till picks it up on its next sync.");
    } catch (error) {
      setFailed(apiErrorMessage(error));
    } finally {
      setSaving(false);
    }
  }

  return (
    <section className="card till-card till-pin-card">
      <h2 className="h3">Your counter PIN</h2>
      <p className="muted-cell">
        {hasPin
          ? "You have one. Setting a new one replaces it everywhere on the next sync."
          : "Set one and a cashier here can call you over to approve an exchange past the return window - with the line down."}
      </p>

      <div className="field">
        <label htmlFor="till-pin-new">New PIN (4 to 6 digits)</label>
        <input
          id="till-pin-new"
          className="input"
          data-testid="till-pin-new"
          type="password"
          inputMode="numeric"
          autoComplete="off"
          disabled={saving}
          value={pin}
          onChange={(e) => setPin(e.target.value)}
        />
      </div>
      <div className="field">
        <label htmlFor="till-pin-password">Your password</label>
        <input
          id="till-pin-password"
          className="input"
          data-testid="till-pin-password"
          type="password"
          autoComplete="current-password"
          disabled={saving}
          value={password}
          onChange={(e) => setPassword(e.target.value)}
        />
      </div>

      {failed && (
        <p className="till-alert" data-testid="till-pin-failed">
          <AlertTriangle size={15} />
          {failed}
        </p>
      )}
      {said && (
        <p className="ok-note" data-testid="till-pin-said">
          {said}
        </p>
      )}

      <button
        type="button"
        className="btn"
        data-testid="till-pin-save"
        disabled={saving || !pin || !password}
        onClick={() => void save()}
      >
        {saving ? "Setting…" : "Set my PIN"}
      </button>
    </section>
  );
}

/**
 * The counter's noise, on or off (#247, grill Q8).
 *
 * Here rather than on the Billing screen, and per counter rather than per
 * person, because that is what it is about: one till stands next to the music
 * and another sits in a back office, and neither is head office's decision or a
 * cashier's login's. It is one switch and it takes effect on the next scan.
 *
 * Pressing it plays the tone it is turning on, which is the only honest way to
 * answer "is the sound working?" - a shop with the machine's volume down would
 * otherwise turn the setting on and off all afternoon.
 */
function ScanSounds({ engine, muted }: { engine: TillEngine; muted: boolean }) {
  return (
    <section className="card till-card till-sound-card">
      <h2 className="h3">Scan sounds</h2>
      <p className="muted-cell">
        A short tick when a scan puts a piece on the bill, and a different, lower buzz when it
        does not - an unknown tag, or a piece still waiting to be told which season it is. Set
        on this counter, and it stays set.
      </p>
      <div className="till-sound-row">
        <button
          type="button"
          className="btn"
          data-testid="till-sound-toggle"
          aria-pressed={!muted}
          onClick={() => {
            void engine.setMuted(!muted);
            // Turning it back on plays the tick, so the answer to "did that
            // work?" is the sound itself rather than a sentence about it.
            if (muted) playTone("tick", false);
          }}
        >
          {muted ? <VolumeX size={15} /> : <Volume2 size={15} />}
          {muted ? "Turn the sounds on" : "Turn the sounds off"}
        </button>
        <span className="muted-cell" data-testid="till-sound-state">
          {muted ? "Silent." : "This counter ticks and buzzes."}
        </span>
      </div>
    </section>
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
        This login is not a counter. A till signs in as one store: the local price list and
        manager authorisations belong to a single shop, so a login that can see several has no
        till to show.
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
