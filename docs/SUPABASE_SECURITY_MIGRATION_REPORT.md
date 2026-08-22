# Supabase security migration report

Project: `rcgipowzivogyqbuwzlv` (`archeon`)

Migration date: 2026-08-21/22. Production migration: `20260822034748_legacy_security_hardening.sql`. Verified recovery point: `backups/20260822T033840Z`; real dumps and manifests remain excluded from Git.

## Vulnerabilities closed

- Sixteen legacy `public` policies allowed unrestricted row access through `USING (true)` and/or `WITH CHECK (true)`.
- Eleven legacy tables containing profiles, password hashes, salts, sessions, verification codes, assistant data and encrypted conversations were granted broad client privileges.
- Three decrypted-content views executed with owner privileges and were broadly selectable by `anon` and `authenticated`.
- Nine public functions inherited mutable `search_path` and implicit client execution rights.
- The `archeon-archivos` bucket used one `PUBLIC ALL` policy for every object in the bucket.
- Default privileges granted future public-schema tables, sequences and functions broadly to API roles.

## Final policies and grants

The text/Firebase-era legacy identifiers have zero verified matches to `auth.users` UUIDs. No ownership relationship was invented. All eleven legacy tables and six sequences now deny `PUBLIC`, `anon`, and `authenticated`; `service_role` retains access for controlled migration and recovery. The sixteen permissive policies were removed without altering rows.

`account_settings` and `device_settings` remain the only client-facing settings tables. They grant `SELECT`, `INSERT`, `UPDATE`, and `DELETE` to `authenticated`, deny `anon`, and enforce separate owner policies using cached `(select auth.uid())` comparisons for every operation.

Storage now has four operation-specific policies for `authenticated`:

- `archeon_files_owner_select`: bucket plus `owner_id` match;
- `archeon_files_owner_insert`: bucket plus first folder equal to the Auth UUID;
- `archeon_files_owner_update`: existing owner, unchanged owner, bucket and Auth UUID folder;
- `archeon_files_owner_delete`: bucket plus `owner_id` match.

The three existing Storage metadata rows had no `owner_id`. They were not deleted or modified; they are quarantined from clients and remain recoverable through the trusted service path.

## Views and functions

`v_conversaciones_decifradas`, `v_mensajes_claros`, and `v_mensajes_decifrados` remain owned by `postgres`, now set `security_invoker=true`, deny client access, and grant only `SELECT` to `service_role`.

All nine audited functions remain `SECURITY INVOKER`; none needed `SECURITY DEFINER`. Each is owned by `postgres`, has `search_path=pg_catalog, public, extensions`, denies execution to `PUBLIC`, `anon`, and `authenticated`, and permits only `service_role`. Client creation in `public` is revoked, so these trusted lookup schemas are not user-writable.

## Validation

The complete migration first ran inside a production transaction ending in `ROLLBACK` and returned `preflight_ok`. The applied migration then returned success.

`supabase/tests/legacy_security_rls.sql` ran with two synthetic users and rolled back all rows. Every assertion passed:

- `anon` could not select or insert private settings;
- User A selected, inserted, updated and deleted its own settings;
- User A could not select, insert, update or delete User B settings;
- authenticated clients could not read quarantined legacy tables or decrypted views;
- no synthetic Auth users remained afterward.

Catalog verification found zero legacy true policies, zero legacy client grants, three security-invoker views, nine pinned invoker functions, and four owner-scoped Storage policies. Supabase Security Advisor reports **0 errors**. Its two warnings are intentional GraphQL discoverability notices for the two authenticated, RLS-protected settings tables.

## Rollback and remaining risks

The emergency rollback is `supabase/rollback/20260822034748_legacy_security_hardening_rollback.sql`. A reversible down/up round trip ran inside one outer transaction and returned `rollback_up_roundtrip_ok`; the outer rollback preserved the secure state. Applying the rollback for real deliberately restores the documented exposure and is allowed only for emergency compatibility recovery.

Remaining risks:

- legacy user data still needs an explicit, verified account-claim migration before client access can return;
- three unowned Storage objects require manual ownership attribution or archival;
- the logical dump includes sensitive Auth and Storage metadata and must remain encrypted, off Git and access-controlled;
- the two GraphQL warnings remain by design while settings sync uses the Data API.
