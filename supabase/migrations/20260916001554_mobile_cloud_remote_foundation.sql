-- ARCHEON same-account mobile/cloud foundation.
-- The database carries encrypted/signed envelopes; device pairing secrets never
-- leave the paired clients and are never stored in Postgres.
begin;

create table if not exists public.archeon_devices (
    id uuid primary key default gen_random_uuid(),
    user_id uuid not null references auth.users(id) on delete cascade,
    installation_id text not null check (length(installation_id) between 16 and 128),
    display_name text not null check (length(display_name) between 1 and 120),
    platform text not null check (platform in ('windows', 'android', 'ios')),
    capabilities jsonb not null default '[]'::jsonb check (jsonb_typeof(capabilities) = 'array'),
    public_key text not null check (length(public_key) between 32 and 4096),
    remote_control_enabled boolean not null default false,
    power_commands_enabled boolean not null default false,
    file_access_enabled boolean not null default true,
    paired_at timestamptz,
    last_seen_at timestamptz not null default now(),
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now(),
    unique (user_id, installation_id),
    unique (user_id, id)
);

create table if not exists public.archeon_device_pairings (
    id uuid primary key default gen_random_uuid(),
    user_id uuid not null references auth.users(id) on delete cascade,
    requester_device_id uuid not null,
    target_device_id uuid not null,
    state text not null default 'pending' check (state in ('pending', 'approved', 'rejected', 'revoked', 'expired')),
    requester_proof text not null check (length(requester_proof) between 32 and 4096),
    target_proof text,
    expires_at timestamptz not null,
    approved_at timestamptz,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now(),
    check (requester_device_id <> target_device_id),
    foreign key (user_id, requester_device_id) references public.archeon_devices(user_id, id) on delete cascade,
    foreign key (user_id, target_device_id) references public.archeon_devices(user_id, id) on delete cascade,
    unique (user_id, requester_device_id, target_device_id)
);

create table if not exists public.archeon_remote_commands (
    id uuid primary key default gen_random_uuid(),
    user_id uuid not null references auth.users(id) on delete cascade,
    source_device_id uuid not null,
    target_device_id uuid not null,
    action text not null check (action in ('system.shutdown', 'launcher.open', 'media.play', 'media.pause', 'media.resume', 'media.stop')),
    arguments jsonb not null default '{}'::jsonb check (jsonb_typeof(arguments) = 'object'),
    risk text not null check (risk in ('standard', 'high')),
    state text not null default 'queued' check (state in ('queued', 'acknowledged', 'running', 'succeeded', 'failed', 'rejected', 'expired', 'cancelled')),
    idempotency_key uuid not null,
    nonce text not null check (length(nonce) between 16 and 128),
    signature text not null check (length(signature) between 32 and 4096),
    confirmation_token_hash text,
    expires_at timestamptz not null,
    acknowledged_at timestamptz,
    completed_at timestamptz,
    error_code text,
    result jsonb,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now(),
    check (source_device_id <> target_device_id),
    check (action <> 'system.shutdown' or (risk = 'high' and confirmation_token_hash is not null)),
    foreign key (user_id, source_device_id) references public.archeon_devices(user_id, id) on delete cascade,
    foreign key (user_id, target_device_id) references public.archeon_devices(user_id, id) on delete cascade,
    unique (user_id, idempotency_key)
);

create table if not exists public.archeon_conversations (
    id uuid primary key default gen_random_uuid(),
    user_id uuid not null references auth.users(id) on delete cascade,
    title text not null default 'Nuevo chat' check (length(title) between 1 and 120),
    archived_at timestamptz,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now(),
    unique (user_id, id)
);

create table if not exists public.archeon_messages (
    id uuid primary key default gen_random_uuid(),
    user_id uuid not null references auth.users(id) on delete cascade,
    conversation_id uuid not null,
    source_device_id uuid,
    role text not null check (role in ('user', 'assistant', 'system')),
    body text not null check (length(body) between 1 and 100000),
    client_message_id uuid not null,
    created_at timestamptz not null default now(),
    foreign key (user_id, conversation_id) references public.archeon_conversations(user_id, id) on delete cascade,
    foreign key (user_id, source_device_id) references public.archeon_devices(user_id, id) on delete set null (source_device_id),
    unique (conversation_id, client_message_id)
);

create table if not exists public.archeon_cloud_files (
    id uuid primary key default gen_random_uuid(),
    user_id uuid not null references auth.users(id) on delete cascade,
    uploader_device_id uuid,
    conversation_id uuid,
    message_id uuid references public.archeon_messages(id) on delete set null,
    storage_path text not null check (length(storage_path) between 38 and 1024),
    display_name text not null check (length(display_name) between 1 and 255),
    mime_type text not null check (length(mime_type) between 1 and 255),
    byte_size bigint not null check (byte_size between 0 and 104857600),
    sha256 text not null check (sha256 ~ '^[0-9a-f]{64}$'),
    state text not null default 'available' check (state in ('uploading', 'available', 'quarantined', 'deleted')),
    created_at timestamptz not null default now(),
    deleted_at timestamptz,
    foreign key (user_id, uploader_device_id) references public.archeon_devices(user_id, id) on delete set null (uploader_device_id),
    foreign key (user_id, conversation_id) references public.archeon_conversations(user_id, id) on delete set null (conversation_id),
    unique (user_id, storage_path)
);

