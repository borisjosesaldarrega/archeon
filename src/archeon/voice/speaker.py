"""Local speaker profiles for wake-word authorization.

Only compact acoustic embeddings are persisted. Raw microphone samples are never
written by this module.
"""

from __future__ import annotations

import math
from array import array
from datetime import UTC, datetime
from threading import RLock
from typing import Any, Protocol
from uuid import uuid4


class SpeakerProfileVault(Protocol):
    def save(self, value: dict[str, Any]) -> None: ...
    def load(self) -> dict[str, Any] | None: ...


def _goertzel(samples: list[float], frequency: float, sample_rate: int) -> float:
    coefficient = 2.0 * math.cos(2.0 * math.pi * frequency / sample_rate)
    previous = previous_two = 0.0
    for sample in samples:
        current = sample + coefficient * previous - previous_two
        previous_two, previous = previous, current
    power = previous_two * previous_two + previous * previous - coefficient * previous * previous_two
    return math.log1p(max(0.0, power) / max(1, len(samples)))


def speaker_embedding(pcm: bytes, sample_rate: int = 16_000) -> tuple[float, ...]:
    """Extract a volume-independent acoustic signature using only local CPU."""
    values = array("h")
    values.frombytes(pcm[: len(pcm) - len(pcm) % 2])
    minimum = int(sample_rate * 0.75)
    if len(values) < minimum:
        raise ValueError("speaker_sample_too_short")
    peak = max(abs(value) for value in values)
    if peak < 300:
        raise ValueError("speaker_sample_too_quiet")
    normalized = [float(value) / peak for value in values]
    frame_size = max(160, sample_rate // 50)
    frames = [normalized[index:index + frame_size] for index in range(0, len(normalized) - frame_size + 1, frame_size)]
    energetic = []
    for frame in frames:
        rms = math.sqrt(sum(value * value for value in frame) / len(frame))
        if rms >= 0.035:
            energetic.append((frame, rms))
    if len(energetic) < 12:
        raise ValueError("speaker_sample_has_insufficient_speech")
    zcr = [sum(1 for a, b in zip(frame, frame[1:]) if (a < 0) != (b < 0)) / len(frame) for frame, _ in energetic]
    rms_values = [rms for _, rms in energetic]
    frequencies = (180, 260, 380, 540, 760, 1050, 1450, 2000, 2800, 3800)
    spectral = [[_goertzel(frame, frequency, sample_rate) for frequency in frequencies] for frame, _ in energetic]

    def mean(values_: list[float]) -> float:
        return sum(values_) / max(1, len(values_))

    def deviation(values_: list[float]) -> float:
        center = mean(values_)
        return math.sqrt(sum((value - center) ** 2 for value in values_) / max(1, len(values_)))

    features = [mean(zcr), deviation(zcr), mean(rms_values), deviation(rms_values)]
    for column in range(len(frequencies)):
        band = [row[column] for row in spectral]
        features.extend((mean(band), deviation(band)))
    magnitude = math.sqrt(sum(value * value for value in features))
    if magnitude <= 1e-9:
        raise ValueError("speaker_embedding_failed")
    return tuple(round(value / magnitude, 7) for value in features)


def cosine_similarity(first: tuple[float, ...], second: tuple[float, ...]) -> float:
    if len(first) != len(second) or not first:
        return 0.0
    return max(-1.0, min(1.0, sum(a * b for a, b in zip(first, second))))


class SpeakerVerificationManager:
    """Manage multiple encrypted, local-only authorized speaker profiles."""

    def __init__(self, vault: SpeakerProfileVault, *, threshold: float = 0.965) -> None:
        self._vault = vault
        self._threshold = max(0.8, min(0.999, float(threshold)))
        self._lock = RLock()
        stored = vault.load() or {}
        profiles = stored.get("profiles", [])
        self._profiles = [dict(profile) for profile in profiles if isinstance(profile, dict)]

    def public_profiles(self) -> list[dict[str, Any]]:
        with self._lock:
            return [{key: profile.get(key) for key in ("id", "name", "role", "enabled", "created_at", "updated_at")}
                    | {"sample_count": len(profile.get("embeddings", []))} for profile in self._profiles]

    def enroll(self, name: str, pcm_samples: list[bytes], *, role: str = "owner", profile_id: str | None = None) -> dict[str, Any]:
        clean_name = " ".join(str(name).split()).strip()
        if not clean_name or len(clean_name) > 48:
            raise ValueError("invalid_speaker_name")
        if len(pcm_samples) < 3:
            raise ValueError("speaker_enrollment_requires_three_samples")
        embeddings = [list(speaker_embedding(sample)) for sample in pcm_samples]
        now = datetime.now(UTC).isoformat()
        with self._lock:
            existing = next((profile for profile in self._profiles if profile.get("id") == profile_id), None)
            if existing is None:
                existing = {"id": uuid4().hex, "created_at": now}
                self._profiles.append(existing)
            existing.update({"name": clean_name, "role": "owner" if role == "owner" else "authorized",
                             "enabled": True, "updated_at": now, "embeddings": embeddings})
            self._save()
            public_id = str(existing["id"])
        return next(profile for profile in self.public_profiles() if profile["id"] == public_id)

    def verify(self, pcm: bytes) -> dict[str, Any]:
        candidate = speaker_embedding(pcm)
        best_profile: dict[str, Any] | None = None
        best_score = -1.0
        with self._lock:
            for profile in self._profiles:
                if not profile.get("enabled", True):
                    continue
                scores = [cosine_similarity(candidate, tuple(float(value) for value in embedding))
                          for embedding in profile.get("embeddings", []) if isinstance(embedding, list)]
                score = max(scores, default=-1.0)
                if score > best_score:
                    best_profile, best_score = profile, score
        return {"authorized": bool(best_profile and best_score >= self._threshold),
                "profile_id": best_profile.get("id") if best_profile else None,
                "name": best_profile.get("name") if best_profile else None,
                "confidence": round(max(0.0, best_score), 4), "threshold": self._threshold}

    def update(self, profile_id: str, *, name: str | None = None, enabled: bool | None = None) -> dict[str, Any]:
        with self._lock:
            profile = self._require(profile_id)
            if name is not None:
                clean_name = " ".join(str(name).split()).strip()
                if not clean_name or len(clean_name) > 48:
                    raise ValueError("invalid_speaker_name")
                profile["name"] = clean_name
            if enabled is not None:
                profile["enabled"] = bool(enabled)
            profile["updated_at"] = datetime.now(UTC).isoformat()
            self._save()
        return next(item for item in self.public_profiles() if item["id"] == profile_id)

    def delete(self, profile_id: str) -> None:
        with self._lock:
            profile = self._require(profile_id)
            self._profiles.remove(profile)
            self._save()

    def _require(self, profile_id: str) -> dict[str, Any]:
        profile = next((item for item in self._profiles if item.get("id") == profile_id), None)
        if profile is None:
            raise ValueError("speaker_profile_not_found")
        return profile

    def _save(self) -> None:
        self._vault.save({"version": 1, "profiles": self._profiles})
