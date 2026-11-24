import { useCallback, useEffect, useState } from "react";

/**
 * Fetch helper. `fn` returns an axios promise (or null to skip, e.g. no patient selected).
 * Re-runs when `deps` change. Ignores responses from stale requests.
 */
export default function useApi(fn, deps) {
  const [state, setState] = useState({ data: null, loading: !!fn, error: "" });
  const [tick, setTick] = useState(0);
  const reload = useCallback(() => setTick((t) => t + 1), []);

  useEffect(() => {
    const p = fn();
    if (!p) { setState({ data: null, loading: false, error: "" }); return; }
    let live = true;
    setState((s) => ({ ...s, loading: true }));
    p.then((r) => live && setState({ data: r.data, loading: false, error: "" }))
      .catch((e) => live && setState({ data: null, loading: false, error: e.response?.data?.detail || "Request failed" }));
    return () => { live = false; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [...deps, tick]);

  return { ...state, reload };
}
