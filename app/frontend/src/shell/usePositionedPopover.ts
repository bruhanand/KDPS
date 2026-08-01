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
 */
export interface PositionedPopover {
  /** Where to render it, in viewport coordinates. `null` until it has been
   *  placed - render nothing before that, or it flashes at the top-left
   *  corner on the way to its real spot. */
  at: { top: number; left: number } | null;
  /** Goes on the control the popover hangs off. */
  triggerRef: RefObject<HTMLButtonElement>;
  /** Goes on the portaled popover. It holds the node for the outside-click
   *  test, and re-places against the popover's real height the moment it is in
   *  the DOM - before that there is nothing to measure. */
  popoverRef: (node: HTMLDivElement | null) => void;
}

export function usePositionedPopover(
  openKey: string | null,
  onClose: () => void,
  /** Stand-in height for the first placement, before the popover has ever
   *  mounted. Pass the popover's CSS `max-height` where it has one, so the
   *  first clamp is conservative rather than optimistic. */
  fallbackHeight = 0,
): PositionedPopover {
  const [at, setAt] = useState<{ top: number; left: number } | null>(null);
  const triggerRef = useRef<HTMLButtonElement>(null);
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
    const height = popoverRef.current?.offsetHeight ?? fallbackHeight;
    const maxTop = window.innerHeight - height - margin;
    const top = Math.max(margin, Math.min(rect.top, maxTop));
    const left = rect.right + margin;
    setAt((current) =>
      current && current.top === top && current.left === left ? current : { top, left },
    );
  }, [fallbackHeight]);

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
