# ARCHEON Data Recovery and Database Plan

## Recovered local SQLite

Database: `archeon_files.db` (excluded from Git because it contains local paths).

```sql
CREATE TABLE file_index (
  name TEXT,
  path TEXT,
  type TEXT,
  last_seen DATETIME
);
```

Recovered row count: 978. There is no primary key, uniqueness constraint or search index. The table is deleted and rebuilt by a startup recursive scan. Replace this with on-demand/native search and, if a cache remains, use a normalized path key, indexed name/type, scan generation and bounded retention.

## Recovered Firebase model

The supplied source uses Firebase Admin/Firestore and contains these literal collection names:

- `users`: email, password hash, config and timestamps.
- `sessions`: custom signed session records and expiration.
- `verification_codes`: email/code/expiration records.
- nested `memoria`, `gustos`, `comandos` under users.
- nested `chats` and `mensajes` for message history/unread state.

This is a behavioral reconstruction from source, not a live Firebase export. Shipping Firebase Admin credentials in the client is unsafe and must not be preserved.

## Supabase audit status

Target project ref: `rcgipowzivogyqbuwzlv`.

Status: `BLOCKED — AUTHORIZATION/SESSION`. The available Supabase connector sees a different account/project, and the in-app browser is signed out. No live target schemas, tables, users, rows, RLS policies, functions, triggers, buckets or storage objects have been inspected. No changes were made.

To unblock safely, connect the Supabase plugin to the account that owns the target project or sign into Supabase in an available browser. The audit will remain read-only until a migration is separately reviewed.

## Required live audit queries

When access is available, collect only metadata/counts initially:

1. schemas, tables, columns, PK/FK/unique/check constraints;
2. indexes and table/index sizes;
3. RLS enabled/forced flags and policies;
4. functions with language, volatility, security-definer/invoker and grants;
5. triggers, publications/realtime membership and extensions;
6. auth configuration and aggregate user/session counts without exposing identities;
7. storage buckets, object counts and policies without downloading user objects;
8. security and performance advisors;
9. migration history and drift.

## Provisional target domains

Do not create these until the live schema is reconciled:

- `profiles` — one row per `auth.users` identity.
- `user_settings` — versioned preferences including performance profile and locale.
- `devices` and `device_credentials` — revocable PC/mobile pairing.
- `memories` — typed, consented long-term/device facts with retention and provenance.
- `conversations` and `messages` — optional synced history with user ownership.
- `tool_runs` — redacted audit metadata; sensitive payloads remain local by default.
- `automations` and `automation_runs` — structured trigger/action definitions.
- `media_favorites` and `media_history` — optional user media state.

Every exposed table must have RLS. Ownership checks use `(select auth.uid()) = user_id`; update policies require both `USING` and `WITH CHECK`. Never authorize from user-editable metadata, never expose a service-role/secret key, and use `security_invoker` views when exposed.

## Migration rules

- First snapshot and document the live schema; do not delete or rename in place.
- Write reproducible SQL migrations in source control.
- Backfill into new structures, validate counts/constraints, then switch readers/writers.
- Keep rollback/compatibility views where required.
- Run Supabase security/performance advisors and test as `anon`, `authenticated` owner, authenticated non-owner and service backend.
- User-data deletion/export must be explicit, audited and reversible where legally/technically possible.

