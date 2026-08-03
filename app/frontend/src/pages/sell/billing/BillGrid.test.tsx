import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import { priceCart } from "../../../till/cart";
import type { Cart } from "../../../till/cart";
import { emptyCart, addPiece } from "../../../till/cart";
import { item, season } from "../../../till/testSupport";
import type { TillGstSlab, TillOffer } from "../../../till/types";
import { Lines } from "./BillGrid";

const SLAB: TillGstSlab = {
  hsn_prefix: "",
  threshold_paise: 250_000,
  rate_below: "5.00",
  rate_above: "18.00",
  effective_from: "2020-01-01",
};

const OFFER: TillOffer = {
  id: 7,
  name: "Threshold offer",
  layer: "brand",
  brand: "MUFTI",
  trigger_type: "none",
  trigger_config: {},
  reward_type: "pct_off",
  reward_config: { percent: "50.00" },
  item_scope: {},
  starts_on: "2026-07-01",
  ends_on: null,
  combinable: false,
  priority: 100,
};

function discountedCart(discountPaise: number): Cart {
  const line = {
    ...addPiece(item("8901", "FW25", 149_900), { stock: 3, alternatives: [] }),
    salesman: 1,
    disc_paise: discountPaise,
  };
  return { ...emptyCart(), lines: [line] };
}

function renderDiscount(discountPaise: number): string {
  const bill = priceCart(
    discountedCart(discountPaise),
    { seasons: [season("FW25", 2)], slabs: [SLAB], offers: [OFFER] },
    "2026-07-30",
    { capPercent: "10.00", allowManualDiscountOnOfferLines: false },
  );
  return renderToStaticMarkup(
    <Lines
      lines={bill.lines}
      salesmen={[]}
      locked={false}
      onEdit={() => undefined}
      onSalesman={() => undefined}
      onPicked={() => undefined}
      onRemove={() => undefined}
      onUndo={() => undefined}
      canUndo={false}
      footer={null}
    />,
  );
}

describe("a manual discount invalidated by an offer", () => {
  it("stays editable so the cashier can remove it", () => {
    const markup = renderDiscount(5_000);

    expect(markup).toContain('data-testid="bill-disc-1"');
    expect(markup).not.toMatch(/data-testid="bill-disc-1"[^>]*disabled=""/);
    expect(markup).toContain("Remove this manual discount");
    expect(markup).toContain("Head Office");
  });

  it("locks an empty discount field while offer stacking is off", () => {
    const markup = renderDiscount(0);

    expect(markup).toMatch(/data-testid="bill-disc-1"[^>]*disabled=""/);
    expect(markup).not.toContain("bill-disc-correction-1");
  });
});
