from __future__ import annotations

import logging
import tempfile
import unittest
from pathlib import Path

from archeon.core.config import ConfigurationManager
from archeon.core.language import LanguageContextEngine
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
        speaking = subscription.get(timeout=0.1)
        self.assertEqual(speaking.type, "assistant.speaking")
        self.assertIsInstance(speaking.to_dict()["payload"], dict)
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

    def test_settings_migrate_and_keep_cloud_private_by_default(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            manager = ConfigurationManager(Path(directory) / "config.json")
            manager.start()
            updated = manager.update_settings({
                "language": {"interface": "fr", "conversation": "auto"},
                "assistant": {"wake_name": "Nova"},
            })
            self.assertEqual(updated["schema_version"], 2)
            self.assertEqual(manager.config.locale, "fr")
            self.assertEqual(manager.config.assistant.wake_name, "Nova")
            self.assertFalse(manager.config.privacy.cloud_processing_allowed)
            self.assertFalse(manager.config.privacy.cloud_screenshots_allowed)
            self.assertFalse(manager.config.startup.startup_sound)
            manager.stop()

    def test_settings_reject_unknown_fields(self) -> None:
        manager = ConfigurationManager(Path("unused.json"))
        with self.assertRaisesRegex(ValueError, "unknown_setting"):
            manager.update_settings({"privacy": {"send_everything": True}})

    def test_language_context_is_independent_from_interface_language(self) -> None:
        engine = LanguageContextEngine()
        self.assertEqual(engine.decide("Please open the settings", fallback="es").response_language, "en")
        self.assertEqual(engine.decide("Por favor abre la configuración", fallback="en").response_language, "es")
        explicit = engine.decide("Please reply in Spanish", fallback="en")
        self.assertEqual(explicit.response_language, "es")
        self.assertEqual(explicit.source, "explicit_request")
        self.assertEqual(engine.decide("設定を開いてください", fallback="es").response_language, "ja")

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
