import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import { draft } from "../../../till/testSupport";
import type { QueuedBill } from "../../../till/types";
import { FinishOverlay } from "./FinishOverlay";

function bill(over: Partial<QueuedBill> = {}): QueuedBill {
  return {
    ...draft(),
    idempotency_uuid: "finished",
    store: "DEO",
    fy: "26-27",
    till_seq: 74,
    doc_number: "26-27/DEO/SAL/74",
    billed_at: "2026-08-03T05:30:00.000Z",
    origin: "offline",
    attempts: 0,
    tenders: [
      { mode: "cash", amount_paise: 49900 },
      { mode: "card", amount_paise: 100000 },
    ],
    ...over,
  };
}

describe("the finish overlay", () => {
  it("shows the saved bill, paid split, change, barcode and both next actions", () => {
    const html = renderToStaticMarkup(
      <FinishOverlay
        bill={bill()}
        cashReceivedPaise={50000}
        printProblem=""
        busy={false}
        onPrint={() => undefined}
        onNext={() => undefined}
      />,
    );

    expect(html).toContain("Bill saved");
    expect(html).toContain("26-27/DEO/SAL/74");
    expect(html).toContain("Paid");
    expect(html).toContain("Cash");
    expect(html).toContain("Card");
    expect(html).toContain("₹1");
    expect(html).toContain('aria-label="Bill 26-27/DEO/SAL/74"');
    expect(html).toContain("Print again");
    expect(html).toContain("Next bill");
    expect(html).toContain("Enter");
  });

  it("names an exchange and keeps a printer failure beside Reprint", () => {
    const html = renderToStaticMarkup(
      <FinishOverlay
        bill={bill({ exchange: { original: { fy: "26-27", till_seq: 40 }, lines: [] } })}
        cashReceivedPaise={49900}
        printProblem="The printer is off. The bill is saved - press Reprint when ready."
        busy={false}
        onPrint={() => undefined}
        onNext={() => undefined}
      />,
    );

    expect(html).toContain("Exchange saved");
    expect(html).toContain("The printer is off");
    expect(html).toContain("Print again");
  });

  it("waits for the initial print attempt before starting the next bill", () => {
    const html = renderToStaticMarkup(
      <FinishOverlay
        bill={bill()}
        cashReceivedPaise={49900}
        printProblem=""
        busy={true}
        onPrint={() => undefined}
        onNext={() => undefined}
      />,
    );

    expect(html.match(/disabled=""/g)).toHaveLength(2);
  });
});
