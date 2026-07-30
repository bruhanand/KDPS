import { describe, expect, it } from "vitest";

import { postedReceiptHtml, receiptHtml } from "./receipt";
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
    const html = receiptHtml(bill(), STORE, { cashReceivedPaise: 200000 });

    expect(html).toContain("Change");
    expect(html).toContain("₹501.00");
  });

  it("leaves the change line off when there is none", () => {
    expect(receiptHtml(bill(), STORE, { cashReceivedPaise: 149900 })).not.toContain("Change");
  });

  it("says how the bill was paid, mode by mode (#182)", () => {
    // The customer's copy has to name the card and the note: those are the two
    // lines they come back to query, and a bill that only said "₹1,499" would
    // leave the counter re-deriving a split from memory.
    const html = receiptHtml(
      bill({
        tenders: [
          { mode: "cash", amount_paise: 29900 },
          { mode: "card", amount_paise: 100000 },
          { mode: "credit_note", amount_paise: 20000, credit_note: "26-27/DEO/CRN/4" },
        ],
      }),
      STORE,
    );

    expect(html).toContain("Card");
    expect(html).toContain("₹1,000.00");
    expect(html).toContain("Credit note");
    expect(html).toContain("26-27/DEO/CRN/4");
  });

  it("gives change against the cash the bill took, not against the bill", () => {
    // ₹1,000 on the card, ₹499 in cash, and a ₹500 note handed over for it.
    // Change is ₹1, and a receipt that measured against the whole bill would
    // print ₹0 - and the drawer would be a rupee up every time.
    const html = receiptHtml(
      bill({
        tenders: [
          { mode: "card", amount_paise: 100000 },
          { mode: "cash", amount_paise: 49900 },
        ],
      }),
      STORE,
      { cashReceivedPaise: 50000 },
    );

    expect(html).toContain("₹1.00");
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

describe("reprinting a bill found by search (#185)", () => {
  const posted = {
    doc_number: "26-27/DEO/SAL/74",
    billed_at: "2026-07-30T12:31:00.000Z",
    origin: "offline",
    store_code: "DEO",
    store_name: "Deoghar",
    store_gstin: "10AAAAA0000A1Z5",
    customer_name: "Mrs Sharma",
    customer_mobile: "9876543210",
    lines: [
      {
        line_no: 1,
        direction: "sale",
        barcode: "8901000000011",
        season: "FW25",
        brand: "MUFTI",
        item: "Shirt",
        design: "SHIRT-01",
        size: "M",
        color: "NAVY",
        manual_desc: "",
        qty: 1,
        mrp_paise: 149900,
        net_paise: 139900,
      },
    ],
    tenders: [{ mode: "cash", amount_paise: 139900 }],
    gross_paise: 149900,
    discount_paise: 10000,
    net_paise: 139900,
    gst_paise: 6662,
    round_paise: 0,
  };

  it("prints the posted bill on the same paper as the till's own", () => {
    const html = postedReceiptHtml(posted);

    expect(html).toContain("26-27/DEO/SAL/74");
    expect(html).toContain("Deoghar");
    // The registration comes off the document's store, because the screen that
    // reprints has no counter behind it to borrow one from.
    expect(html).toContain("10AAAAA0000A1Z5");
    expect(html).toContain("₹1,399.00");
  });

  it("describes the line from the snapshot the bill was billed with", () => {
    // Rule 3: the brand, item and size were written onto the line at billing, so
    // a reprint a year later reads the garment as it was sold, not as the item
    // master describes it today.
    expect(postedReceiptHtml(posted)).toContain("MUFTI · Shirt · SHIRT-01 · M · NAVY");
  });

  it("still says a bill was written offline", () => {
    expect(postedReceiptHtml(posted)).toContain("Billed offline");
    expect(postedReceiptHtml({ ...posted, origin: "online" })).not.toContain("Billed offline");
  });

  it("shows no change on a bill paid to the paise", () => {
    // The cash the customer held out is not on the document - only what the bill
    // took - so a reprint may not invent a change figure.
    expect(postedReceiptHtml(posted)).not.toContain("Change");
  });
});
