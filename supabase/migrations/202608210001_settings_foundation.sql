-- ARCHEON settings foundation. Additive and transactional; preserves legacy data.
begin;

create table if not exists public.account_settings (
    user_id uuid primary key references auth.users(id) on delete cascade,
    settings jsonb not null default '{}'::jsonb,
    version bigint not null default 1 check (version > 0),
    updated_at timestamptz not null default now()
);

create table if not exists public.device_settings (
    id uuid primary key default gen_random_uuid(),
    user_id uuid not null references auth.users(id) on delete cascade,
    device_id text not null check (length(device_id) between 1 and 128),
    device_name text not null default 'Windows device' check (length(device_name) between 1 and 120),
    settings jsonb not null default '{}'::jsonb,
    version bigint not null default 1 check (version > 0),
    updated_at timestamptz not null default now(),
    unique (user_id, device_id)
);

create index if not exists device_settings_user_updated_idx
    on public.device_settings (user_id, updated_at desc);

alter table public.account_settings enable row level security;
alter table public.account_settings force row level security;
alter table public.device_settings enable row level security;
alter table public.device_settings force row level security;

revoke all on table public.account_settings from anon, authenticated;
revoke all on table public.device_settings from anon, authenticated;
grant select, insert, update, delete on table public.account_settings to authenticated;
grant select, insert, update, delete on table public.device_settings to authenticated;

drop policy if exists account_settings_owner_select on public.account_settings;
drop policy if exists account_settings_owner_insert on public.account_settings;
drop policy if exists account_settings_owner_update on public.account_settings;
drop policy if exists account_settings_owner_delete on public.account_settings;
create policy account_settings_owner_select on public.account_settings for select to authenticated using ((select auth.uid()) = user_id);
create policy account_settings_owner_insert on public.account_settings for insert to authenticated with check ((select auth.uid()) = user_id);
create policy account_settings_owner_update on public.account_settings for update to authenticated using ((select auth.uid()) = user_id) with check ((select auth.uid()) = user_id);
create policy account_settings_owner_delete on public.account_settings for delete to authenticated using ((select auth.uid()) = user_id);

drop policy if exists device_settings_owner_select on public.device_settings;
drop policy if exists device_settings_owner_insert on public.device_settings;
drop policy if exists device_settings_owner_update on public.device_settings;
drop policy if exists device_settings_owner_delete on public.device_settings;
create policy device_settings_owner_select on public.device_settings for select to authenticated using ((select auth.uid()) = user_id);
create policy device_settings_owner_insert on public.device_settings for insert to authenticated with check ((select auth.uid()) = user_id);
create policy device_settings_owner_update on public.device_settings for update to authenticated using ((select auth.uid()) = user_id) with check ((select auth.uid()) = user_id);
create policy device_settings_owner_delete on public.device_settings for delete to authenticated using ((select auth.uid()) = user_id);

commit;
