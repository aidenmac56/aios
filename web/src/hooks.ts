import { useCallback, useEffect, useRef, useState } from "react";
import { api } from "./api";

export interface Loaded<T> {
  data: T | null;
  error: unknown;
  loading: boolean;
  reload: () => void;
}

/** GET a path; refetch when the path changes or reload() is called. Keeps old data while reloading. */
export function useApi<T>(path: string | null, opts: { pollMs?: number | null } = {}): Loaded<T> {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [loading, setLoading] = useState<boolean>(!!path);
  const [tick, setTick] = useState(0);
  const lastPath = useRef<string | null>(null);

  useEffect(() => {
    if (!path) return;
    let alive = true;
    if (lastPath.current !== path) {
      setData(null);
      lastPath.current = path;
    }
    setLoading(true);
    api
      .get<T>(path)
      .then((d) => {
        if (!alive) return;
        setData(d);
        setError(null);
      })
      .catch((e) => alive && setError(e))
      .finally(() => alive && setLoading(false));
    return () => {
      alive = false;
    };
  }, [path, tick]);

  const pollMs = opts.pollMs ?? null;
  useEffect(() => {
    if (!path || !pollMs) return;
    const t = window.setInterval(() => setTick((n) => n + 1), pollMs);
    return () => window.clearInterval(t);
  }, [path, pollMs]);

  const reload = useCallback(() => setTick((n) => n + 1), []);
  return { data, error, loading, reload };
}

/** Run an async action with busy + error state. */
export function useAction() {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const run = useCallback(async <R,>(fn: () => Promise<R>): Promise<R | undefined> => {
    setBusy(true);
    setError(null);
    try {
      return await fn();
    } catch (e) {
      setError(e);
      return undefined;
    } finally {
      setBusy(false);
    }
  }, []);
  return { busy, error, run, setError };
}
