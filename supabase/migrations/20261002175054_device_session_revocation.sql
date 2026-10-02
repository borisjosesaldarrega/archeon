begin;

alter table public.archeon_devices
  add column if not exists auth_session_id uuid,
  add column if not exists session_revoked_at timestamptz;

create index if not exists archeon_devices_owner_auth_session_idx
  on public.archeon_devices (user_id, auth_session_id)
  where auth_session_id is not null;

create schema if not exists private;

create or replace function private.archeon_current_session_active()
returns boolean
language sql
stable
security definer
set search_path = pg_catalog, public
as $$
  select coalesce(
    nullif(auth.jwt() ->> 'session_id', '') is not null
    and not exists (
      select 1
      from public.archeon_devices d
      where d.user_id = (select auth.uid())
        and d.auth_session_id = (auth.jwt() ->> 'session_id')::uuid
        and d.session_revoked_at is not null
    ),
    false
  );
$$;

revoke all on function private.archeon_current_session_active() from public, anon;
grant usage on schema private to authenticated;
grant execute on function private.archeon_current_session_active() to authenticated;

do $policies$
declare
  table_name text;
begin
  foreach table_name in array array[
    'account_settings', 'device_settings',
    'archeon_devices', 'archeon_device_pairings', 'archeon_remote_commands',
    'archeon_conversations', 'archeon_messages', 'archeon_cloud_files'
  ] loop
    execute format('drop policy if exists %I on public.%I', table_name || '_owner_select', table_name);
    execute format('drop policy if exists %I on public.%I', table_name || '_owner_insert', table_name);
    execute format('drop policy if exists %I on public.%I', table_name || '_owner_update', table_name);
    execute format('drop policy if exists %I on public.%I', table_name || '_owner_delete', table_name);
    execute format(
      'create policy %I on public.%I for select to authenticated using ((select auth.uid()) = user_id and (select private.archeon_current_session_active()))',
      table_name || '_owner_select', table_name
    );
    execute format(
      'create policy %I on public.%I for insert to authenticated with check ((select auth.uid()) = user_id and (select private.archeon_current_session_active()))',
      table_name || '_owner_insert', table_name
    );
    execute format(
      'create policy %I on public.%I for update to authenticated using ((select auth.uid()) = user_id and (select private.archeon_current_session_active())) with check ((select auth.uid()) = user_id and (select private.archeon_current_session_active()))',
      table_name || '_owner_update', table_name
    );
    execute format(
      'create policy %I on public.%I for delete to authenticated using ((select auth.uid()) = user_id and (select private.archeon_current_session_active()))',
      table_name || '_owner_delete', table_name
    );
  end loop;
end
$policies$;

drop policy if exists archeon_cloud_objects_owner_select on storage.objects;
drop policy if exists archeon_cloud_objects_owner_insert on storage.objects;
drop policy if exists archeon_cloud_objects_owner_update on storage.objects;
drop policy if exists archeon_cloud_objects_owner_delete on storage.objects;
create policy archeon_cloud_objects_owner_select on storage.objects for select to authenticated
using (
  bucket_id = 'archeon-cloud'
  and (storage.foldername(name))[1] = (select auth.uid())::text
  and (select private.archeon_current_session_active())
);
create policy archeon_cloud_objects_owner_insert on storage.objects for insert to authenticated
with check (
  bucket_id = 'archeon-cloud'
  and (storage.foldername(name))[1] = (select auth.uid())::text
  and (select private.archeon_current_session_active())
);
create policy archeon_cloud_objects_owner_update on storage.objects for update to authenticated
using (
  bucket_id = 'archeon-cloud'
  and (storage.foldername(name))[1] = (select auth.uid())::text
  and (select private.archeon_current_session_active())
)
with check (
  bucket_id = 'archeon-cloud'
  and (storage.foldername(name))[1] = (select auth.uid())::text
  and (select private.archeon_current_session_active())
);
create policy archeon_cloud_objects_owner_delete on storage.objects for delete to authenticated
using (
  bucket_id = 'archeon-cloud'
  and (storage.foldername(name))[1] = (select auth.uid())::text
  and (select private.archeon_current_session_active())
);

comment on column public.archeon_devices.auth_session_id is
  'Supabase JWT session_id currently authorized for this installation.';
comment on column public.archeon_devices.session_revoked_at is
  'When set, ARCHEON rejects this session without affecting other devices.';

commit;
