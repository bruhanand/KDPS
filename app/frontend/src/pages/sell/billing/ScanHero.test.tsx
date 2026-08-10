import { act, create } from "react-test-renderer";
import type { ReactTestInstance } from "react-test-renderer";
import { describe, expect, it, vi } from "vitest";

import { ScanHero, scanHeroState } from "./ScanHero";

describe("scan hero state", () => {
  it("names a normal sale scanner as listening", () => {
    expect(scanHeroState("sale", false)).toBe("LISTENING");
  });

  it("names a return scanner as awaiting the original bill", () => {
    expect(scanHeroState("return", false)).toBe("AWAITING BILL");
  });

  it("makes a failed scan visible until the cashier dismisses it", () => {
    expect(scanHeroState("sale", true)).toBe("NOT FOUND");
  });
});

describe("Enter submits the live scan, not a stale one (#257)", () => {
  function mountScanBox(value: string, onSubmit: (code: string) => void): ReactTestInstance {
    // `.root` is only valid once `act()` has returned - the tree counts as
    // "unmounted" to react-test-renderer's own bookkeeping while still
    // inside the act scope that created it.
    let renderer!: ReturnType<typeof create>;
    act(() => {
      renderer = create(
        <ScanHero
          mode="sale"
          boxRef={() => {}}
          value={value}
          disabled={false}
          placeholder=""
          hasError={false}
          errorBarcode=""
          demoCodes={[]}
          onChange={() => {}}
          onSubmit={onSubmit}
          onLookup={() => {}}
          onDismissError={() => {}}
          onBillOffTag={() => {}}
          onDemoScan={() => {}}
        />,
      );
    });
    return renderer.root.findByProps({ "data-testid": "bill-scan" });
  }

  it("submits the DOM input's own value at Enter, even when the `value` prop is stale", () => {
    // A wedge firing scans faster than React repaints can have this handler
    // still bound to a render from before the last keystroke committed - the
    // `value` prop here ("890") stands in for that stale render, and the
    // native input's own value at the moment of Enter ("8901234") for what
    // the DOM actually holds by then. Submitting the prop would send a
    // truncated code that genuinely fails to resolve, on a tag that is
    // really on the shelf.
    const onSubmit = vi.fn();
    const input = mountScanBox("890", onSubmit);

    act(() => {
      input.props.onKeyDown({
        key: "Enter",
        preventDefault: () => {},
        currentTarget: { value: "8901234" },
      });
    });

    expect(onSubmit).toHaveBeenCalledWith("8901234");
  });

  it("does nothing on any key but Enter", () => {
    const onSubmit = vi.fn();
    const input = mountScanBox("8901234", onSubmit);

    act(() => {
      input.props.onKeyDown({
        key: "Tab",
        preventDefault: () => {},
        currentTarget: { value: "8901234" },
      });
    });

    expect(onSubmit).not.toHaveBeenCalled();
  });
});
