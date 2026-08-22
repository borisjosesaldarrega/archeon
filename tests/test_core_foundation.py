from __future__ import annotations

import logging
import tempfile
import unittest
from pathlib import Path

from archeon.core.config import ConfigurationManager
from archeon.core.events import EventBus
from archeon.core.lifecycle import ComponentState, LifecycleManager, ManagedComponent
from archeon.core.secure_logging import configure_logging


class _Recorder(ManagedComponent):
    def __init__(self, name: str, actions: list[str]) -> None:
        super().__init__(name)
        self.actions = actions

    def _start(self) -> None:
        self.actions.append(f"start:{self.name}")

    def _stop(self) -> None:
        self.actions.append(f"stop:{self.name}")


class CoreFoundationTests(unittest.TestCase):
    def test_event_bus_filters_and_bounds_queues(self) -> None:
        bus = EventBus()
        subscription = bus.subscribe("assistant.*", max_queue=2)
        bus.publish("music.started")
        bus.publish("assistant.listening", {"level": 1})
        bus.publish("assistant.thinking")
        bus.publish("assistant.speaking")
        self.assertEqual(subscription.dropped_events, 1)
        self.assertEqual(subscription.get(timeout=0.1).type, "assistant.thinking")
        self.assertEqual(subscription.get(timeout=0.1).type, "assistant.speaking")
        subscription.close()
        self.assertEqual(bus.subscriber_count, 0)
        bus.close()

    def test_lifecycle_stops_in_reverse_order(self) -> None:
        actions: list[str] = []
        first = _Recorder("first", actions)
        second = _Recorder("second", actions)
        lifecycle = LifecycleManager((first, second))
        lifecycle.start()
        lifecycle.stop()
        self.assertEqual(actions, ["start:first", "start:second", "stop:second", "stop:first"])
        self.assertEqual(first.state, ComponentState.STOPPED)

    def test_configuration_is_atomic_and_validated(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "config.json"
            manager = ConfigurationManager(path)
            manager.start()
            manager.config.ghost.size = 999
            manager.config.performance.profile = "eco"
            manager.stop()
            loaded = ConfigurationManager(path)
            loaded.start()
            self.assertEqual(loaded.config.ghost.size, 256)
            self.assertEqual(loaded.config.performance.profile, "eco")
            loaded.stop()

    def test_logging_redacts_secret_values(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            logger = configure_logging(Path(directory))
            logger.info("token=super-secret password=hunter2")
            for handler in logger.handlers:
                handler.flush()
            text = (Path(directory) / "archeon.log").read_text(encoding="utf-8")
            self.assertNotIn("super-secret", text)
            self.assertNotIn("hunter2", text)
            self.assertIn("<redacted>", text)
            logging.shutdown()


if __name__ == "__main__":
    unittest.main()
