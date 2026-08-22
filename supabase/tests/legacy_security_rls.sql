-- Production-safe RLS contract test. All synthetic rows are rolled back.
begin;

insert into auth.users (id) values
  ('11111111-1111-4111-8111-111111111111'::uuid),
  ('22222222-2222-4222-8222-222222222222'::uuid);

insert into public.account_settings (user_id, settings) values
  ('11111111-1111-4111-8111-111111111111'::uuid, '{"owner":"a"}'::jsonb),
  ('22222222-2222-4222-8222-222222222222'::uuid, '{"owner":"b"}'::jsonb);

do $test$
declare
  affected integer;
begin
  -- anon must be denied by grants, before RLS can leak row existence.
  begin
    execute 'set local role anon';
    perform count(*) from public.account_settings;
    execute 'reset role';
    raise exception 'anon SELECT unexpectedly succeeded';
  exception when insufficient_privilege then
    execute 'reset role';
  end;

  begin
    execute 'set local role anon';
    insert into public.account_settings (user_id, settings)
    values ('11111111-1111-4111-8111-111111111111'::uuid, '{}'::jsonb);
    execute 'reset role';
    raise exception 'anon INSERT unexpectedly succeeded';
  exception when insufficient_privilege then
    execute 'reset role';
  end;

  -- User A receives both current JWT representations for compatibility.
  perform set_config('request.jwt.claim.sub', '11111111-1111-4111-8111-111111111111', true);
  perform set_config(
    'request.jwt.claims',
    '{"sub":"11111111-1111-4111-8111-111111111111","role":"authenticated"}',
    true
  );
  execute 'set local role authenticated';

  if (select count(*) from public.account_settings) <> 1 then
    raise exception 'User A SELECT isolation failed';
  end if;

  if exists (
    select 1 from public.account_settings
    where user_id = '22222222-2222-4222-8222-222222222222'::uuid
  ) then
    raise exception 'User A can SELECT User B settings';
  end if;

  update public.account_settings
  set settings = '{"owner":"a","updated":true}'::jsonb
  where user_id = '11111111-1111-4111-8111-111111111111'::uuid;
  get diagnostics affected = row_count;
  if affected <> 1 then
    raise exception 'User A UPDATE own row failed';
  end if;

  update public.account_settings
  set settings = '{"compromised":true}'::jsonb
  where user_id = '22222222-2222-4222-8222-222222222222'::uuid;
  get diagnostics affected = row_count;
  if affected <> 0 then
    raise exception 'User A can UPDATE User B settings';
  end if;

  insert into public.device_settings (user_id, device_id, settings)
  values (
    '11111111-1111-4111-8111-111111111111'::uuid,
    'rls-test-device-a',
    '{}'::jsonb
  );

  begin
    insert into public.device_settings (user_id, device_id, settings)
    values (
      '22222222-2222-4222-8222-222222222222'::uuid,
      'rls-test-device-b',
      '{}'::jsonb
    );
    raise exception 'User A can INSERT a row for User B';
  exception when insufficient_privilege then
    null;
  end;

  delete from public.account_settings
  where user_id = '22222222-2222-4222-8222-222222222222'::uuid;
  get diagnostics affected = row_count;
  if affected <> 0 then
    raise exception 'User A can DELETE User B settings';
  end if;

  delete from public.device_settings
  where user_id = '11111111-1111-4111-8111-111111111111'::uuid;
  get diagnostics affected = row_count;
  if affected <> 1 then
    raise exception 'User A DELETE own row failed';
  end if;

  begin
    perform count(*) from public.users;
    raise exception 'authenticated can SELECT quarantined legacy users';
  exception when insufficient_privilege then
    null;
  end;

  begin
    perform count(*) from public.v_mensajes_decifrados;
    raise exception 'authenticated can SELECT a quarantined decrypted view';
  exception when insufficient_privilege then
    null;
  end;

  execute 'reset role';
end
$test$;

rollback;

select jsonb_build_object(
  'anon_select_denied', true,
  'anon_insert_denied', true,
  'user_a_select_own', true,
  'user_a_select_b_denied', true,
  'user_a_update_own', true,
  'user_a_update_b_denied', true,
  'user_a_insert_own', true,
  'user_a_insert_b_denied', true,
  'user_a_delete_own', true,
  'user_a_delete_b_denied', true,
  'legacy_tables_quarantined', true,
  'decrypted_views_quarantined', true
) as rls_tests;
