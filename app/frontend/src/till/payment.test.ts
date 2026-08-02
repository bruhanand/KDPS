// The mock payment adapter, and the one thing it must never do (#248, grill Q5).
//
// Two rules are worth a test that cannot be argued with.
//
// **The mock can never produce a confirmed tender.** Not "does not today" - the
// last test here drives every answer it is capable of giving all the way to the
// wire body and asserts the stamp is `manual` every time. Until real hardware
// lands, a `confirmed` on a bill would be the till vouching for money it never
// saw the bank confirm.
//
// **Unknown is never converted to failed on this counter's clock.** The acquirer
// owns the timeout (grill Q5): a charge nobody can reach may well have taken the
// customer's money, and a till that quietly called it failed would send the
// cashier to collect it a second time.

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import {
  ANSWER_MS,
  brokeDown,
  chargeCardOf,
  chargeStamp,
  createMockPaymentAdapter,
  GENERATING_MS,
  MOCK_ANSWERS,
} from "./payment";
import type { ChargeStanding, PaymentAdapter } from "./payment";
import { emptyPayment, splitOf, toTenders } from "./tender";

const BILL = 250000;

/** Start a charge and collect every state it walks through, without waiting for
 *  it - the caller drives the clock. */
function drive(adapter: PaymentAdapter, amountPaise = BILL) {
  const seen: ChargeStanding[] = [];
  const done = (async () => {
    for await (const standing of adapter.charge(amountPaise)) seen.push(standing);
  })();
  return { seen, done };
}

/** Wind the clock past the acquirer's answer. */
async function settle() {
  await vi.advanceTimersByTimeAsync(GENERATING_MS + ANSWER_MS + 1);
}

beforeEach(() => {
  vi.useFakeTimers();
});

afterEach(() => {
  vi.useRealTimers();
});

describe("the mock walks the five states", () => {
  it("shows generating at once, then the QR to wait against", async () => {
    const adapter = createMockPaymentAdapter();
    const { seen, done } = drive(adapter);

    // Generating is synchronous on purpose: the card must never open blank.
    await vi.advanceTimersByTimeAsync(0);
    expect(seen.map((s) => s.state)).toEqual(["generating"]);

    await vi.advanceTimersByTimeAsync(GENERATING_MS);
    expect(seen.map((s) => s.state)).toEqual(["generating", "awaiting"]);

    await settle();
    await done;
  });

  it("hands over no QR payload of its own - the placeholder is honest about that", async () => {
    const adapter = createMockPaymentAdapter();
    const { seen, done } = drive(adapter);
    await vi.advanceTimersByTimeAsync(GENERATING_MS);

    // A real adapter fills `qr` with the acquirer's payload. A mock that made
    // one up would put a scannable-looking code that pays nobody in front of a
    // customer.
    expect(seen.at(-1)?.qr ?? "").toBe("");

    await settle();
    await done;
  });

  it("ends on an answer with a sentence the counter can act on", async () => {
    const adapter = createMockPaymentAdapter();
    const { seen, done } = drive(adapter);

    await settle();
    await done;

    const last = seen.at(-1)!;
    expect(["failed", "unknown"]).toContain(last.state);
    expect(last.reason.length).toBeGreaterThan(20);
  });

  it("gives both answers in turn, so a cashier can reach either by hand", async () => {
    const adapter = createMockPaymentAdapter();
    const answers: string[] = [];

    for (let i = 0; i < MOCK_ANSWERS.length; i += 1) {
      const { seen, done } = drive(adapter);
      await settle();
      await done;
      answers.push(seen.at(-1)!.state);
    }

    expect(answers).toEqual([...MOCK_ANSWERS]);
  });
});

