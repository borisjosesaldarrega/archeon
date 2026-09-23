"""Provider-neutral lifecycle facade for local intelligence."""

from __future__ import annotations

from typing import Any

from archeon.core.lifecycle import ManagedComponent

from .models import GenerationRequest, GenerationResult, ModelState
from .providers import ModelProvider


class ModelManager(ManagedComponent):
    def __init__(self, provider: ModelProvider | None = None) -> None:
        super().__init__("local_ai")
        self._provider = provider

    @property
    def available(self) -> bool:
        return self._provider is not None

    @property
    def model_state(self) -> ModelState:
        return self._provider.state if self._provider else ModelState.UNLOADED

    def configure(self, provider: ModelProvider | None) -> None:
        if self._provider is not None:
            self._provider.unload()
        self._provider = provider

    def generate(self, request: GenerationRequest) -> GenerationResult:
        if self._provider is None:
            raise RuntimeError("local_ai_unavailable")
        return self._provider.generate(request)

    def unload(self) -> None:
        if self._provider is not None:
            self._provider.unload()

    def status(self) -> dict[str, Any]:
        if self._provider is None:
            return {"available": False, "state": ModelState.UNLOADED.value}
        return {"available": True, **self._provider.status()}

    def _start(self) -> None:
        pass  # Deliberately does not load the model.

    def _stop(self) -> None:
        self.unload()
