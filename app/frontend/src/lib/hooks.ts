import { useCallback, useEffect, useState } from "react";

import { api } from "./api";

/** Shape of a DRF PageNumberPagination response (see finledger's LedgerPagination). */
export interface Paginated<T> {
  results: T[];
  count: number;
  next: string | null;
}

/**
 * Server-side pagination against DRF's PageNumberPagination. Owns page/count/hasNext
 * and the "showing X–Y of Z" arithmetic so paginated ledger screens don't each
 * re-implement it. `searchParams` builds the `page`/`page_size` query; `applyPage`
 * consumes the response and returns its rows.
 */
export function usePagination(pageSize = 50) {
  const [page, setPage] = useState(1);
  const [count, setCount] = useState(0);
  const [hasNext, setHasNext] = useState(false);

  const applyPage = useCallback(<T>(data: Paginated<T>): T[] => {
    setCount(data.count);
    setHasNext(Boolean(data.next));
    return data.results;
  }, []);

  const searchParams = useCallback(
    (extra?: Record<string, string>) => {
      const q = new URLSearchParams(extra);
      q.set("page", String(page));
      q.set("page_size", String(pageSize));
      return q;
    },
    [page, pageSize],
  );

  const reset = useCallback(() => setPage(1), []);
  const next = useCallback(() => setPage((p) => p + 1), []);
  const prev = useCallback(() => setPage((p) => p - 1), []);

  return { page, pageSize, count, hasNext, setPage, applyPage, searchParams, reset, next, prev };
}

export function useList<T = any>(url: string | null) {
  const [data, setData] = useState<T[]>([]);
  const [loading, setLoading] = useState(true);
  const reload = useCallback(() => {
    if (!url) return;
    setLoading(true);
    api
      .get(url)
      .then((r) => setData(r.data))
      .finally(() => setLoading(false));
  }, [url]);
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
