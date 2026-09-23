"""Opt-in plugin registry."""

from .manager import PluginManager, PluginManifest
from .trust import TrustedPublisherVerifier

__all__ = ["PluginManager", "PluginManifest", "TrustedPublisherVerifier"]
