# Supabase audit — 2026-08-21

Project inspected: `rcgipowzivogyqbuwzlv` (`archeon`). The inspection used catalog-only SQL and dashboard metadata. No application rows, credentials, browser cookies, or stored user content were read.

## Current inventory

- 11 public tables: `users`, `sessions`, `verification_codes`, `memoria`, `skills`, `comandos`, `gustos`, `chats_mensajes`, `archivos`, `conversaciones`, `mensajes`.
- Three decrypted-content views: `v_conversaciones_decifradas`, `v_mensajes_claros`, `v_mensajes_decifrados`.
- Nine public functions, five encryption-related triggers, one storage bucket policy for `archeon-archivos`.
- Foreign keys use the legacy text `public.users.id`; the current schema is not yet tied to `auth.users.id`.
- The dashboard reports no migrations, no branches and no managed backups for this Free project.

## Critical findings

1. RLS is enabled on all 11 public tables, but current policies use `USING (true)` / `WITH CHECK (true)` for the `public` role. RLS therefore does not isolate users.
2. `anon` and `authenticated` have broad table privileges, including write and truncate privileges, across legacy tables and decrypted views.
3. `anon` and `authenticated` can execute all nine public functions.
4. Supabase Security Advisor reports three errors: all decrypted views are Security Definer views and can bypass the querying user's RLS context.
5. Security Advisor reports 53 warnings, including mutable function `search_path` and permissive RLS policies.
6. Some tables contain authentication-sensitive fields (`password_hash`, `salt`, session signatures and verification codes) inside an exposed schema. They must not remain client-readable.
7. Several foreign-key columns lack supporting indexes; user-scoped queries will degrade as data grows.

## Safe migration sequence

1. Add isolated `account_settings` and `device_settings` tables linked directly to `auth.users`, with explicit grants and owner-only RLS.
2. Integrate Supabase Auth in the application and verify two-user isolation plus anonymous denial.
3. Inventory legacy consumers and create a tested mapping from legacy text IDs to Auth UUIDs.
4. Revoke anonymous access to secrets and decrypted views before removing permissive policies.
5. Rebuild views as `security_invoker`, lock function `search_path`, reduce function execution grants and add user-scope indexes.
6. Migrate encrypted content and authentication records in reversible batches; retain a reconciliation ledger.
7. Only after verification, retire custom password/session/code storage. No destructive step is included in the first migration.

The first reproducible migration is `supabase/migrations/202608210001_settings_foundation.sql`. It is deliberately additive because the project currently has no managed backup.

## Applied checkpoint

The first migration was applied through the authenticated Supabase SQL editor on 2026-08-21 and then verified from PostgreSQL catalogs:

- both settings tables exist with RLS enabled and forced;
- all eight owner policies target only `authenticated` and compare `auth.uid()` with `user_id`;
- `anon` has zero table grants;
- `authenticated` has only `SELECT`, `INSERT`, `UPDATE`, and `DELETE`;
- both ownership foreign keys reference `auth.users(id) ON DELETE CASCADE`.

Legacy security findings remain open. They were intentionally not changed in this additive checkpoint because no managed backup is available and the current desktop build still uses the legacy local development auth provider.
