import { act, create } from "react-test-renderer";
import { describe, expect, it } from "vitest";

import { item } from "./testSupport";
import { useCart } from "./useCart";
import type { CartApi } from "./useCart";

/** Mounts `useCart` for real, through React's own reconciler - not a plain
 *  function call - so a burst of `take()` calls queued inside one `act()`
 *  goes through the exact `setCart` batching a wedge scanner can trigger
 *  (#257): every call in the burst fires before React gets to render once,
 *  the same as several keydown events landing faster than a repaint. `take`
 *  itself never changes identity (`useCart`'s own empty-deps `useCallback`),
 *  so calling whichever one the harness captured before the burst began is
 *  exactly what a stale render's event handler would do too - the case this
 *  is meant to catch. */
function mountCart(): { current: CartApi | null } {
  const ref: { current: CartApi | null } = { current: null };
  function Harness({ onReady }: { onReady: (api: CartApi) => void }) {
    onReady(useCart());
    return null;
  }
  act(() => {
    create(<Harness onReady={(api) => (ref.current = api)} />);
  });
  return ref;
}

describe("a burst of scans with no inter-scan delay (#257)", () => {
  it("lands 20 distinct barcodes queued in one batch as 20 lines", () => {
    const ref = mountCart();
    const pieces = Array.from({ length: 20 }, (_, i) => item(String(8900000 + i)));

    act(() => {
      for (const piece of pieces) ref.current!.take(piece, { stock: 3, alternatives: [] }, 1);
    });

    expect(ref.current!.cart.lines).toHaveLength(20);
    expect(new Set(ref.current!.cart.lines.map((l) => l.barcode)).size).toBe(20);
  });

  it("lands a burst of the same barcode queued in one batch as one line at the full quantity", () => {
    const ref = mountCart();
    const piece = item("8901234");

    act(() => {
      for (let i = 0; i < 20; i += 1) ref.current!.take(piece, { stock: 3, alternatives: [] }, 1);
    });

    expect(ref.current!.cart.lines).toHaveLength(1);
    expect(ref.current!.cart.lines[0].qty).toBe(20);
  });

  it("hands `onApplied` the exact cart each call in the batch produced, in order", () => {
    const ref = mountCart();
    const pieces = Array.from({ length: 5 }, (_, i) => item(String(8900000 + i)));
    const seenLineCounts: number[] = [];

    act(() => {
      for (const piece of pieces) {
        ref.current!.take(piece, { stock: 3, alternatives: [] }, 1, (next) =>
          seenLineCounts.push(next.lines.length),
        );
      }
    });

    expect(seenLineCounts).toEqual([1, 2, 3, 4, 5]);
  });
});
