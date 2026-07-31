import { useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import { AlertTriangle, KeyRound, Search, Undo2 } from "lucide-react";

import { PageHeader } from "../../components/PageHeader";
import { api, apiErrorMessage } from "../../lib/api";
import { Money, formatDateTime, formatINR } from "../../lib/format";
import { SyncLight } from "../../till/SyncLight";
import { useTill } from "../../till/TillProvider";
import { describeOriginal, legFor, parkExchange, refundFor, returnableQty } from "../../till/exchange";
import type { Exchange, ExchangeLeg, OriginalLine } from "../../till/exchange";
import { billSeqFrom, findQueuedBill, fromServer } from "../../till/original";
import type { FoundBill, SaleDetail } from "../../till/original";
import { LATE_RETURN, PLAIN_RETURN } from "../../till/pin";
import type { Ask, Authorisation } from "../../till/pin";
import { useTillWorld } from "../../till/useTillWorld";
import { newUuid } from "../../till/uuid";
import { ManagerPin, useWrongPins } from "./ManagerPin";
import "./ReturnsExchange.css";

// ---------------------------------------------------------------------------
// Return & Exchange - the two ways a piece comes back (#184, D10 step 5)
// ---------------------------------------------------------------------------
//
// One screen, one starting point - find the bill it was bought on - and then two
// endings that are not variations of each other:
//
// **Exchange.** The customer is taking something else instead, so the pieces
// coming back ride on the *bill being rung up now*: one document, one net amount,
// and the counter takes the difference or hands over a credit note if it goes the
// other way. This screen picks the lines and parks them; Billing prices them
// against whatever is scanned next. It works with the line down, because a bill
// works with the line down.
//
// **Plain return.** Nothing is bought in its place, so there is no bill to hang
// it on: it is a document of its own, it takes a manager's tap every single time,
// and the customer walks out with a credit note rather than cash (grill Q7).
// **It needs the network**, by design and not by accident - a return is rare and
// risky, the SRT number is the server's to allocate, and the credit note has to
// exist somewhere other than on this device before the customer is handed it. So
// the button is disabled offline and says why.
//
// Two things a person reads here that are worth stating.
//
// **What comes back is what was paid** (D2), never today's price. It is shown per
// line before anybody commits to anything, because "you paid ₹1,049 for this, not
// the ₹1,499 on the tag" is the sentence the conversation across the counter is
// actually about.
//
// **A bill the counter has not yet synced can be exchanged against but not
// returned against.** Head office has never seen it, so there is no document to
// give back against - the screen says so rather than offering a button that would
// come back `ORIGINAL_NOT_FOUND` with the customer standing there.

/** What the cashier has picked off one line of the original bill. */
interface Picked {
  qty: number;
  reason: string;
  condition: "good" | "damaged";
}

/** The reasons a piece comes back, as the counter would say them. Free text
 *  would be a column nobody could group by; these are what the daily check and
 *  the brand conversation are both about. */
const REASONS = ["size", "fit", "colour", "defect", "changed mind", "gift"] as const;

export default function ReturnsExchangePage() {
  const { engine, till } = useTill();
  if (!engine || !till) return <NoCounter />;
  return <Counter />;
}

function Counter() {
  const { engine, till } = useTill();
  const navigate = useNavigate();
  const world = useTillWorld(engine?.db ?? null, till?.syncedAt ?? "");

  const [typed, setTyped] = useState("");
  const [looking, setLooking] = useState(false);
  const [found, setFound] = useState<FoundBill | null>(null);
  const [note, setNote] = useState("");
  const [failed, setFailed] = useState("");
  const [picked, setPicked] = useState<Record<number, Picked>>({});
  const [working, setWorking] = useState(false);
  const [asking, setAsking] = useState<Ask[] | null>(null);
  /** Wrong PINs at this counter, and the pause they earn - see `useWrongPins`. */
  const pins = useWrongPins();
  /** The manager's *second* answer, for a bill older than the window. Asked for
   *  separately because it is a separate decision - a tick that came free with
   *  the first one would make the window a thing nobody ever chose to set
   *  aside. */
  const [lateOk, setLateOk] = useState(false);

  const online = till?.online ?? false;
  const legs = useMemo(() => legsFrom(found, picked), [found, picked]);
  const total = legs.reduce((n, leg) => n + leg.refund_paise, 0);

  function reset() {
    setFound(null);
    setPicked({});
    setLateOk(false);
    setFailed("");
  }

  /**
   * Find the bill: the counter's own queue first, head office second.
   *
   * The order is the point - a bill rung up ten minutes ago and not yet synced is
   * the commonest exchange there is, and head office cannot answer about it at
   * all. See `till/original.ts`.
   */
  async function findBill() {
    const seq = billSeqFrom(typed);
    if (!engine || seq === null) {
      setFailed("Type the bill number from the customer's copy.");
      return;
    }
    setLooking(true);
    reset();
    setNote("");
    try {
      const fy = till?.register?.fy || (await engine.db.queue.orderBy("id").last())?.fy || "";
      const local = fy ? await findQueuedBill(engine.db, fy, seq) : null;
      if (local) {
        setFound(local);
        return;
      }
      if (!online) {
        setFailed(
          `Bill ${seq} is not one this counter is still holding, and there is no line to ask ` +
            "head office. It can be looked up when the connection is back.",
        );
        return;
      }
      // **Search first, then read the bill it names.** The detail endpoint is
      // keyed by the whole `26-27/DEO/SAL/74`, and what a person reads off the
      // slip is "74" - so asking for the detail directly would 404 on every
      // online lookup. The search is the endpoint built for exactly this ("a
      // person reads 74 off the slip as often as the whole key", `sell/views.py`)
      // and it renders the number from the series' own prefix and suffix, which
      // the counter must not try to guess.
      // Searched on what was actually **typed**, not on the sequence pulled out
      // of it: the whole key is what narrows two financial years of one counter
      // to the bill in the customer's hand, and it is printed on their copy.
      const { data: matches } = await api.get<{ doc_number: string }[]>("/sell/sales", {
        params: { doc: typed.trim() },
      });
      if (!matches.length) {
        setFailed(`No bill ${typed.trim()} at this store.`);
        return;
      }
      if (matches.length > 1) {
        // Two financial years of the same counter, most likely - both series
        // start at 1 every April. A screen that silently took the first would
        // give back against last year's bill.
        setFailed(
          `More than one bill here matches "${typed.trim()}". Type the whole number from ` +
            "the customer's copy.",
        );
        return;
      }
      const { data } = await api.get<SaleDetail>(
        `/sell/sales/${encodeURIComponent(matches[0].doc_number)}`,
      );
      setFound(fromServer(data));
    } catch (error) {
      setFailed(apiErrorMessage(error));
    } finally {
      setLooking(false);
    }
  }

  function pick(line: OriginalLine, patch: Partial<Picked>) {
    setPicked((current) => {
      const existing = current[line.line_no] ?? { qty: 0, reason: "", condition: "good" as const };
      const next = { ...existing, ...patch };
      if (next.qty <= 0) {
        const { [line.line_no]: _dropped, ...rest } = current;
        return rest;
      }
      return { ...current, [line.line_no]: next };
    });
  }

  /** Hand the picked pieces to the Billing screen and go there. */
  async function exchange() {
    if (!engine || !found || !legs.length || working) return;
    setWorking(true);
    try {
      const parked: Exchange = { original: found.original, lines: legs };
      await parkExchange(engine.db, parked);
      navigate("/sell");
    } catch (error) {
      setFailed(messageOf(error));
      setWorking(false);
    }
  }

  /** Take the pieces back for a credit note - the server-only flow. */
  async function plainReturn(authorisation: Authorisation) {
    if (!found || !legs.length || working) return;
    setWorking(true);
    setFailed("");
    try {
      const { data } = await api.post<{ credit_note: string; value_paise: number }>(
        "/sell/returns",
        {
          idempotency_uuid: newUuid(),
          store: world.store?.code ?? "",
          original: { fy: found.original.fy, till_seq: found.original.till_seq },
          lines: legs.map((leg) => ({
            original_line: leg.original_line,
            qty: leg.qty,
            reason: leg.reason,
            condition: leg.condition,
          })),
          override: { user_id: authorisation.user_id },
          window_override: lateOk,
        },
      );
      setNote(
        `Taken back. Credit note ${data.credit_note} for ${formatINR(data.value_paise)} - ` +
          "write the number on the customer's copy. No cash comes out of the drawer.",
      );
      reset();
      setTyped("");
      // The counter's copy of the open notes and the shelf both moved; the next
      // sync brings them down. Asking for one now means the note is spendable at
      // this till within seconds rather than within five minutes.
      void engine?.syncNow();
    } catch (error) {
      setFailed(apiErrorMessage(error));
    } finally {
      setWorking(false);
    }
  }

  const asks: Ask[] = legs.length
    ? [
        {
          kind: PLAIN_RETURN,
          ref: found?.original.doc_number ?? "",
          paise: total,
          label: found?.original.doc_number ?? "This return",
        },
        ...(lateOk
          ? [
              {
                kind: LATE_RETURN,
                ref: found?.original.doc_number ?? "",
                paise: total,
                label: found?.original.doc_number ?? "This return",
              } as Ask,
            ]
          : []),
      ]
    : [];

  return (
    <div className="page-pad">
      <PageHeader
        lead="Find the bill a piece was bought on, and take it back onto a new bill or for a credit note."
        actions={<SyncLight />}
      />

      <section className="card section-card">
        <div className="rx-find">
          <div className="field">
            <label htmlFor="rx-bill">Bill number from the customer&rsquo;s copy</label>
            <input
              id="rx-bill"
              className="input"
              data-testid="rx-bill"
              autoComplete="off"
              placeholder="74, or 26-27/DEO/SAL/74"
              value={typed}
              onChange={(e) => setTyped(e.target.value)}
              onKeyDown={(e) => {
                if (e.key !== "Enter") return;
                e.preventDefault();
                void findBill();
              }}
            />
          </div>
          <button
            type="button"
            className="btn btn-cta"
            data-testid="rx-find"
            disabled={looking || !typed.trim()}
            onClick={() => void findBill()}
          >
            <Search size={15} />
            {looking ? "Looking…" : "Find the bill"}
          </button>
        </div>
        <p className="muted-cell">
          This counter&rsquo;s own bills are looked at first, so one rung up minutes ago can be
          exchanged against with the line down.
        </p>
      </section>

      {failed && (
        <p className="bill-alert" data-testid="rx-failed">
          <AlertTriangle size={15} />
          {failed}
        </p>
      )}
      {note && (
        <p className="ok-note" data-testid="rx-note">
          {note}
        </p>
      )}

      {found && (
        <>
          <section className="card section-card" data-testid="rx-bill-found">
            <p className="eyebrow">{found.original.doc_number}</p>
            <p className="muted-cell">
              Billed {formatDateTime(found.billed_at)}
              {found.customer_name ? ` · ${found.customer_name}` : ""}
              {found.customer_mobile ? ` · ${found.customer_mobile}` : ""}
            </p>
            {found.local && (
              <p className="warn-note" data-testid="rx-not-synced">
                This bill has not reached head office yet. It can be exchanged against - that is
                a new bill, and the two arrive together - but it cannot be taken back for a
                credit note until it has synced.
              </p>
            )}
            <Lines lines={found.lines} picked={picked} onPick={pick} />
          </section>

          <section className="card section-card rx-actions" data-testid="rx-actions">
            <div className="rx-total">
              <span>Coming back</span>
              <span data-testid="rx-total">
                <Money paise={total} />
              </span>
            </div>
            <p className="muted-cell">
              What the customer actually paid for these pieces, not today&rsquo;s ticket price.
            </p>

            <label className="rx-late">
              <input
                type="checkbox"
                data-testid="rx-late"
                checked={lateOk}
                onChange={(e) => setLateOk(e.target.checked)}
              />
              This bill is past the store&rsquo;s return window and the manager is taking it back
              anyway
            </label>

            <div className="rx-buttons">
              <button
                type="button"
                className="btn btn-cta"
                data-testid="rx-exchange"
                disabled={!legs.length || working}
                onClick={() => void exchange()}
              >
                <Undo2 size={15} />
                Exchange - put these on a new bill
              </button>
              <button
                type="button"
                className="btn"
                data-testid="rx-return"
                disabled={!legs.length || working || !online || found.local}
                title={
                  found.local
                    ? "This bill has not reached head office yet."
                    : !online
                      ? "A return needs the connection - the credit note is head office's to issue."
                      : ""
                }
                onClick={() => setAsking(asks)}
              >
                <KeyRound size={15} />
                Return for a credit note
              </button>
            </div>
            {!online && (
              <p className="warn-note" data-testid="rx-offline">
                The connection is down. An exchange still works - it is an ordinary bill - but a
                return for a credit note needs head office, because the note is a document
                somewhere other than this device.
              </p>
            )}
            <p className="muted-cell">
              Cash never leaves the drawer on a return. The customer takes a credit note,
              spendable at this shop.
            </p>
          </section>
        </>
      )}

      {asking && (
        <ManagerPin
          managers={world.managers}
          asks={asking}
          wrong={pins.wrong}
          onWrong={pins.wasWrong}
          onClose={() => setAsking(null)}
          onAuthorised={(authorisation) => {
            pins.clear();
            setAsking(null);
            void plainReturn(authorisation);
          }}
        />
      )}
    </div>
  );
}

/** The picked lines, as legs on a bill. Recomputed rather than stored: the
 *  refund follows the quantity, and two copies of that arithmetic is one copy too
 *  many (`exchange.refundFor`). */
function legsFrom(found: FoundBill | null, picked: Record<number, Picked>): ExchangeLeg[] {
  if (!found) return [];
  return found.lines
    .filter((line) => (picked[line.line_no]?.qty ?? 0) > 0)
    .map((line) => {
      const choice = picked[line.line_no];
      return {
        ...legFor(line, choice.qty, `x${line.line_no}`),
        reason: choice.reason,
        condition: choice.condition,
      };
    });
}

function Lines({
  lines,
  picked,
  onPick,
}: {
  lines: OriginalLine[];
  picked: Record<number, Picked>;
  onPick: (line: OriginalLine, patch: Partial<Picked>) => void;
}) {
  return (
    <div className="table-wrap">
      <table className="data" data-testid="rx-lines">
        <thead>
          <tr>
            <th>Piece</th>
            <th className="num">Bought</th>
            <th className="num">Still returnable</th>
            <th className="num">Paid</th>
            <th className="num">Give back</th>
            <th>Reason</th>
            <th>Condition</th>
            <th className="num">Back</th>
          </tr>
        </thead>
        <tbody>
          {lines.map((line) => {
            const left = returnableQty(line);
            const choice = picked[line.line_no];
            const qty = choice?.qty ?? 0;
            return (
              <tr key={line.line_no} data-testid={`rx-line-${line.line_no}`}>
                <td>
                  {describeOriginal(line)}
                  <br />
                  <span className="mono muted-cell">{line.barcode}</span>
                </td>
                <td className="num">{line.qty}</td>
                <td className="num" data-testid={`rx-left-${line.line_no}`}>
                  {left === 0 ? <span className="muted-cell">all back</span> : left}
                </td>
                <td className="num">
                  <Money paise={line.net_paise} />
                </td>
                <td className="num">
                  <input
                    className="input bill-cell"
                    inputMode="numeric"
                    data-testid={`rx-qty-${line.line_no}`}
                    aria-label={`How many of line ${line.line_no} are coming back`}
                    disabled={left === 0}
                    value={qty || ""}
                    placeholder="0"
                    onChange={(e) => onPick(line, { qty: wantedQty(e.target.value, left) })}
                  />
                </td>
                <td>
                  <select
                    className="select bill-cell"
                    data-testid={`rx-reason-${line.line_no}`}
                    aria-label={`Why line ${line.line_no} is coming back`}
                    disabled={!qty}
                    value={choice?.reason ?? ""}
                    onChange={(e) => onPick(line, { reason: e.target.value })}
                  >
                    <option value="">Not said</option>
                    {REASONS.map((reason) => (
                      <option key={reason} value={reason}>
                        {reason}
                      </option>
                    ))}
                  </select>
                </td>
                <td>
                  <select
                    className="select bill-cell"
                    data-testid={`rx-condition-${line.line_no}`}
                    aria-label={`What condition line ${line.line_no} is in`}
                    disabled={!qty}
                    value={choice?.condition ?? "good"}
                    onChange={(e) =>
                      onPick(line, { condition: e.target.value === "damaged" ? "damaged" : "good" })
                    }
                  >
                    <option value="good">Good - back on the shelf</option>
                    <option value="damaged">Damaged - into quarantine</option>
                  </select>
                </td>
                <td className="num" data-testid={`rx-refund-${line.line_no}`}>
                  {qty ? (
                    <Money paise={refundFor(line, qty)} />
                  ) : (
                    <span className="muted-cell">nothing yet</span>
                  )}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

/**
 * A quantity as the counter may type it: whole pieces, never more than are left.
 *
 * Capped here rather than refused later, because the server's refusal
 * (`ALREADY_RETURNED`) would arrive with the customer standing at the counter -
 * and on the exchange path it would arrive *after* the receipt had printed, with
 * the whole queue stopped behind it.
 */
export function wantedQty(typed: string, left: number): number {
  const whole = Math.trunc(Number(typed));
  if (!Number.isFinite(whole) || whole <= 0) return 0;
  return Math.min(whole, left);
}

function messageOf(error: unknown): string {
  return error instanceof Error ? error.message : String(error);
}

function NoCounter() {
  return (
    <div className="page-pad">
      <PageHeader lead="Taking a piece back, onto a new bill or for a credit note." />
      <p className="warn-note" data-testid="rx-no-counter">
        This login is not a counter. A return is taken at the shop that sold the piece, and the
        credit note it issues is spendable there - so a login that can see several shops has no
        counter to take one at.
      </p>
    </div>
  );
}
