import { useLayoutEffect } from "react";

import { refreshThemeColour } from "../theme/theme";

/** Enter the document-wide counter room and return its exact cleanup. Exported
 *  as the browser seam behind the hook so StrictMode's setup/cleanup cycle is
 *  testable without coupling a test to React internals. */
export function enterCounterRoom(
  root: HTMLElement,
  refresh: () => void = refreshThemeColour,
): () => void {
  const previousRoom = root.dataset.room;
  root.dataset.room = "counter";
  refresh();

  return () => {
    if (previousRoom === undefined) delete root.dataset.room;
    else root.dataset.room = previousRoom;
    refresh();
  };
}

/** A layout effect prevents a warm frame painting before the dark room enters. */
export function useCounterRoom(): void {
  useLayoutEffect(() => enterCounterRoom(document.documentElement), []);
}