create index if not exists archeon_devices_owner_seen_idx on public.archeon_devices (user_id, last_seen_at desc);
create index if not exists archeon_pairings_target_state_idx on public.archeon_device_pairings (target_device_id, state, expires_at);
create index if not exists archeon_commands_target_queue_idx on public.archeon_remote_commands (target_device_id, state, expires_at, created_at);
create index if not exists archeon_conversations_owner_updated_idx on public.archeon_conversations (user_id, updated_at desc);
create index if not exists archeon_messages_conversation_created_idx on public.archeon_messages (conversation_id, created_at);
create index if not exists archeon_cloud_files_owner_created_idx on public.archeon_cloud_files (user_id, created_at desc) where state <> 'deleted';

alter table public.archeon_devices enable row level security;
alter table public.archeon_device_pairings enable row level security;
alter table public.archeon_remote_commands enable row level security;
alter table public.archeon_conversations enable row level security;
alter table public.archeon_messages enable row level security;
alter table public.archeon_cloud_files enable row level security;
alter table public.archeon_devices force row level security;
alter table public.archeon_device_pairings force row level security;
alter table public.archeon_remote_commands force row level security;
alter table public.archeon_conversations force row level security;
alter table public.archeon_messages force row level security;
alter table public.archeon_cloud_files force row level security;

revoke all on table public.archeon_devices, public.archeon_device_pairings,
    public.archeon_remote_commands, public.archeon_conversations,
    public.archeon_messages, public.archeon_cloud_files from anon, authenticated;
grant select, insert, update, delete on table public.archeon_devices,
    public.archeon_device_pairings, public.archeon_remote_commands,
    public.archeon_conversations, public.archeon_messages,
    public.archeon_cloud_files to authenticated;

do $policies$
declare
    table_name text;
begin
    foreach table_name in array array[
        'archeon_devices', 'archeon_device_pairings', 'archeon_remote_commands',
        'archeon_conversations', 'archeon_messages', 'archeon_cloud_files'
    ] loop
        execute format('drop policy if exists %I on public.%I', table_name || '_owner_select', table_name);
        execute format('drop policy if exists %I on public.%I', table_name || '_owner_insert', table_name);
        execute format('drop policy if exists %I on public.%I', table_name || '_owner_update', table_name);
        execute format('drop policy if exists %I on public.%I', table_name || '_owner_delete', table_name);
        execute format('create policy %I on public.%I for select to authenticated using ((select auth.uid()) = user_id)', table_name || '_owner_select', table_name);
        execute format('create policy %I on public.%I for insert to authenticated with check ((select auth.uid()) = user_id)', table_name || '_owner_insert', table_name);
        execute format('create policy %I on public.%I for update to authenticated using ((select auth.uid()) = user_id) with check ((select auth.uid()) = user_id)', table_name || '_owner_update', table_name);
        execute format('create policy %I on public.%I for delete to authenticated using ((select auth.uid()) = user_id)', table_name || '_owner_delete', table_name);
    end loop;
end
$policies$;

insert into storage.buckets (id, name, public, file_size_limit)
values ('archeon-cloud', 'archeon-cloud', false, 104857600)
on conflict (id) do update set public = false, file_size_limit = excluded.file_size_limit;

drop policy if exists archeon_cloud_objects_owner_select on storage.objects;
drop policy if exists archeon_cloud_objects_owner_insert on storage.objects;
drop policy if exists archeon_cloud_objects_owner_update on storage.objects;
drop policy if exists archeon_cloud_objects_owner_delete on storage.objects;
create policy archeon_cloud_objects_owner_select on storage.objects for select to authenticated
using (bucket_id = 'archeon-cloud' and (storage.foldername(name))[1] = (select auth.uid())::text);
create policy archeon_cloud_objects_owner_insert on storage.objects for insert to authenticated
with check (bucket_id = 'archeon-cloud' and (storage.foldername(name))[1] = (select auth.uid())::text);
create policy archeon_cloud_objects_owner_update on storage.objects for update to authenticated
using (bucket_id = 'archeon-cloud' and (storage.foldername(name))[1] = (select auth.uid())::text)
with check (bucket_id = 'archeon-cloud' and (storage.foldername(name))[1] = (select auth.uid())::text);
create policy archeon_cloud_objects_owner_delete on storage.objects for delete to authenticated
using (bucket_id = 'archeon-cloud' and (storage.foldername(name))[1] = (select auth.uid())::text);

do $realtime$
declare
    table_name text;
begin
    foreach table_name in array array[
        'archeon_devices', 'archeon_device_pairings', 'archeon_remote_commands',
        'archeon_conversations', 'archeon_messages', 'archeon_cloud_files'
    ] loop
        if not exists (
            select 1 from pg_publication_tables
            where pubname = 'supabase_realtime' and schemaname = 'public' and tablename = table_name
        ) then
            execute format('alter publication supabase_realtime add table public.%I', table_name);
        end if;
    end loop;
end
$realtime$;

commit;
