import { useCallback, useEffect, useRef, useState } from "react";
import type { RefObject } from "react";

/**
 * A popover that hangs off a control inside the sidebar card: portaled out of
 * it, and placed by measuring its trigger.
 *
 * Two of them exist - the rail's section flyout and the profile panel - and
 * both need the same thing for the same reason. The card's `.nav` scrolls
 * (`overflow-y: auto`), which per the CSS spec forces its `overflow-x` to
 * compute as `auto` too, so a popover positioned beside the card as an ordinary
 * descendant is clipped by that, invisibly. Both are therefore `position:
 * fixed`, portaled to `document.body`, and given a place in viewport
 * coordinates.
 *
 * That is one behaviour with four parts that have to stay in step, which is why
 * it is written once rather than twice:
 *
 *  · measure on open, from the trigger;
 *  · re-measure on scroll and resize, because both move the trigger without
 *    React re-rendering anything;
 *  · clamp against the popover's own height, because a `position: fixed` box
 *    below the fold cannot be scrolled into view;
 *  · close on outside click and on Escape - the two ways every popup in this
 *    shell closes.
 *
 * `openKey` is the *identity* of what is open, not a boolean: the rail has one
 * flyout per section sharing one trigger ref, and moving straight from one
 * section to the next has to re-place the popover, which a boolean that stayed
 * `true` would not do.
 *
 * A third caller (Billing's scan-box prompts, #243) needed two more things a
 * button-only, right-of-trigger hook could not give it: the trigger is an
 * `<input>`, and the prompt has to hang *below* the box rather than beside it,
 * because it shares the row with the payment rail and a right-anchored panel
 * would land on top of that. Both are parameters rather than forks - `T` for
 * the element type, `side` for which edge it is measured from - so the
 * sidebar flyout and the profile panel, which pass neither, get back exactly
 * the behaviour they had.
 */
export interface PositionedPopover<T extends HTMLElement = HTMLButtonElement> {
  /** Where to render it, in viewport coordinates. `null` until it has been
   *  placed - render nothing before that, or it flashes at the top-left
   *  corner on the way to its real spot. `maxHeight` is only set on the
   *  `"below"` side, where the popover grows downward by an amount CSS alone
   *  cannot bound: a `100vh`-based rule has no way to know how far down the
   *  page the trigger sits, so a popover starting well below the top of the
   *  viewport would still be let to run past the bottom. Apply it as an
   *  inline style on the popover; `"right"` callers keep clamping `top`
   *  against their own measured height instead, unaffected. */
  at: { top: number; left: number; maxHeight?: number } | null;
  /** Goes on the control the popover hangs off. */
  triggerRef: RefObject<T>;
  /** Goes on the portaled popover. It holds the node for the outside-click
   *  test, and re-places against the popover's real height the moment it is in
   *  the DOM - before that there is nothing to measure. */
  popoverRef: (node: HTMLDivElement | null) => void;
}

export function usePositionedPopover<T extends HTMLElement = HTMLButtonElement>(
  openKey: string | null,
  onClose: () => void,
  /** Stand-in size for the first placement, before the popover has ever
   *  mounted: height on the `"right"` side (clamped against the bottom of the
   *  screen), width on the `"below"` side (clamped against the right edge).
   *  Pass the popover's CSS max on whichever axis that is, so the first clamp
   *  is conservative rather than optimistic. */
  fallbackSize = 0,
  /** Which edge of the trigger the popover is measured from. `"right"` (the
   *  rail flyout, the profile panel) clamps vertically, because the trigger
   *  sits in a column that can run the height of the screen. `"below"` (the
   *  scan box) clamps horizontally instead, because the trigger sits in a row
   *  near the right edge of the page. */
  side: "right" | "below" = "right",
): PositionedPopover<T> {
  const [at, setAt] = useState<{ top: number; left: number; maxHeight?: number } | null>(null);
  const triggerRef = useRef<T>(null);
  const popoverRef = useRef<HTMLDivElement | null>(null);

  // Held in a ref so the listener effect can key on `openKey` alone. Callers
  // pass an inline closure, which is a new function on every render, and an
  // effect keyed on it would tear down and rebind two document listeners on
  // every render of the sidebar.
  const close = useRef(onClose);
  close.current = onClose;

  const place = useCallback(() => {
    const trigger = triggerRef.current;
    if (!trigger) return;
    const margin = 8;
    const rect = trigger.getBoundingClientRect();
    let top: number;
    let left: number;
    let maxHeight: number | undefined;
    if (side === "below") {
      const width = popoverRef.current?.offsetWidth ?? fallbackSize;
      const maxLeft = window.innerWidth - width - margin;
      top = rect.bottom + margin;
      left = Math.max(margin, Math.min(rect.left, maxLeft));
      maxHeight = window.innerHeight - top - margin;
    } else {
      const height = popoverRef.current?.offsetHeight ?? fallbackSize;
      const maxTop = window.innerHeight - height - margin;
      top = Math.max(margin, Math.min(rect.top, maxTop));
      left = rect.right + margin;
    }
    setAt((current) =>
      current &&
      current.top === top &&
      current.left === left &&
      current.maxHeight === maxHeight
        ? current
        : { top, left, maxHeight },
    );
  }, [fallbackSize, side]);

  useEffect(() => {
    if (!openKey) {
      setAt(null);
      return;
    }
    place();
    window.addEventListener("resize", place);
    document.addEventListener("scroll", place, true);
    return () => {
      window.removeEventListener("resize", place);
      document.removeEventListener("scroll", place, true);
    };
  }, [openKey, place]);

  const attachPopover = useCallback(
    (node: HTMLDivElement | null) => {
      popoverRef.current = node;
      if (node) place();
    },
    [place],
  );

  // Checked against both halves of the popover: the trigger stayed where it
  // was rendered, the panel was portaled to `document.body`, and neither one
  // alone is "the popover".
  useEffect(() => {
    if (!openKey) return;
    const off = new AbortController();
    const { signal } = off;
    document.addEventListener(
      "pointerdown",
      (e) => {
        const target = e.target as Node;
        if (triggerRef.current?.contains(target)) return;
        if (popoverRef.current?.contains(target)) return;
        close.current();
      },
      { signal },
    );
    document.addEventListener(
      "keydown",
      (e) => {
        if (e.key === "Escape") close.current();
      },
      { signal },
    );
    return () => off.abort();
  }, [openKey]);

  return { at, triggerRef, popoverRef: attachPopover };
}
