from __future__ import annotations

import logging
import tempfile
import unittest
from pathlib import Path

from archeon.core.config import ConfigurationManager
from archeon.core.language import LanguageContextEngine
from archeon.core.events import EventBus
from archeon.sync import ConflictResolution, SettingsEnvelope, SettingsSyncEngine
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
            self.assertEqual(updated["schema_version"], 5)
            self.assertEqual(manager.config.locale, "fr")
            self.assertEqual(manager.config.assistant.wake_name, "Nova")
            manager.update_settings({"appearance": {"command_input_visible": False, "large_targets": True, "left_handed": True, "visual_voice_cues": False}})
            self.assertFalse(manager.config.appearance.command_input_visible)
            self.assertTrue(manager.config.appearance.large_targets)
            self.assertTrue(manager.config.appearance.left_handed)
            self.assertFalse(manager.config.appearance.visual_voice_cues)
            manager.update_settings({"assistant": {"listening_paused": True, "pause_listening_phrase": "silencio archi", "resume_listening_phrase": "continúa archi"}})
            self.assertTrue(manager.config.assistant.listening_paused)
            self.assertEqual(manager.config.assistant.resume_listening_phrase, "continúa archi")
            manager.update_settings({"appearance": {"accent_color": "#A855F7"}, "assistant": {"preferred_name": "DZ"}})
            self.assertEqual(manager.config.appearance.accent_color, "#A855F7")
            self.assertEqual(manager.config.assistant.preferred_name, "DZ")
            manager.update_settings({"appearance": {"interface_layout": {
                "clock": {"x": 84, "y": -32, "anchor": "viewport", "left": 74.25, "top": 18.75, "color": "#22C55E", "visible": False, "scale": 135},
                "top_actions": {"x": -20, "y": 12, "color": "invalid", "visible": False},
                "conversation": {"x": 200, "y": -80, "width": 88, "scale": 90, "background": "#112233", "text_color": "#E5F7FA", "style": "bubbles"},
                "unknown": {"x": 999},
            }}})
            self.assertEqual(manager.config.appearance.interface_layout["clock"]["x"], 84)
            self.assertEqual(manager.config.appearance.interface_layout["clock"]["color"], "#22C55E")
            self.assertFalse(manager.config.appearance.interface_layout["clock"]["visible"])
            self.assertEqual(manager.config.appearance.interface_layout["clock"]["scale"], 135)
            self.assertEqual(manager.config.appearance.interface_layout["clock"]["anchor"], "viewport")
            self.assertEqual(manager.config.appearance.interface_layout["clock"]["left"], 74.25)
            self.assertEqual(manager.config.appearance.interface_layout["clock"]["top"], 18.75)
            self.assertTrue(manager.config.appearance.interface_layout["menu_toggle"]["visible"])
            self.assertIsNone(manager.config.appearance.interface_layout["session_badge"]["color"])
            self.assertEqual(manager.config.appearance.interface_layout["conversation"]["width"], 88)
            self.assertEqual(manager.config.appearance.interface_layout["conversation"]["scale"], 90)
            self.assertEqual(manager.config.appearance.interface_layout["conversation"]["background"], "#112233")
            self.assertEqual(manager.config.appearance.interface_layout["conversation"]["text_color"], "#E5F7FA")
            self.assertEqual(manager.config.appearance.interface_layout["conversation"]["style"], "bubbles")
            self.assertNotIn("unknown", manager.config.appearance.interface_layout)
            self.assertFalse(manager.config.privacy.cloud_processing_allowed)
            self.assertFalse(manager.config.privacy.cloud_screenshots_allowed)
            self.assertFalse(manager.config.startup.startup_sound)
            manager.update_settings({"startup": {"launch_at_login": True, "window_mode": "maximized"}})
            manager.update_settings({"voice": {"speaker_verification_enabled": True, "speaker_rejection_feedback": "visual"}})
            self.assertTrue(manager.config.startup.launch_at_login)
            self.assertEqual(manager.config.startup.window_mode, "maximized")
            payloads = manager.sync_payloads()
            self.assertGreater(payloads["account"]["version"], 0)
            self.assertNotIn("background_path", payloads["account"]["settings"]["appearance"])
            self.assertFalse(payloads["account"]["settings"]["appearance"]["command_input_visible"])
            self.assertTrue(payloads["account"]["settings"]["appearance"]["large_targets"])
            self.assertTrue(payloads["account"]["settings"]["appearance"]["left_handed"])
            self.assertFalse(payloads["account"]["settings"]["appearance"]["visual_voice_cues"])
            self.assertEqual(payloads["account"]["settings"]["appearance"]["accent_color"], "#A855F7")
            self.assertIn("background_path", payloads["device"]["settings"]["appearance"])
            self.assertIn("interface_layout", manager.sync_payloads()["device"]["settings"]["appearance"])
            self.assertNotIn("interface_layout", manager.sync_payloads()["account"]["settings"]["appearance"])
            self.assertNotIn("position_x", payloads["account"]["settings"]["ghost"])
            self.assertIn("position_x", payloads["device"]["settings"]["ghost"])
            self.assertNotIn("input_device_id", payloads["account"]["settings"]["voice"])
            self.assertNotIn("speaker_verification_enabled", payloads["account"]["settings"]["voice"])
            self.assertTrue(payloads["device"]["settings"]["voice"]["speaker_verification_enabled"])
            self.assertEqual(payloads["account"]["settings"]["media"]["alternative_versions"], "ask")
            manager.update_settings({"media": {"preferred_volume": 42, "dj_mode": True}})
            self.assertEqual(manager.config.media.preferred_volume, 42)
            self.assertTrue(manager.config.media.dj_mode)
            manager.update_settings({"clock": {"visible": True, "use_24_hour": True, "show_seconds": True, "show_date": False}})
            self.assertTrue(manager.config.clock.use_24_hour)
            self.assertTrue(manager.config.clock.show_seconds)
            self.assertFalse(manager.config.clock.show_date)
            reloaded = ConfigurationManager(Path(directory) / "config.json")
            reloaded.start()
            self.assertEqual(reloaded.config.appearance.interface_layout["clock"]["x"], 84)
            self.assertEqual(reloaded.config.appearance.interface_layout["clock"]["left"], 74.25)
            self.assertEqual(reloaded.config.appearance.interface_layout["clock"]["top"], 18.75)
            self.assertEqual(reloaded.config.appearance.interface_layout["conversation"]["background"], "#112233")
            self.assertEqual(reloaded.config.appearance.interface_layout["conversation"]["style"], "bubbles")
            self.assertTrue(reloaded.config.assistant.listening_paused)
            self.assertEqual(reloaded.config.media.preferred_volume, 42)
            self.assertTrue(reloaded.config.clock.use_24_hour)
            self.assertTrue(reloaded.config.clock.show_seconds)
            self.assertFalse(reloaded.config.clock.show_date)
            self.assertEqual(
                set(payloads["account"]["settings"]["intelligence"]),
                {"profile", "memory_enabled", "conversation_turns"},
            )
            self.assertNotIn("intelligence", payloads["device"]["settings"])
            self.assertNotIn("model_id", str(payloads))
            version = manager.config.sync.version
            manager.touch_sync()
            self.assertEqual(manager.config.sync.version, version + 1)
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

    def test_settings_sync_conflicts_use_version_then_timestamp(self) -> None:
        local = SettingsEnvelope(3, "2026-08-21T10:00:00+00:00", {"theme": "dark"})
        remote = SettingsEnvelope(2, "2026-08-21T11:00:00+00:00", {"theme": "light"})
        self.assertEqual(SettingsSyncEngine.resolve(local, remote), ConflictResolution.LOCAL)
        newer_remote = SettingsEnvelope(3, "2026-08-21T12:00:00+00:00", {})
        self.assertEqual(SettingsSyncEngine.resolve(local, newer_remote), ConflictResolution.REMOTE)

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
