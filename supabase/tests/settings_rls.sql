-- Run in a disposable branch/test database. No user content is selected.
begin;
set local role anon;
select set_config('request.jwt.claims', '{}', true);
do $$ begin
  if exists (select 1 from public.account_settings) then
    raise exception 'anon can read account_settings';
  end if;
  if exists (select 1 from public.device_settings) then
    raise exception 'anon can read device_settings';
  end if;
end $$;
rollback;
