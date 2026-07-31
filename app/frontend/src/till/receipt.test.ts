import { describe, expect, it } from "vitest";

import { postedReceiptHtml, receiptHtml } from "./receipt";
import type { PostedBill } from "./receipt";
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
      bill({ customer: { name: "<script>alert(1)</script>", mobile: "", gstin: "" } }),
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

describe("a B2B tax invoice (#187)", () => {
  /** The customer handed over a card. Same state as the shop. */
  function b2b(over: Partial<QueuedBill> = {}): QueuedBill {
    return bill({
      customer: { name: "Sharma Traders", mobile: "9876543210", gstin: "10AABCU9603R1Z2" },
      b2b_tax_kind: "cgst_sgst",
      ...over,
    });
  }

  it("prints the buyer's registration, without which it is not a tax invoice", () => {
    const html = receiptHtml(b2b(), STORE);

    expect(html).toContain("10AABCU9603R1Z2");
    expect(html).toContain("Sharma Traders");
  });

  it("splits the tax into CGST and SGST for a buyer in this state", () => {
    const html = receiptHtml(b2b(), STORE);

    // ₹71.38 of tax, halved without losing the odd paise.
    expect(html).toContain("CGST included");
    expect(html).toContain("SGST included");
    expect(html).toContain("₹35.69");
    expect(html).not.toContain("IGST");
  });

  it("shows one IGST line for a buyer across the state line", () => {
    const html = receiptHtml(
      b2b({
        customer: { name: "Ranchi Retail", mobile: "", gstin: "20AABCU9603R1Z1" },
        b2b_tax_kind: "igst",
      }),
      STORE,
    );

    expect(html).toContain("IGST included");
    expect(html).toContain("₹71.38");
    expect(html).not.toContain("CGST");
  });

  it("says the IRN is to follow, because at the counter it always is", () => {
    // Head office raises it inside thirty days, on the government portal. The
    // shop cannot, and the bill prints the moment the customer pays.
    expect(receiptHtml(b2b(), STORE)).toContain("IRN to follow");
  });

  it("prints the split the bill was closed with, not one it re-derives", () => {
    // The counter's copy and the books have to say one thing. If the bill says
    // IGST, IGST is what the customer's copy says, whatever the store's state is.
    const html = receiptHtml(b2b({ b2b_tax_kind: "igst" }), STORE);

    expect(html).toContain("IGST included");
  });

  it("leaves a B2C bill completely alone", () => {
    const html = receiptHtml(bill(), STORE);

    expect(html).toContain("Tax included");
    expect(html).not.toContain("CGST");
    expect(html).not.toContain("IGST");
    expect(html).not.toContain("IRN");
    expect(html).not.toContain("Buyer");
  });
});

/** One sold line of a posted bill, for the reprint fixtures below. */
function postedLine() {
  return {
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
    salesman_code: "ALIE",
    salesman_name: "Ali E.",
    qty: 1,
    mrp_paise: 149900,
    disc_paise: 10000,
    net_paise: 139900,
    gst_rate: "5.00",
    gst_paise: 6662,
  };
}

function postedFixture(): PostedBill {
  return {
    doc_number: "26-27/DEO/SAL/74",
    billed_at: "2026-07-30T12:31:00.000Z",
    origin: "offline",
    store_code: "DEO",
    store_name: "Deoghar",
    store_gstin: "10AAAAA0000A1Z5",
    customer_name: "Mrs Sharma",
    customer_mobile: "9876543210",
    buyer_gstin: "",
    b2b_tax_kind: "none",
    irn: "",
    exchange_of: null,
    lines: [postedLine()],
    tenders: [{ mode: "cash", amount_paise: 139900 }],
    gross_paise: 149900,
    discount_paise: 10000,
    net_paise: 139900,
    gst_paise: 6662,
    round_paise: 0,
  };
}

