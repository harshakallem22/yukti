"""In-process event bus for live run streaming.

Events are appended by the background run thread and read by SSE handlers using a
monotonic index, which is also what makes `Last-Event-ID` reconnection work: a
client that drops reconnects with its last index and replays from there.

Deliberately in-memory. A multi-process deployment would need Redis pub/sub, but
that is not the current shape of the system and adding it now would be
infrastructure without a requirement.
"""

from __future__ import annotations

import threading
from collections import defaultdict
from typing import Any


class EventBus:
    def __init__(self) -> None:
        self._events: dict[str, list[dict[str, Any]]] = defaultdict(list)
        self._finished: set[str] = set()
        self._lock = threading.Lock()

    def emit(self, run_id: str, event: dict[str, Any]) -> None:
        with self._lock:
            queue = self._events[run_id]
            queue.append({"seq": len(queue), **event})

    def since(self, run_id: str, index: int) -> list[dict[str, Any]]:
        with self._lock:
            return self._events[run_id][index:]

    def finish(self, run_id: str) -> None:
        with self._lock:
            self._finished.add(run_id)

    def is_finished(self, run_id: str) -> bool:
        with self._lock:
            return run_id in self._finished

    def reset(self, run_id: str) -> None:
        with self._lock:
            self._finished.discard(run_id)


bus = EventBus()
