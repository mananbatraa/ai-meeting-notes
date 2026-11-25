import { useCallback, useEffect, useState } from "react";

import { api } from "../lib/api";
import type { MeetingSummary } from "../lib/types";

export function useMeetings() {
  const [items, setItems] = useState<MeetingSummary[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [version, setVersion] = useState(0);

  useEffect(() => {
    let cancelled = false;
    api.listMeetings(50).then(
      (page) => {
        if (cancelled) return;
        setItems(page.items);
        setError(null);
        setLoading(false);
      },
      (e: unknown) => {
        if (cancelled) return;
        setError(e instanceof Error ? e.message : String(e));
        setLoading(false);
      },
    );
    return () => {
      cancelled = true;
    };
  }, [version]);

  const reload = useCallback(() => setVersion((v) => v + 1), []);

  return { items, error, loading, reload };
}
