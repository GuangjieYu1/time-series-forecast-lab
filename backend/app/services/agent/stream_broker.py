from __future__ import annotations

import threading
from collections import defaultdict

from app.schemas import AgentStreamEvent


class AgentStreamBroker:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._next_cursor: dict[str, int] = defaultdict(int)
        self._events: dict[str, list[AgentStreamEvent]] = defaultdict(list)

    def publish(self, run_id: str, event: AgentStreamEvent) -> AgentStreamEvent:
        with self._lock:
            cursor = self._next_cursor[run_id] + 1
            self._next_cursor[run_id] = cursor
            materialized = event.model_copy(update={"cursor": cursor})
            bucket = self._events[run_id]
            bucket.append(materialized)
            if len(bucket) > 400:
                del bucket[: len(bucket) - 400]
            return materialized

    def list_after(self, run_id: str, cursor: int) -> list[AgentStreamEvent]:
        with self._lock:
            return [event for event in self._events.get(run_id, []) if event.cursor > cursor]


agent_stream_broker = AgentStreamBroker()
