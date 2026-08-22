# Supabase legacy security audit

Catalog inspection date: 2026-08-21/22. This document describes metadata only; no application rows were read. The current reconstructed Core contains no references to the legacy tables or decrypted views, so no dependency from the new application was found. Legacy executable behavior still needs compatibility testing before policy replacement.

## Decrypted views

All three views are owned by `postgres`, have no `security_invoker` reloption and therefore execute with creator permissions. `anon`, `authenticated`, `service_role`, and `postgres` currently receive every table-style privilege, although only `SELECT` is meaningful for these views. This is broader than required.

### `public.v_conversaciones_decifradas`

- Query: selects `id`, `user_id`, decrypted `titulo_cifrado`, `ultima_vez`, and `creado` from `public.conversaciones`.
- Dependency: `public.conversaciones`.
- Risk: an anonymous caller can retrieve decrypted conversation titles across users because the view uses the owner's access rather than caller RLS.
- Safe target: `security_invoker = true`, `SELECT` only for `authenticated`, underlying owner RLS, no anonymous grant.

### `public.v_mensajes_claros`

- Query: selects `id`, `chat_id`, `rol`, decrypted `contenido_cifrado`, and `created_at` from `public.mensajes`.
- Dependency: `public.mensajes`.
- Risk: the view omits `user_id`, so it cannot independently express ownership; an anonymous caller can potentially read decrypted messages across all chats.
- Safe target: do not expose this view directly. Prefer the ownership-aware replacement below or an authenticated function in a private schema with an explicit ownership check.

### `public.v_mensajes_decifrados`

- Query: joins `public.mensajes` to `public.conversaciones`, exposes `c.user_id`, and decrypts `contenido_cifrado`.
- Dependencies: `public.mensajes`, `public.conversaciones`.
- Risk: creator permissions bypass ownership checks and expose decrypted message content.
- Safe target: `security_invoker = true`, `SELECT` only for `authenticated`, and owner RLS on both underlying tables.

The reason these views were created with the default definer behavior is not recorded. The likely legacy purpose was convenient client-side decryption, but this is an inference from their names and definitions, not a confirmed design requirement.

## Legacy RLS policy inventory

| Table | Existing intent inferred from names | Current effective access | New application need |
|---|---|---|---|
| `users` | Account/profile storage | Public `ALL`, true/true | Own profile only; password/session secrets must leave exposed schema |
| `sessions` | Custom legacy sessions | Public `ALL`, true/true | None after Supabase Auth migration |
| `verification_codes` | Custom email codes | Public `ALL`, true/true | None after Supabase Auth migration |
| `memoria` | Assistant memory | Public `ALL`, true/true | Authenticated owner CRUD |
| `skills` | User-defined skills | Public `ALL`, true/true | Authenticated owner CRUD |
| `comandos` | Command history/queue | Multiple overlapping public policies | Authenticated owner CRUD; service workflow to be defined separately |
| `gustos` | User preferences | Duplicate public `ALL` policies | Authenticated owner CRUD |
| `chats_mensajes` | Chat messages | Duplicate public `ALL` policies | Authenticated owner CRUD |
| `archivos` | File metadata | Public `ALL`, true/true | Authenticated owner CRUD |
| `conversaciones` | Encrypted conversations | Public `ALL`, true/true | Authenticated owner CRUD |
| `mensajes` | Encrypted messages | Public `ALL`, true/true | Access through owned conversation |
| `storage.objects` | `archeon-archivos` bucket | Public `ALL` for every object in bucket | Owner-prefixed object access only |

The old policy names establish that broad access was intentional during development, but they do not prove which released client depended on it. No policy will be replaced until a verified logical backup exists and the v9.8 compatibility path is mapped.

## Function and grant concerns

Nine public functions are executable by both `anon` and `authenticated`, including encryption/decryption, migration and cleanup functions. Security Advisor also reports mutable `search_path`. Before changing them:

1. Record exact definitions in the verified schema dump without copying secrets into Git.
2. Determine whether encryption key material is embedded, read from Vault, or otherwise configured.
3. Revoke client execution from trigger-only and administrative functions.
4. Set an explicit safe `search_path` and schema-qualify referenced objects.
5. Validate encryption/decryption round-trips using synthetic rows only.

## Planned migration and rollback gate

The security migration must be transactional and separate from Auth integration. Its rollback file will be generated from the verified pre-change `schema.sql`, stored without real data, and reviewed before production execution. The rollback restores exact policies/views/functions/grants, but using it deliberately reopens the risks documented here and must create a security event.
