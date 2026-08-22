"""Lazy persistence adapters with no cloud client import at startup."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

from archeon.core.lifecycle import ManagedComponent


class DatabaseProvider(Protocol):
    name: str

    def connect(self) -> None: ...

    def close(self) -> None: ...

    def health(self) -> dict[str, Any]: ...


class NullDatabaseProvider:
    name = "none"

    def connect(self) -> None:
        return None

    def close(self) -> None:
        return None

    def health(self) -> dict[str, Any]:
        return {"provider": self.name, "connected": False, "mode": "local-only"}


@dataclass(slots=True)
class SupabaseProvider:
    """Optional provider. Importing `supabase` occurs only on explicit connect."""

    url: str
    publishable_key: str
    name: str = "supabase"
    _client: Any = None

    def connect(self) -> None:
        if not self.url or not self.publishable_key:
            raise RuntimeError("Supabase is not configured")
        try:
            from supabase import create_client
        except ImportError as error:
            raise RuntimeError("optional Supabase client is not installed") from error
        self._client = create_client(self.url, self.publishable_key)

    def close(self) -> None:
        self._client = None

    def health(self) -> dict[str, Any]:
        return {"provider": self.name, "connected": self._client is not None}


class DatabaseManager(ManagedComponent):
    def __init__(self, provider_factory=NullDatabaseProvider) -> None:
        super().__init__("database")
        self._factory = provider_factory
        self._provider: DatabaseProvider | None = None

    @property
    def loaded(self) -> bool:
        return self._provider is not None

    def connect(self) -> DatabaseProvider:
        if self._provider is None:
            self._provider = self._factory()
            self._provider.connect()
        return self._provider

    def health(self) -> dict[str, Any]:
        if self._provider is None:
            return {"provider": "unloaded", "connected": False}
        return self._provider.health()

    def _start(self) -> None:
        return None

    def _stop(self) -> None:
        if self._provider is not None:
            self._provider.close()
            self._provider = None

