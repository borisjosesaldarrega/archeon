from __future__ import annotations

import math
import struct
import unittest

from archeon.auth import MemorySessionVault
from archeon.voice.speaker import SpeakerVerificationManager, speaker_embedding


def voice_sample(base_frequency: float, variation: float = 0.0, seconds: float = 1.4) -> bytes:
    sample_rate = 16_000
    values = []
    for index in range(int(sample_rate * seconds)):
        time = index / sample_rate
        envelope = 0.35 + 0.65 * abs(math.sin(2 * math.pi * 2.4 * time))
        value = envelope * (
            math.sin(2 * math.pi * (base_frequency + variation) * time)
            + 0.42 * math.sin(2 * math.pi * base_frequency * 2.15 * time)
            + 0.18 * math.sin(2 * math.pi * base_frequency * 3.7 * time)
        )
        values.append(max(-32767, min(32767, int(value * 11_000))))
    return struct.pack(f"<{len(values)}h", *values)


class SpeakerVerificationTests(unittest.TestCase):
    def test_embedding_rejects_short_or_quiet_audio(self) -> None:
        with self.assertRaisesRegex(ValueError, "too_short"):
            speaker_embedding(b"\0" * 100)
        with self.assertRaisesRegex(ValueError, "too_quiet"):
            speaker_embedding(b"\0" * 40_000)

    def test_multiple_profiles_authorize_matching_voice_and_reject_other_voice(self) -> None:
        vault = MemorySessionVault()
        manager = SpeakerVerificationManager(vault)
        owner = manager.enroll("Propietario", [voice_sample(170, delta) for delta in (-2, 0, 2)])
        guest = manager.enroll("Persona autorizada", [voice_sample(245, delta) for delta in (-2, 0, 2)], role="authorized")
        self.assertTrue(manager.verify(voice_sample(171))["authorized"])
        self.assertEqual(manager.verify(voice_sample(171))["profile_id"], owner["id"])
        self.assertTrue(manager.verify(voice_sample(246))["authorized"])
        self.assertEqual(manager.verify(voice_sample(246))["profile_id"], guest["id"])
        self.assertFalse(manager.verify(voice_sample(390))["authorized"])

    def test_profiles_persist_without_raw_audio_and_can_be_disabled_or_deleted(self) -> None:
        vault = MemorySessionVault()
        manager = SpeakerVerificationManager(vault)
        profile = manager.enroll("Mi voz", [voice_sample(185, delta) for delta in (-1, 0, 1)])
        stored = vault.load()
        self.assertIn("embeddings", stored["profiles"][0])
        self.assertNotIn("audio", str(stored).casefold())
        manager.update(profile["id"], name="Voz principal", enabled=False)
        self.assertFalse(manager.verify(voice_sample(185))["authorized"])
        reloaded = SpeakerVerificationManager(vault)
        self.assertEqual(reloaded.public_profiles()[0]["name"], "Voz principal")
        reloaded.delete(profile["id"])
        self.assertEqual(reloaded.public_profiles(), [])


if __name__ == "__main__":
    unittest.main()
