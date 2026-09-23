"""Central permission decisions with deny-by-default behavior."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Callable, Iterable

from .config import ConfigurationManager


class PermissionState(StrEnum):
    DENIED = "denied"
    ASK = "ask"
    SESSION = "session"
    ALWAYS = "always"


class RiskLevel(StrEnum):
    READ_ONLY = "read_only"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


@dataclass(frozen=True, slots=True)
class PermissionRequest:
    permissions: tuple[str, ...]
    risk: RiskLevel
    action: str
    reason: str


@dataclass(frozen=True, slots=True)
class PermissionDecision:
    allowed: bool
    reason: str


Confirmer = Callable[[PermissionRequest], bool]


class PermissionEngine:
    def __init__(self, configuration: ConfigurationManager) -> None:
        self._configuration = configuration
        self._session_grants: set[str] = set()

    def get_state(self, permission: str) -> PermissionState:
        if permission in self._session_grants:
            return PermissionState.SESSION
        value = self._configuration.config.permissions.get(permission, PermissionState.ASK.value)
        try:
            return PermissionState(value)
        except ValueError:
            return PermissionState.ASK

    def set_state(self, permission: str, state: PermissionState) -> None:
        if state is PermissionState.SESSION:
            self._session_grants.add(permission)
            return
        self._session_grants.discard(permission)
        self._configuration.set_permission(permission, state.value)

    def evaluate(
        self,
        permissions: Iterable[str],
        *,
        risk: RiskLevel,
        action: str,
        reason: str,
        confirmer: Confirmer | None = None,
        ephemeral_grants: Iterable[str] = (),
    ) -> PermissionDecision:
        required = tuple(sorted(set(permissions)))
        if not required:
            return PermissionDecision(True, "no permissions required")
        states = {permission: self.get_state(permission) for permission in required}
        denied = [permission for permission, state in states.items() if state is PermissionState.DENIED]
        if denied:
            return PermissionDecision(False, f"denied: {', '.join(denied)}")
        scoped = set(ephemeral_grants)
        states = {
            permission: (PermissionState.SESSION if permission in scoped else state)
            for permission, state in states.items()
        }
        pending = [permission for permission, state in states.items() if state is PermissionState.ASK]
        if not pending:
            return PermissionDecision(True, "granted")
        approval_mode = self._configuration.config.approval.mode
        if approval_mode == "balanced" and risk is RiskLevel.READ_ONLY:
            return PermissionDecision(True, "read-only action allowed by balanced approval mode")
        if approval_mode == "full_control" and risk in {
            RiskLevel.READ_ONLY, RiskLevel.LOW, RiskLevel.MEDIUM,
        }:
            return PermissionDecision(True, "action allowed by full-control approval mode")
        if confirmer is None:
            return PermissionDecision(False, f"confirmation required: {', '.join(pending)}")
        request = PermissionRequest(tuple(pending), risk, action, reason)
        if not confirmer(request):
            return PermissionDecision(False, "user declined")
        self._session_grants.update(pending)
        return PermissionDecision(True, "granted for session")

    def clear_session(self) -> None:
        self._session_grants.clear()
