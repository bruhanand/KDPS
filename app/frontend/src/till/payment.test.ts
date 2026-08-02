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

describe("what an outcome does to the bill", () => {
  it("stamps nothing on anything short of success", () => {
    for (const state of ["generating", "awaiting", "failed", "unknown"] as const) {
      expect(chargeStamp({ state, reason: "", qr: "" }, BILL)).toBeNull();
    }
  });

  it("stamps nothing on a success with no reference - the server would refuse it", () => {
    // `upi_state=confirmed` with a blank `upi_reference` is a `VALIDATION`
    // refusal (api-contract §2), and a refused bill is a receipt already in a
    // customer's hand.
    expect(chargeStamp({ state: "success", reference: "  ", reason: "", qr: "" }, BILL)).toBeNull();
  });

  it("stamps the reference and the figure it was charged against", () => {
    expect(chargeStamp({ state: "success", reference: "417223918811", reason: "", qr: "" }, BILL))
      .toEqual({ reference: "417223918811", amount_paise: BILL });
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
