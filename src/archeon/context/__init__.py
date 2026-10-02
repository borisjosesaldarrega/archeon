"""Bounded local request context for text and referenced attachments."""

from .attachments import AttachmentRecord, AttachmentStore, UserRequestContext
from .file_router import FileRoute, FileTypeRouter
from .budget import (
    ContextBudget, ContextBudgetManager, ContextOptimizer, ConversationMemory,
    ResponseBudget, ResponseBudgetManager, estimate_tokens,
)
from .topic import ContextRelevanceGate, TopicDecision
from .interpreter import (
    ContextEntity, ContextFact, ContextInterpretation, ContextInterpreter,
    ContextRegistry, ConversationContextManager, ConversationState,
    EntityDefinition, EvidenceStatus, IntentDefinition, ThreadResolution,
    TopicDefinition, TopicThread,
)

__all__ = [
    "AttachmentRecord", "AttachmentStore", "UserRequestContext", "FileRoute", "FileTypeRouter",
    "ContextBudget", "ContextBudgetManager", "ContextOptimizer", "ConversationMemory",
    "ResponseBudget", "ResponseBudgetManager", "estimate_tokens",
    "ContextRelevanceGate", "TopicDecision",
    "ContextEntity", "ContextFact", "ContextInterpretation", "ContextInterpreter",
    "ContextRegistry", "ConversationContextManager", "ConversationState",
    "EntityDefinition", "EvidenceStatus", "IntentDefinition", "ThreadResolution",
    "TopicDefinition", "TopicThread",
]