describe("reprinting a bill found by search (#185)", () => {
  const posted: PostedBill = {
    doc_number: "26-27/DEO/SAL/74",
    billed_at: "2026-07-30T12:31:00.000Z",
    origin: "offline",
    store_code: "DEO",
    store_name: "Deoghar",
    store_gstin: "10AAAAA0000A1Z5",
    customer_name: "Mrs Sharma",
    customer_mobile: "9876543210",
    buyer_gstin: "",
    b2b_tax_kind: "none",
    irn: "",
    exchange_of: null,
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
        salesman_code: "ALIE",
        salesman_name: "Ali E.",
        qty: 1,
        mrp_paise: 149900,
        disc_paise: 10000,
        net_paise: 139900,
        gst_rate: "5.00",
        gst_paise: 6662,
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

  it("reprints the split the bill was raised under (#187)", () => {
    // Off the posted document, never re-derived: the shop's registration can
    // change hands, and what this bill charged is a fact it carries.
    const html = postedReceiptHtml({
      ...posted,
      buyer_gstin: "20AABCU9603R1Z1",
      b2b_tax_kind: "igst",
    });

    expect(html).toContain("20AABCU9603R1Z1");
    expect(html).toContain("IGST included");
  });

  it("prints the IRN once head office has raised one, and says so until then", () => {
    const queued = { ...posted, buyer_gstin: "10AABCU9603R1Z2", b2b_tax_kind: "cgst_sgst" as const };

    expect(postedReceiptHtml(queued)).toContain("IRN to follow");
    expect(postedReceiptHtml({ ...queued, irn: "IRN-2026-0001" })).toContain("IRN IRN-2026-0001");
  });
});

describe("a piece given back on the same bill (#184)", () => {
  /** ₹1,499 out, ₹1,200 back - the customer pays the difference. */
  function exchanged(over: Partial<QueuedBill> = {}): QueuedBill {
    return bill({
      exchange: {
        original: { fy: "26-27", till_seq: 40 },
        lines: [
          {
            line_no: 2,
            barcode: "8901000000022",
            qty: 1,
            refund_paise: 120000,
            gst_rate: "5.00",
            gst_paise: 5714,
            reason: "size",
            condition: "good",
            original_line: 1,
          },
        ],
      },
      totals: { ...draft().totals, net_paise: 29900, gst_paise: 1424 },
      tenders: [{ mode: "cash", amount_paise: 29900 }],
      ...over,
    });
  }

  it("prints what came back, and against which bill", () => {
    const html = receiptHtml(exchanged(), STORE);

    expect(html).toContain("Given back against bill 40");
    expect(html).toContain("8901000000022");
    expect(html).toContain("size");
  });

  it("shows what the customer was credited, not what the tag says", () => {
    // The half of the sum the customer cannot check for themselves: the pieces
    // going out are priced off tags in their hand, and this one is priced off a
    // bill from weeks ago (D2).
    const html = receiptHtml(exchanged(), STORE);

    expect(html).toContain("Given back");
    expect(html).toContain("₹1,200.00");
    expect(html).toContain("₹299.00");
  });

  it("promises a credit note, not cash, when the bill owes the customer", () => {
    const owing = exchanged({
      totals: { ...draft().totals, gross_paise: 0, net_paise: -70100, gst_paise: -3338 },
      tenders: [],
    });

    const html = receiptHtml(owing, STORE);

    expect(html).toContain("Credit note");
    expect(html).toContain("₹701.00");
    expect(html).toContain("No cash is paid out on a return");
    // "Tax included ₹-655.78" is arithmetically right and not a sentence anybody
    // would put on a customer's copy (browser QA of #184). A bill that gives back
    // more than it sells gives the tax back too, and says so.
    expect(html).toContain("Tax given back");
    expect(html).toContain("₹33.38");
    expect(html).not.toContain("-₹");
    // Its number is head office's to allocate, so a counter printing offline
    // cannot know it - and saying so is the truth rather than a blank.
    expect(html).toContain("number follows");
    expect(html).not.toContain("To pay");
  });

  it("leaves an ordinary bill exactly as it was", () => {
    const html = receiptHtml(bill(), STORE);

    expect(html).not.toContain("Given back");
    expect(html).toContain("To pay");
  });
});

describe("reprinting a bill that had a piece given back on it (#184)", () => {
  /** The same bill, with one line sold and one given back against bill 40. */
  const exchanged: PostedBill = {
    ...postedFixture(),
    exchange_of: { doc_number: "26-27/DEO/SAL/40", fy: "26-27", till_seq: 40 },
    lines: [
      postedLine(),
      {
        ...postedLine(),
        line_no: 2,
        direction: "return",
        barcode: "8901000000022",
        net_paise: 120000,
        gst_paise: 5714,
        return_reason: "size",
        condition: "good",
      },
    ],
    net_paise: 19900,
    gst_paise: 948,
    tenders: [{ mode: "cash", amount_paise: 19900 }],
  };

  it("prints the returned piece as one given back, not as one sold", () => {
    // The defect this is here for: rendered as a sale line, a piece the customer
    // *handed back* appears on their copy as one they bought, and the column of
    // amounts no longer comes to the total under it.
    const html = postedReceiptHtml(exchanged);

    expect(html).toContain("Given back against bill 40");
    expect(html).toContain("8901000000022");
    expect(html).toContain("size");
    expect(html).toContain("₹1,200.00");
  });

  it("still prints the sold line as a sale", () => {
    const html = postedReceiptHtml(exchanged);

    expect(html).toContain("MUFTI · Shirt · SHIRT-01 · M · NAVY");
    expect(html).toContain("₹199.00");
  });
});
