# Plugins

`src/archeon/plugins/` is the only extension owner. Packages require a valid manifest, supported version, safe paths, bounded content, package integrity, a trusted Ed25519 publisher signature and explicitly granted known permissions. Startup re-verifies installed packages. Enable, disable, restart, update and remove share the same lifecycle and shutdown path.

No trusted production publisher key is provisioned, so installation remains fail-closed and the UI reports `NOT CONFIGURED`. Process isolation alone is not sufficient for arbitrary untrusted third-party code; AppContainer/broker isolation is outside the current scope.
