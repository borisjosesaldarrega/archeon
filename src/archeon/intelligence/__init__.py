"""Lazy, provider-neutral intelligence services."""

from .manager import ModelManager
from .models import GenerationRequest, GenerationResult, ModelDescriptor, ModelState
from .providers import LlamaCppProvider, ModelProvider
from .resources import MemoryPressureGuard, MemorySnapshot, system_memory_snapshot
from .router import ModelRouter, RouteDecision

__all__ = [
    "GenerationRequest", "GenerationResult", "LlamaCppProvider", "ModelDescriptor",
    "MemoryPressureGuard", "MemorySnapshot", "ModelManager", "ModelProvider", "ModelRouter",
    "ModelState", "RouteDecision", "system_memory_snapshot",
]
