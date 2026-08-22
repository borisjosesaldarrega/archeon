"""A bounded, thread-safe event bus with no worker thread of its own."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from queue import Empty, Full, Queue
from threading import Lock
from types import MappingProxyType
from typing import Any, Mapping


_CLOSED = object()


@dataclass(frozen=True, slots=True)
class Event:
    sequence: int
    type: str
    source: str
    payload: Mapping[str, Any] = field(default_factory=dict)
    timestamp: str = field(default_factory=lambda: datetime.now(UTC).isoformat())
    correlation_id: str | None = None
    sensitive: bool = False

    def to_dict(self, *, include_sensitive: bool = False) -> dict[str, Any]:
        payload: dict[str, Any] | str = dict(self.payload)
        if self.sensitive and not include_sensitive:
            payload = "<redacted>"
        return {
            "sequence": self.sequence,
            "type": self.type,
            "source": self.source,
            "payload": payload,
            "timestamp": self.timestamp,
            "correlation_id": self.correlation_id,
        }


class Subscription:
    """A closeable bounded event subscription."""

    def __init__(
        self,
        bus: EventBus,
        subscription_id: int,
        patterns: tuple[str, ...],
        max_queue: int,
    ) -> None:
        self._bus = bus
        self.id = subscription_id
        self.patterns = patterns
        self._queue: Queue[Event | object] = Queue(maxsize=max_queue)
        self._closed = False
        self.dropped_events = 0

    @property
    def closed(self) -> bool:
        return self._closed

    def matches(self, event_type: str) -> bool:
        return any(
            pattern == "*"
            or pattern == event_type
            or (pattern.endswith(".*") and event_type.startswith(pattern[:-1]))
            for pattern in self.patterns
        )

    def _offer(self, event: Event) -> None:
        if self._closed:
            return
        try:
            self._queue.put_nowait(event)
        except Full:
            try:
                self._queue.get_nowait()
            except Empty:
                pass
            self.dropped_events += 1
            self._queue.put_nowait(event)

    def get(self, timeout: float | None = None) -> Event:
        item = self._queue.get(timeout=timeout)
        if item is _CLOSED:
            raise RuntimeError("subscription is closed")
        return item  # type: ignore[return-value]

    def close(self) -> None:
        if not self._closed:
            self._bus.unsubscribe(self.id)

    def _mark_closed(self) -> None:
        self._closed = True
        try:
            self._queue.put_nowait(_CLOSED)
        except Full:
            try:
                self._queue.get_nowait()
            except Empty:
                pass
            self._queue.put_nowait(_CLOSED)

    def __enter__(self) -> Subscription:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()


class EventBus:
    """Publishes synchronously into bounded queues; idle cost is effectively zero."""

    def __init__(self) -> None:
        self._lock = Lock()
        self._subscribers: dict[int, Subscription] = {}
        self._next_subscription_id = 1
        self._next_sequence = 1
        self._closed = False

    def subscribe(self, *patterns: str, max_queue: int = 128) -> Subscription:
        if max_queue < 1:
            raise ValueError("max_queue must be positive")
        patterns = patterns or ("*",)
        with self._lock:
            if self._closed:
                raise RuntimeError("event bus is closed")
            subscription_id = self._next_subscription_id
            self._next_subscription_id += 1
            subscription = Subscription(self, subscription_id, tuple(patterns), max_queue)
            self._subscribers[subscription_id] = subscription
            return subscription

    def publish(
        self,
        event_type: str,
        payload: Mapping[str, Any] | None = None,
        *,
        source: str = "core",
        correlation_id: str | None = None,
        sensitive: bool = False,
    ) -> Event:
        if not event_type or any(char.isspace() for char in event_type):
            raise ValueError("event_type must be a non-empty dotted identifier")
        with self._lock:
            if self._closed:
                raise RuntimeError("event bus is closed")
            sequence = self._next_sequence
            self._next_sequence += 1
            subscribers = tuple(self._subscribers.values())
        event = Event(
            sequence=sequence,
            type=event_type,
            source=source,
            payload=MappingProxyType(dict(payload or {})),
            correlation_id=correlation_id,
            sensitive=sensitive,
        )
        for subscription in subscribers:
            if subscription.matches(event_type):
                subscription._offer(event)
        return event

    def unsubscribe(self, subscription_id: int) -> None:
        with self._lock:
            subscription = self._subscribers.pop(subscription_id, None)
        if subscription is not None:
            subscription._mark_closed()

    def close(self) -> None:
        with self._lock:
            if self._closed:
                return
            self._closed = True
            subscriptions = tuple(self._subscribers.values())
            self._subscribers.clear()
        for subscription in subscriptions:
            subscription._mark_closed()

    @property
    def subscriber_count(self) -> int:
        with self._lock:
            return len(self._subscribers)
