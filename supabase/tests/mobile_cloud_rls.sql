-- Production-safe ownership checks. All synthetic rows are rolled back.
begin;

insert into auth.users (id) values
  ('33333333-3333-4333-8333-333333333333'::uuid),
  ('44444444-4444-4444-8444-444444444444'::uuid);

insert into public.archeon_conversations (id, user_id, title) values
  ('aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa'::uuid, '33333333-3333-4333-8333-333333333333'::uuid, 'A'),
  ('bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb'::uuid, '44444444-4444-4444-8444-444444444444'::uuid, 'B');

do $test$
declare
  affected integer;
begin
  begin
    execute 'set local role anon';
    perform count(*) from public.archeon_conversations;
    execute 'reset role';
    raise exception 'anon SELECT unexpectedly succeeded';
  exception when insufficient_privilege then
    execute 'reset role';
  end;

  perform set_config('request.jwt.claim.sub', '33333333-3333-4333-8333-333333333333', true);
  perform set_config('request.jwt.claims', '{"sub":"33333333-3333-4333-8333-333333333333","role":"authenticated"}', true);
  execute 'set local role authenticated';

  if (select count(*) from public.archeon_conversations) <> 1 then
    raise exception 'conversation owner isolation failed';
  end if;

  update public.archeon_conversations set title = 'compromised'
  where id = 'bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb'::uuid;
  get diagnostics affected = row_count;
  if affected <> 0 then
    raise exception 'user A updated user B conversation';
  end if;

  begin
    insert into public.archeon_messages (
      user_id, conversation_id, role, body, client_message_id
    ) values (
      '33333333-3333-4333-8333-333333333333'::uuid,
      'bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb'::uuid,
      'user', 'cross-owner', gen_random_uuid()
    );
    raise exception 'cross-owner conversation reference succeeded';
  exception when foreign_key_violation then
    null;
  end;

  execute 'reset role';
end
$test$;

rollback;
