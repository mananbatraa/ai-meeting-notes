import { useCallback, useEffect, useRef, useState } from "react";

import { api, ApiError } from "../lib/api";
import { TERMINAL_STATUSES, type MeetingDetail } from "../lib/types";

export const POLL_INTERVAL_MS = 1500;

interface State {
  meeting: MeetingDetail | null;
  error: string | null;
  notFound: boolean;
}

/** Loads a meeting and keeps polling while it is still processing. */
export function useMeeting(id: string) {
  const [state, setState] = useState<State>({ meeting: null, error: null, notFound: false });
  const [generation, setGeneration] = useState(0);
  const timer = useRef<ReturnType<typeof setTimeout> | undefined>(undefined);

  useEffect(() => {
    // A different meeting id remounts the component (see App), so state never mixes ids.
    let cancelled = false;

    const tick = async () => {
      try {
        const meeting = await api.getMeeting(id);
        if (cancelled) return;
        setState({ meeting, error: null, notFound: false });
        if (!TERMINAL_STATUSES.has(meeting.status)) {
          timer.current = setTimeout(tick, POLL_INTERVAL_MS);
        }
      } catch (e) {
        if (cancelled) return;
        if (e instanceof ApiError && e.status === 404) {
          setState({ meeting: null, error: null, notFound: true });
          return;
        }
        // transient error: keep the last good data and try again
        setState((s) => ({ ...s, error: e instanceof Error ? e.message : String(e) }));
        timer.current = setTimeout(tick, POLL_INTERVAL_MS * 2);
      }
    };
    void tick();

    return () => {
      cancelled = true;
      clearTimeout(timer.current);
    };
  }, [id, generation]);

  /** Restart polling, e.g. after a retry puts the meeting back in the queue. */
  const refresh = useCallback(() => setGeneration((g) => g + 1), []);

  /** Apply a local change (e.g. an edited action item) without refetching. */
  const update = useCallback((fn: (m: MeetingDetail) => MeetingDetail) => {
    setState((s) => (s.meeting ? { ...s, meeting: fn(s.meeting) } : s));
  }, []);

  return { ...state, refresh, update };
}
