"""Lazy, provider-based local document support for ARCHI."""

from .editor import DocumentEditor
from .engine import DocumentAgentEngine
from .reader import DocumentContent, DocumentPage, DocumentReader
from .renderer import DocumentRenderer
from .resolver import DocumentCandidate, DocumentResolution, DocumentResolver
from .style import DocumentStyleProfile
from .evidence import EvidenceCapture, write_evidence_manifest
from .quality import RequirementChecker, RequirementResult

__all__ = [
    "DocumentAgentEngine", "DocumentContent", "DocumentEditor", "DocumentPage",
    "DocumentReader", "DocumentRenderer", "DocumentCandidate", "DocumentResolution", "DocumentResolver",
    "DocumentStyleProfile", "EvidenceCapture", "write_evidence_manifest",
    "RequirementChecker", "RequirementResult",
]