describe("check status", () => {
  it("answers with where the charge actually stands", async () => {
    const adapter = createMockPaymentAdapter();
    const { done } = drive(adapter);

    await vi.advanceTimersByTimeAsync(GENERATING_MS);
    expect((await adapter.checkStatus())?.state).toBe("awaiting");

    await settle();
    await done;
  });

  it("re-checking an unknown leaves it unknown - the till never decides a timeout", async () => {
    const adapter = createMockPaymentAdapter({ answers: ["unknown"] });
    const { seen, done } = drive(adapter);
    await settle();
    await done;
    expect(seen.at(-1)!.state).toBe("unknown");

    // However long the cashier keeps asking, and however long the clock runs on.
    await vi.advanceTimersByTimeAsync(10 * ANSWER_MS);
    expect((await adapter.checkStatus())?.state).toBe("unknown");
    expect((await adapter.checkStatus())?.state).toBe("unknown");
  });

  it("has nothing to report before a charge, and nothing after one is cancelled", async () => {
    const adapter = createMockPaymentAdapter();
    expect(await adapter.checkStatus()).toBeNull();

    const { done } = drive(adapter);
    await vi.advanceTimersByTimeAsync(GENERATING_MS);
    await adapter.cancel();
    await done;

    expect(await adapter.checkStatus()).toBeNull();
  });
});

describe("cancelling", () => {
  it("stops the charge where it stands - no answer arrives afterwards", async () => {
    const adapter = createMockPaymentAdapter();
    const { seen, done } = drive(adapter);
    await vi.advanceTimersByTimeAsync(GENERATING_MS);

    await adapter.cancel();
    await done;

    expect(seen.map((s) => s.state)).toEqual(["generating", "awaiting"]);

    // And the acquirer's timer, already running when Cancel was pressed, does
    // not land a state on a card the cashier has closed.
    await vi.advanceTimersByTimeAsync(10 * ANSWER_MS);
    expect(seen.map((s) => s.state)).toEqual(["generating", "awaiting"]);
  });

  it("a second charge takes over from the first cleanly", async () => {
    // What React's StrictMode does on every mount, and what "Try again" does on
    // a failed card: the abandoned charge must not write over the live one.
    const adapter = createMockPaymentAdapter();
    const first = drive(adapter);
    const second = drive(adapter);

    await settle();
    await first.done;
    await second.done;

    expect(first.seen.map((s) => s.state)).toEqual(["generating"]);
    expect(second.seen.at(-1)!.state).toBe(MOCK_ANSWERS[0]);
  });
});

describe("what the card is showing", () => {
  const card = (state: ChargeStanding["state"], over: Partial<ChargeStanding> = {}) =>
    chargeCardOf({ state, reason: "the bank said so", qr: "", ...over }, BILL);

  it("waits, and calls the way out Cancel, while a charge is still running", () => {
    for (const state of ["generating", "awaiting"] as const) {
      expect(card(state).tone).toBe("waiting");
      expect(card(state).leaves).toBe("cancel");
      expect(card(state).canRetry).toBe(false);
    }
  });

  it("offers Check status only once there is a charge for the bank to check", () => {
    expect(card("generating").canCheck).toBe(false);
    expect(card("awaiting").canCheck).toBe(true);
  });

  it("dresses an unknown apart from a failure - it is doubt, not a refusal", () => {
    // Grill Q5: a charge nobody can reach may well have taken the customer's
    // money. Painted like a refusal, it invites collecting it a second time.
    expect(card("unknown").tone).toBe("doubt");
    expect(card("failed").tone).toBe("bad");
  });

  it("offers an unknown another check and never another charge", () => {
    // The distinction the whole state exists for: asking again is free, and
    // starting a second charge against a payment that may already have gone
    // through is the double collection.
    expect(card("unknown")).toMatchObject({ canCheck: true, canRetry: false });
    expect(card("failed")).toMatchObject({ canCheck: false, canRetry: true });
  });

  it("says what the adapter said on an answer, in the adapter's own words", () => {
    expect(card("failed").says).toBe("the bank said so");
    expect(card("unknown").says).toBe("the bank said so");
  });

  it("reads the reference back on a success, and offers nothing further", () => {
    const good = card("success", { reference: "417223918811", amount_paise: BILL });

    expect(good.tone).toBe("good");
    expect(good.says).toContain("417223918811");
    expect(good).toMatchObject({ canCheck: false, canRetry: false, leaves: "close" });
  });

  it("never says confirmed about a success the bill will record as manual", () => {
    // The card and the stamp read the same rule, so the words cannot promise
    // what `chargeStamp` is about to refuse - a cashier told "it goes on the
    // bill as confirmed" would never look again at a row going up on their own
    // word.
    for (const over of [
      { reference: "417223918811", amount_paise: undefined },
      { reference: "417223918811", amount_paise: BILL - 100 },
      { reference: "  ", amount_paise: BILL },
    ]) {
      const shown = card("success", over);

      expect(chargeStamp({ state: "success", reason: "", qr: "", ...over }, BILL)).toBeNull();
      expect(shown.tone).toBe("doubt");
      expect(shown.says).not.toContain("confirmed this payment");
      expect(shown.says).toMatch(/on your word/);
    }
  });
});

