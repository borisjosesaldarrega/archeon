"""Fail-closed remote command execution for a paired ARCHEON device."""

from __future__ import annotations

import json
import os
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Any, Callable, Mapping

from .models import RemoteAction, RemoteCommand, RemoteControlPolicy


class CommandReplayStore:
    """Small atomic idempotency ledger; it stores IDs only, never command bodies."""

    def __init__(self, path: Path, *, maximum: int = 2000) -> None:
        self._path = path
        self._maximum = max(100, maximum)

    def values(self) -> set[str]:
        try:
            value = json.loads(self._path.read_text(encoding="utf-8"))
        except (OSError, ValueError, json.JSONDecodeError):
            return set()
        return {str(item) for item in value[-self._maximum:]} if isinstance(value, list) else set()

    def add(self, value: str) -> None:
        values = list(self.values())
        if value not in values:
            values.append(value)
        values = values[-self._maximum:]
        self._path.parent.mkdir(parents=True, exist_ok=True)
        with NamedTemporaryFile("w", encoding="utf-8", dir=self._path.parent, suffix=".tmp", delete=False) as pending:
            json.dump(values, pending, separators=(",", ":"))
            pending.flush()
            os.fsync(pending.fileno())
            temporary = Path(pending.name)
        os.replace(temporary, self._path)


class RemoteCommandExecutor:
    """Execute only explicitly registered actions after cryptographic authorization."""

    def __init__(
        self,
        policy: RemoteControlPolicy,
        pairing_secret_provider: Callable[[str], bytes | None],
        replay_store: CommandReplayStore,
        handlers: Mapping[RemoteAction, Callable[[Mapping[str, Any]], dict[str, Any]]],
    ) -> None:
        self._policy = policy
        self._secret = pairing_secret_provider
        self._replay = replay_store
        self._handlers = dict(handlers)

    def execute(self, command: RemoteCommand) -> dict[str, Any]:
        handler = self._handlers.get(command.action)
        if handler is None:
            raise PermissionError("remote_action_not_supported")
        arguments = dict(command.arguments)
        confirmation = arguments.pop("confirmation_token", None)
        seen = self._replay.values()
        self._policy.authorize(
            command,
            self._secret(command.source_device_id),
            confirmation_token=str(confirmation) if confirmation else None,
            seen_idempotency_keys=seen,
        )
        result = handler(arguments)
        if not isinstance(result, dict) or not result.get("ok"):
            raise RuntimeError(str(result.get("error", "remote_action_failed")) if isinstance(result, dict) else "remote_action_failed")
        self._replay.add(command.idempotency_key)
        return result
