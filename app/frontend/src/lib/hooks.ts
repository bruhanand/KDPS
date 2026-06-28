import { useCallback, useEffect, useState } from "react";

import { api } from "./api";

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
