# Authentication

The canonical owner is `src/archeon/auth/`; preference synchronization is `src/archeon/sync/`. With no Supabase configuration the app uses an explicit `not_configured` provider rather than simulated accounts. Guest sessions remain local.

Implemented contracts cover registration, repeated password, 8-digit OTP, login, recovery, MFA methods, session refresh/logout and RLS-scoped sync. Local and mocked-provider regressions pass. A real remote PASS requires an active Supabase project, controlled mailbox/account and working network. The current remote project is inactive/unreachable, so remote registration, OTP, login, recovery, MFA, RLS and online sync are `BLOCKED EXTERNALLY`.
