# Cloud and sync

Cloud contracts live in `src/archeon/cloud/`; preference synchronization lives in `src/archeon/sync/`. No unconfigured remote capability runs in the background. Offline changes can be queued only when a real sync backend was configured and then became unavailable; missing configuration returns `sync_backend_not_configured`.

## Mobile and files

The canonical runtime now exposes owner-scoped actions for conversation lists,
messages, devices and private cloud files. File uploads are streamed through the
loopback server with a 100 MiB limit, stored in the private `archeon-cloud`
bucket and verified by SHA-256 before preview or download. Active content such
as HTML and executables is never previewed.

`src/archeon/ui/mobile.html` is the first phone-optimized client. It supports
multiple local chats when the cloud is offline and account-backed chats/files
when the Supabase backend is reachable. It can be exercised from Android over
`adb reverse` without exposing the desktop loopback server to the LAN.

The schema and fail-closed execution contracts for paired remote commands are
present, including expiry, signatures, replay protection and an extra power
command confirmation. Device secret exchange and the continuously running
desktop command receiver are not complete, so remote open/play/shutdown remain
disabled rather than being simulated.

## External dependency status

Realtime account sync, cross-network file access and device relay require the
linked Supabase project to be reachable and the mobile/cloud migration to be
deployed. Local configuration alone is not considered proof that the backend is
operational.
