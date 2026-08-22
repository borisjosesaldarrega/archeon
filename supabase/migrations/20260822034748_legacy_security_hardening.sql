begin;

set local lock_timeout = '5s';
set local statement_timeout = '60s';

-- Prevent future objects from inheriting the legacy public API exposure.
revoke create on schema public from public, anon, authenticated;
alter default privileges for role postgres in schema public revoke all on tables from anon, authenticated;
alter default privileges for role postgres in schema public revoke all on sequences from anon, authenticated;
alter default privileges for role postgres in schema public revoke all on functions from anon, authenticated;

-- The legacy identity is text/Firebase-era data and has no verified mapping to
-- auth.users UUIDs. Keep it available to the trusted service role only until an
-- explicit account migration claims each row.
drop policy if exists "Acceso total conversaciones" on public.conversaciones;
drop policy if exists "Acceso total mensajes" on public.mensajes;
drop policy if exists "Permitir acceso total a archivos" on public.archivos;
drop policy if exists "Permitir acceso total a chats" on public.chats_mensajes;
drop policy if exists "Permitir acceso total a codigos" on public.verification_codes;
drop policy if exists "Permitir acceso total a comandos" on public.comandos;
drop policy if exists "Permitir acceso total a gustos" on public.gustos;
drop policy if exists "Permitir acceso total a memoria" on public.memoria;
drop policy if exists "Permitir acceso total a sessions" on public.sessions;
drop policy if exists "Permitir acceso total a skills" on public.skills;
drop policy if exists "Permitir acceso total a users" on public.users;
drop policy if exists "Permitir insercion comandos" on public.comandos;
drop policy if exists "Permitir lectura comandos" on public.comandos;
drop policy if exists "Permitir todo chats" on public.chats_mensajes;
drop policy if exists "Permitir todo gustos" on public.gustos;
drop policy if exists "Permitir update comandos" on public.comandos;

revoke all on table
  public.users,
  public.sessions,
  public.verification_codes,
  public.memoria,
  public.skills,
  public.comandos,
  public.gustos,
  public.chats_mensajes,
  public.archivos,
  public.conversaciones,
  public.mensajes
from public, anon, authenticated;

grant all on table
  public.users,
  public.sessions,
  public.verification_codes,
  public.memoria,
  public.skills,
  public.comandos,
  public.gustos,
  public.chats_mensajes,
  public.archivos,
  public.conversaciones,
  public.mensajes
to service_role;

revoke all on sequence
  public.chats_mensajes_id_seq,
  public.comandos_id_seq,
  public.gustos_id_seq,
  public.memoria_id_seq,
  public.mensajes_id_seq,
  public.skills_id_seq
from public, anon, authenticated;

grant all on sequence
  public.chats_mensajes_id_seq,
  public.comandos_id_seq,
  public.gustos_id_seq,
  public.memoria_id_seq,
  public.mensajes_id_seq,
  public.skills_id_seq
to service_role;

-- These UUID-backed settings tables are the only current client-facing data.
revoke all on table public.account_settings, public.device_settings from public, anon;
grant select, insert, update, delete on table public.account_settings, public.device_settings to authenticated;
grant all on table public.account_settings, public.device_settings to service_role;

-- Postgres views use owner privileges by default. Make RLS semantics explicit,
-- then keep decrypted legacy content off the client API until ownership mapping.
alter view public.v_conversaciones_decifradas set (security_invoker = true);
alter view public.v_mensajes_claros set (security_invoker = true);
alter view public.v_mensajes_decifrados set (security_invoker = true);

revoke all on table
  public.v_conversaciones_decifradas,
  public.v_mensajes_claros,
  public.v_mensajes_decifrados
from public, anon, authenticated;

grant select on table
  public.v_conversaciones_decifradas,
  public.v_mensajes_claros,
  public.v_mensajes_decifrados
to service_role;

-- All functions are invoker functions. Pin their lookup path and remove the
-- implicit PUBLIC execute grant. Trigger/admin/decryption functions remain
-- available only to the trusted service role during legacy quarantine.
alter function public.archeon_decrypt(text) set search_path = pg_catalog, public, extensions;
alter function public.archeon_encrypt(text) set search_path = pg_catalog, public, extensions;
alter function public.auto_encrypt_mensajes() set search_path = pg_catalog, public, extensions;
alter function public.auto_encrypt_titulos() set search_path = pg_catalog, public, extensions;
alter function public.cifrar_nuevos_mensajes() set search_path = pg_catalog, public, extensions;
alter function public.es_base64(text) set search_path = pg_catalog, public, extensions;
alter function public.handle_new_user_email() set search_path = pg_catalog, public, extensions;
alter function public.limpiar_chats_antiguos() set search_path = pg_catalog, public, extensions;
alter function public.migrar_datos_cifrados() set search_path = pg_catalog, public, extensions;

revoke execute on function
  public.archeon_decrypt(text),
  public.archeon_encrypt(text),
  public.auto_encrypt_mensajes(),
  public.auto_encrypt_titulos(),
  public.cifrar_nuevos_mensajes(),
  public.es_base64(text),
  public.handle_new_user_email(),
  public.limpiar_chats_antiguos(),
  public.migrar_datos_cifrados()
from public, anon, authenticated;

grant execute on function
  public.archeon_decrypt(text),
  public.archeon_encrypt(text),
  public.auto_encrypt_mensajes(),
  public.auto_encrypt_titulos(),
  public.cifrar_nuevos_mensajes(),
  public.es_base64(text),
  public.handle_new_user_email(),
  public.limpiar_chats_antiguos(),
  public.migrar_datos_cifrados()
to service_role;

-- Replace the bucket-wide PUBLIC policy. Existing unowned rows are preserved
-- but intentionally quarantined; new objects must live below <auth.uid()>/.
drop policy if exists "Permitir todo storage" on storage.objects;

create policy archeon_files_owner_select
on storage.objects for select to authenticated
using (
  bucket_id = 'archeon-archivos'
  and owner_id = (select auth.uid()::text)
);

create policy archeon_files_owner_insert
on storage.objects for insert to authenticated
with check (
  bucket_id = 'archeon-archivos'
  and (storage.foldername(name))[1] = (select auth.uid()::text)
);

create policy archeon_files_owner_update
on storage.objects for update to authenticated
using (
  bucket_id = 'archeon-archivos'
  and owner_id = (select auth.uid()::text)
)
with check (
  bucket_id = 'archeon-archivos'
  and owner_id = (select auth.uid()::text)
  and (storage.foldername(name))[1] = (select auth.uid()::text)
);

create policy archeon_files_owner_delete
on storage.objects for delete to authenticated
using (
  bucket_id = 'archeon-archivos'
  and owner_id = (select auth.uid()::text)
);

commit;