describe("the terminal itself giving up", () => {
  it("is an unknown, never a failure - the charge may have got away first", () => {
    const standing = brokeDown(new Error("no reader attached"));

    expect(standing.state).toBe("unknown");
    expect(chargeCardOf(standing, BILL)).toMatchObject({
      tone: "doubt",
      canCheck: true,
      canRetry: false,
    });
  });

  it("says what the machine said, and what to do about it", () => {
    expect(brokeDown(new Error("no reader attached")).reason).toContain("no reader attached");
    // Something that is not an Error at all - a rejected string, a DOMException
    // with no message - must still leave a sentence a cashier can act on.
    expect(brokeDown("boom").reason).toMatch(/record it by hand/);
  });

  it("carries no reference, so it cannot become a stamp", () => {
    expect(chargeStamp(brokeDown(new Error("x")), BILL)).toBeNull();
  });
});

describe("what an outcome does to the bill", () => {
  const good: ChargeStanding = {
    state: "success",
    reference: "417223918811",
    amount_paise: BILL,
    reason: "",
    qr: "",
  };

  it("stamps nothing on anything short of success", () => {
    for (const state of ["generating", "awaiting", "failed", "unknown"] as const) {
      expect(chargeStamp({ ...good, state }, BILL)).toBeNull();
    }
  });

  it("stamps nothing on a success with no reference - the server would refuse it", () => {
    // `upi_state=confirmed` with a blank `upi_reference` is a `VALIDATION`
    // refusal (api-contract §2), and a refused bill is a receipt already in a
    // customer's hand.
    expect(chargeStamp({ ...good, reference: "  " }, BILL)).toBeNull();
  });

  it("stamps nothing when the bank does not say what it took", () => {
    // An adapter that cannot account for the figure is not a confirmation of
    // it. Falling back to the cashier's word is the safe direction, and the
    // only one available.
    expect(chargeStamp({ ...good, amount_paise: undefined }, BILL)).toBeNull();
  });

  it("stamps nothing when the bank took a different figure from the one asked for", () => {
    // A partly captured charge, or a QR the customer re-presented. Recording it
    // as `confirmed` for the full amount would be the till telling head office
    // the bank approved money it never saw.
    expect(chargeStamp({ ...good, amount_paise: BILL - 100 }, BILL)).toBeNull();
  });

  it("stamps the reference and the figure it was charged against", () => {
    expect(chargeStamp(good, BILL)).toEqual({ reference: "417223918811", amount_paise: BILL });
  });

  it("no answer the mock can give ever reaches the wire as confirmed", async () => {
    // The acceptance criterion, end to end: every outcome this adapter is
    // capable of, through the stamp and out to the tender row the queue posts.
    const adapter = createMockPaymentAdapter();

    for (let i = 0; i < MOCK_ANSWERS.length; i += 1) {
      const { seen, done } = drive(adapter);
      await settle();
      await done;

      for (const standing of seen) {
        const payment = {
          ...emptyPayment(),
          cash_paise: 0,
          upi_paise: BILL,
          upi_charge: chargeStamp(standing, BILL),
        };
        const upi = toTenders(splitOf(payment, BILL, [], "2026-08-02")).find(
          (row) => row.mode === "upi",
        );
        expect(upi?.upi_state).toBe("manual");
        expect(upi?.upi_reference).toBeUndefined();
      }
    }
  });
});
