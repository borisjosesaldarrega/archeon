begin;

create or replace function public.delete_own_account()
returns void
language plpgsql
security definer
set search_path = ''
as $$
declare
  target_user_id uuid := auth.uid();
begin
  if target_user_id is null then
    raise exception 'authentication required' using errcode = '42501';
  end if;

  delete from auth.users where id = target_user_id;
  if not found then
    raise exception 'account not found' using errcode = 'P0002';
  end if;
end;
$$;

alter function public.delete_own_account() owner to postgres;
revoke all on function public.delete_own_account() from public, anon;
grant execute on function public.delete_own_account() to authenticated, service_role;

commit;
