"""Core primitives with no third-party runtime dependencies."""

from .events import Event, EventBus, Subscription
from .lifecycle import ComponentState, LifecycleManager, ManagedComponent

__all__ = [
    "ComponentState",
    "Event",
    "EventBus",
    "LifecycleManager",
    "ManagedComponent",
    "Subscription",
]

