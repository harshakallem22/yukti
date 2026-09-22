import { useEffect, useRef, useState } from "react";
import type { RunEvent } from "./types";

/**
 * Subscribes to a run's SSE stream.
 *
 * EventSource reconnects on its own and replays from `Last-Event-ID`, which is
 * why SSE was chosen over polling — a dropped connection does not lose steps.
 * The stream is closed on the server's `close` event so a finished run does not
 * hold an open connection.
 */
export function useRunEvents(runId: string, enabled: boolean) {
  const [events, setEvents] = useState<RunEvent[]>([]);
  const [connected, setConnected] = useState(false);
  const sourceRef = useRef<EventSource | null>(null);

  useEffect(() => {
    if (!enabled) {
      sourceRef.current?.close();
      sourceRef.current = null;
      setConnected(false);
      return;
    }

    const source = new EventSource(`/api/runs/${runId}/events`);
    sourceRef.current = source;

    const handle = (event: MessageEvent) => {
      try {
        setEvents((current) => [...current, JSON.parse(event.data) as RunEvent]);
      } catch {
        // A malformed frame should not tear down the stream.
      }
    };

    source.onopen = () => setConnected(true);
    for (const name of ["step", "status", "error", "done", "message"]) {
      source.addEventListener(name, handle as EventListener);
    }
    source.addEventListener("close", () => {
      source.close();
      setConnected(false);
    });
    source.onerror = () => setConnected(false);

    return () => {
      source.close();
      sourceRef.current = null;
    };
  }, [runId, enabled]);

  return { events, connected };
}
