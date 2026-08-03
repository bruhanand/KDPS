import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import type { FoundBill } from "../../../till/original";
import { AgainstBill, ReturnCustomerSearch } from "./ReturnCounter";

const found: FoundBill = {
  original: { fy: "26-27", till_seq: 74, doc_number: "26-27/DEO/SAL/74" },
  billed_at: "2026-07-30T12:31:00Z",
  customer_name: "Mrs Sharma",
  customer_mobile: "9876543210",
  net_paise: 299800,
  local: false,
  lines: [
    {
      line_no: 1,
      barcode: "8901000000011",
      season: "FW25",
      design: "Oxford",
      color: "Blue",
      size: "M",
      brand: "MUFTI",
      item: "Shirt",
      hsn: "6205",
      qty: 2,
      net_paise: 299800,
      gst_rate: "5.00",
      gst_paise: 14276,
      manual_desc: "",
      direction: "sale",
      returned_qty: 1,
      returned_paise: 149900,
    },
  ],
};

describe("the return counter", () => {
  it("shows the original bill, return ceiling, decisions, and exchange switch", () => {
    const html = renderToStaticMarkup(
      <AgainstBill
        found={found}
        picked={{}}
        outgoing={false}
        late={false}
        windowDays={7}
        locked={false}
        onPick={() => undefined}
        onTakeEverything={() => undefined}
        onOutgoing={() => undefined}
        onChangeBill={() => undefined}
      />,
    );

    expect(html).toContain("26-27/DEO/SAL/74");
    expect(html).toContain("Mrs Sharma");
    expect(html).toContain('class="is-unmarked"');
    expect(html).toContain("of 1");
    expect(html).toContain("Take everything back");
    expect(html).toContain("Good · back on shelf");
    expect(html).toContain("Damaged · quarantine");
    expect(html).toContain("Scan pieces going out");
  });

  it("is honest about the search boundary while offline", () => {
    const html = renderToStaticMarkup(
      <ReturnCustomerSearch
        searchKey="mobile"
        term="9876"
        online={false}
        looking={false}
        error=""
        customers={[]}
        matches={[]}
        onSearchKey={() => undefined}
        onTerm={() => undefined}
        onSearch={() => undefined}
        onPickCustomer={() => undefined}
        onPick={() => undefined}
      />,
    );

    expect(html).toContain("Offline · head-office history needs the line");
    expect(html).toContain("No bill this counter can see matches that customer.");
  });
});
