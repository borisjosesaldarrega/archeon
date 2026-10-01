"""Verified, provider-based application update contracts."""

from archeon.updates.manager import (
    GitHubReleaseProvider,
    ReleaseInfo,
    UnconfiguredUpdateProvider,
    UpdateManager,
    UpdateProvider,
)

__all__ = ["ReleaseInfo", "GitHubReleaseProvider", "UnconfiguredUpdateProvider", "UpdateManager", "UpdateProvider"]
