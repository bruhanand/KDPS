import { describe, expect, it } from "vitest";

import { receiptHtml } from "./receipt";
import { draft } from "./testSupport";
import type { QueuedBill } from "./types";

const STORE = { code: "DEO", gstin: "10AAAAA0000A1Z5", state_code: "10" };

function bill(over: Partial<QueuedBill> = {}): QueuedBill {
  return {
    ...draft(),
    idempotency_uuid: "c0ffee",
    store: "DEO",
    fy: "26-27",
    till_seq: 74,
    origin: "offline",
    doc_number: "26-27/DEO/SAL/74",
    attempts: 0,
    ...over,
  };
}

describe("the customer's copy", () => {
  it("names the bill, the shop and its GSTIN", () => {
    const html = receiptHtml(bill(), STORE);

    expect(html).toContain("26-27/DEO/SAL/74");
    expect(html).toContain("10AAAAA0000A1Z5");
  });

  it("shows what was paid and what tax is inside it", () => {
    const html = receiptHtml(bill(), STORE);

    expect(html).toContain("₹1,499.00");
    expect(html).toContain("₹71.38");
  });

  it("says the bill was written with no line to head office", () => {
    // The origin tag is evidence for the daily check, and a store person seeing
    // it on the paper knows why the copy at head office may not be there yet.
    expect(receiptHtml(bill({ origin: "offline" }), STORE)).toContain("Billed offline");
    expect(receiptHtml(bill({ origin: "online" }), STORE)).not.toContain("Billed offline");
  });

  it("shows the change when the customer paid round", () => {
    const html = receiptHtml(bill(), STORE, { tenderedPaise: 200000 });

    expect(html).toContain("Change");
    expect(html).toContain("₹501.00");
  });

  it("leaves the change line off when there is none", () => {
    expect(receiptHtml(bill(), STORE, { tenderedPaise: 149900 })).not.toContain("Change");
  });

  it("prints no cost and no margin, ever (H2)", () => {
    // The stylesheet is stripped first: `margin` is a CSS property, and a test
    // that made the receipt avoid it would be a test shaping the layout.
    const printed = receiptHtml(bill(), STORE)
      .replace(/<style>[\s\S]*?<\/style>/, "")
      .toLowerCase();

    for (const word of ["cost", "margin", "profit", "landed", "purchase"]) {
      expect(printed, word).not.toContain(word);
    }
  });

  it("says what a line is in words the screen lends it", () => {
    const html = receiptHtml(bill(), STORE, { describe: () => "MUFTI Shirt · M · Navy" });

    expect(html).toContain("MUFTI Shirt · M · Navy");
  });

  it("escapes whatever a customer typed, so a name cannot become markup", () => {
    const html = receiptHtml(
      bill({ customer: { name: "<script>alert(1)</script>", mobile: "" } }),
      STORE,
    );

    expect(html).not.toContain("<script>");
    expect(html).toContain("&lt;script&gt;");
  });

  it("is a whole document, so an iframe can be handed it as it stands", () => {
    const html = receiptHtml(bill(), STORE);

    expect(html.startsWith("<!doctype html>")).toBe(true);
    expect(html).toContain("</html>");
  });
});
