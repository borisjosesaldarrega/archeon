-- Emergency compatibility rollback for 20260822034748_legacy_security_hardening.
-- Applying this deliberately restores the documented public data exposure.
begin;

drop policy if exists archeon_files_owner_select on storage.objects;
drop policy if exists archeon_files_owner_insert on storage.objects;
drop policy if exists archeon_files_owner_update on storage.objects;
drop policy if exists archeon_files_owner_delete on storage.objects;
create policy "Permitir todo storage" on storage.objects for all to public
using (bucket_id = 'archeon-archivos')
with check (bucket_id = 'archeon-archivos');

alter view public.v_conversaciones_decifradas reset (security_invoker);
alter view public.v_mensajes_claros reset (security_invoker);
alter view public.v_mensajes_decifrados reset (security_invoker);

grant all on table
  public.v_conversaciones_decifradas,
  public.v_mensajes_claros,
  public.v_mensajes_decifrados
to anon, authenticated, service_role;

alter function public.archeon_decrypt(text) reset search_path;
alter function public.archeon_encrypt(text) reset search_path;
alter function public.auto_encrypt_mensajes() reset search_path;
alter function public.auto_encrypt_titulos() reset search_path;
alter function public.cifrar_nuevos_mensajes() reset search_path;
alter function public.es_base64(text) reset search_path;
alter function public.handle_new_user_email() reset search_path;
alter function public.limpiar_chats_antiguos() reset search_path;
alter function public.migrar_datos_cifrados() reset search_path;

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
to public, anon, authenticated, service_role;

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
to anon, authenticated, service_role;

grant all on sequence
  public.chats_mensajes_id_seq,
  public.comandos_id_seq,
  public.gustos_id_seq,
  public.memoria_id_seq,
  public.mensajes_id_seq,
  public.skills_id_seq
to anon, authenticated, service_role;

create policy "Acceso total conversaciones" on public.conversaciones using (true) with check (true);
create policy "Acceso total mensajes" on public.mensajes using (true) with check (true);
create policy "Permitir acceso total a archivos" on public.archivos using (true) with check (true);
create policy "Permitir acceso total a chats" on public.chats_mensajes using (true) with check (true);
create policy "Permitir acceso total a codigos" on public.verification_codes using (true) with check (true);
create policy "Permitir acceso total a comandos" on public.comandos using (true) with check (true);
create policy "Permitir acceso total a gustos" on public.gustos using (true) with check (true);
create policy "Permitir acceso total a memoria" on public.memoria using (true) with check (true);
create policy "Permitir acceso total a sessions" on public.sessions using (true) with check (true);
create policy "Permitir acceso total a skills" on public.skills using (true) with check (true);
create policy "Permitir acceso total a users" on public.users using (true) with check (true);
create policy "Permitir insercion comandos" on public.comandos for insert with check (true);
create policy "Permitir lectura comandos" on public.comandos for select using (true);
create policy "Permitir todo chats" on public.chats_mensajes using (true) with check (true);
create policy "Permitir todo gustos" on public.gustos using (true) with check (true);
create policy "Permitir update comandos" on public.comandos for update using (true) with check (true);

alter default privileges for role postgres in schema public grant all on tables to anon, authenticated;
alter default privileges for role postgres in schema public grant all on sequences to anon, authenticated;
alter default privileges for role postgres in schema public grant all on functions to anon, authenticated;

commit;
