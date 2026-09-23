# Security

- Secrets are not embedded in `src/`, build inputs or package metadata.
- Windows local tokens and speaker signatures use DPAPI with UI disabled.
- Plugins fail closed: manifest/schema, compatibility, archive paths, size, SHA-256, Ed25519 publisher signature and explicit permissions are checked before a separate host process starts.
- Separate process is not an OS security boundary. Untrusted third-party execution needs an AppContainer/broker and is outside this release candidate.
- Updates fail closed and cannot claim success without a configured signed provider.
- File and computer actions use scoped permissions, cancellation and verification. Broad destructive legacy utilities were not migrated.
- `.env`, `.env.local` and Firebase service-account files are ignored legacy/local material. Values must never be logged. External keys must be rotated/revoked before those files are removed.
