import { useCallback, useEffect, useState } from "react";

import { api } from "./api";
import { withQuery, type QueryParams } from "./query";

/**
 * A list endpoint, refetched whenever its filters change.
 *
 * `params` is how a screen carries a search term (#102) or a tab without
 * building URLs itself — and it is compared by the URL it produces, not by
 * object identity, so an inline `{ q }` on every render costs one fetch, not a
 * loop. A blank value is dropped, so an empty search box asks the exact
 * question the screen asked before it had one.
 */
export function useList<T = any>(url: string | null, params?: QueryParams) {
  const [data, setData] = useState<T[]>([]);
  const [loading, setLoading] = useState(true);
  const full = url === null ? null : withQuery(url, params);
  const reload = useCallback(() => {
    if (!full) return;
    setLoading(true);
    api
      .get(full)
      .then((r) => setData(r.data))
      .finally(() => setLoading(false));
  }, [full]);
  useEffect(() => {
    reload();
  }, [reload]);
  return { data, loading, reload };
}

export function useDoc<T = any>(url: string | null) {
  const [data, setData] = useState<T | null>(null);
  const [loading, setLoading] = useState(true);
  useEffect(() => {
    let live = true;
    if (!url) return;
    setLoading(true);
    api
      .get(url)
      .then((r) => live && setData(r.data))
      .finally(() => live && setLoading(false));
    return () => {
      live = false;
    };
  }, [url]);
  return { data, loading };
}
