# Supabase backup and recovery

Project: `rcgipowzivogyqbuwzlv` (`archeon`). Real dumps are written to `backups/`, which is excluded from Git. Never commit database data, database passwords, access tokens, refresh tokens, MFA secrets, or OTP values.

## Current recovery status

- The project uses the Free plan and exposes no downloadable managed backup or PITR restore point.
- Supabase CLI `2.109.0` is installed, authenticated and linked to this repository.
- The first passwordless dump attempt failed while Supabase tried to rotate its temporary `cli_login_postgres` role. PostgreSQL rejected that managed operation with `42501`. No dump file was treated as valid.
- Docker Desktop and standalone `pg_dump`/`psql` are not installed system-wide. To avoid installing a database server or persistent background service, the backup script downloads the official EDB PostgreSQL 17.11 portable binaries once into the Git-ignored `backups/.tools/` directory and uses `pg_dump` directly over TLS.
- Logical backups created at `2026-08-22T03:34:05Z` and `2026-08-22T03:38:40Z` passed structural verification and produced identical hashes: `roles.sql` 189 bytes, `schema.sql` 29,768 bytes, and `data.sql` 58,232 bytes. Their Git-ignored manifests record SHA-256 hashes and successful checks for all expected tables, policies, grants, views, functions, triggers, sanitized roles, and `COPY` data statements.
- The role dump contains no password material. It has no custom role definitions after the official reserved-role filter, which is valid for this project; `RESET ALL;` records successful completion of the sanitized role export.
- A full restore rehearsal remains pending because the portable PostgreSQL server does not reproduce Supabase-managed `auth`, `storage`, Vault, and GraphQL schemas. Production has not been used as a restore target.

## Create and verify a logical backup

Run from PowerShell:

```powershell
.\tools\backup_supabase.ps1
```

The script requests the database password using a hidden prompt, places it only in the child process environment, clears it in `finally`, and produces:

```text
backups/<UTC timestamp>/roles.sql
backups/<UTC timestamp>/schema.sql
backups/<UTC timestamp>/data.sql
backups/<UTC timestamp>/manifest.json
```

The verifier checks non-trivial file sizes, SHA-256 hashes, all expected ARCHEON tables, the three legacy decrypted views, representative functions and triggers, policies, grants, roles and data statements. It never prints row content.

If a password is ever pasted into chat, source code, a screenshot, or a normal shell prompt, rotate it in Supabase before running the backup. A normal PowerShell prompt is not a secure password prompt. Run the script first and type the new password only after `Supabase database password:` appears; no characters or asterisks are displayed while typing.

Store an encrypted copy of the verified directory outside this PC. Database backups include Storage metadata but not the underlying Storage objects; those require a separate object export.

## Restore validation

The preferred validation target is a disposable local Supabase stack or a separate test project, never production. Once Docker Desktop and `psql` are available:

1. Start a clean local Supabase stack with `supabase start`.
2. Restore `roles.sql`, then `schema.sql`, then `data.sql` using the local connection information printed by `supabase status`.
3. Run `tools/verify_supabase_backup.py` against the source dump.
4. Query only catalog counts and object names to confirm tables, policies, functions, views and triggers.
5. Run negative RLS tests as `anon`, User A and User B.
6. Destroy only the disposable local stack after validation.

Do not run `supabase db reset --linked`; that command rebuilds the remote database and is destructive.

## Security migration and rollback order

### Legacy policies

Current state: RLS is enabled, but broad `public` policies use `USING (true)` / `WITH CHECK (true)`. Before replacement, map every policy to its legacy consumer and required operation. The migration must first create owner-scoped policies using `TO authenticated` plus `(select auth.uid()) = user_id`, test them with two users, then revoke broad grants and remove permissive policies in the same transaction.

Rollback: retain the exact pre-change policy definitions in a dedicated rollback SQL file inside `supabase/rollback/`. Re-applying them is an emergency compatibility rollback only and reopens the documented exposure.

### Security-definer views

Current state: `v_conversaciones_decifradas`, `v_mensajes_claros`, and `v_mensajes_decifrados` run with creator privileges and are broadly granted. Audit their complete definitions, owners, dependencies and consumers before changing them.

Expected migration: rebuild compatible views with `security_invoker = true`, restrict grants to the minimum role, and ensure underlying tables have owner RLS. If any privileged decryption operation is truly required, move it to a non-exposed schema, revoke `PUBLIC` execution and perform an explicit authenticated ownership check.

Rollback: preserve the original view definitions and grants in the rollback file. Never restore them without recording that the Security Advisor errors return.

### Functions and triggers

Expected migration: fix mutable `search_path`, revoke unnecessary `PUBLIC`/`anon` execution, preserve trigger behavior and verify encryption round-trips using synthetic data only.

Rollback: restore each original function definition and grant independently. Trigger rollback must use the exact original trigger/function pair.

## Recovery acceptance

A backup is accepted only when all three SQL files and the manifest exist, hashes are recorded, required objects are present, a restore to a disposable target succeeds, negative RLS tests pass, and the encrypted off-device copy is confirmed.
