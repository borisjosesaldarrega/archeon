-- Signup policy is enforced inside Supabase Auth, not only in the desktop UI.
create or replace function public.archeon_canonical_email(value text)
returns text
language sql
immutable
strict
set search_path = ''
as $$
  select case
    when lower(split_part(value, '@', 2)) in ('gmail.com', 'googlemail.com') then
      replace(split_part(split_part(lower(value), '@', 1), '+', 1), '.', '') || '@gmail.com'
    else lower(value)
  end
$$;

create or replace function public.archeon_before_user_created(event jsonb)
returns jsonb
language plpgsql
set search_path = ''
as $$
declare
  raw_email text := nullif(trim(event->'user'->>'email'), '');
  candidate text;
  domain text;
begin
  -- The hook also runs for phone/OAuth paths; this policy governs email signup.
  if raw_email is null then
    return '{}'::jsonb;
  end if;
  candidate := public.archeon_canonical_email(raw_email);
  domain := split_part(candidate, '@', 2);
  -- Serialize equivalent aliases so concurrent signups cannot both pass the check.
  perform pg_advisory_xact_lock(hashtextextended(candidate, 0));

  if exists (
    select 1
    from unnest(array[
      '10minutemail.com','dispostable.com','dropmail.me','emailondeck.com',
      'fakeinbox.com','guerrillamail.com','maildrop.cc','mailinator.com',
      'moakt.com','sharklasers.com','temp-mail.org','tempmail.com',
      'throwawaymail.com','yopmail.com'
    ]) as blocked(value)
    where domain = blocked.value or domain like '%.' || blocked.value
  ) then
    return jsonb_build_object(
      'error', jsonb_build_object(
        'http_code', 403,
        'message', 'disposable_email_not_allowed'
      )
    );
  end if;

  if exists (
    select 1 from auth.users as existing
    where public.archeon_canonical_email(existing.email) = candidate
  ) then
    return jsonb_build_object(
      'error', jsonb_build_object(
        'http_code', 409,
        'message', 'account_exists'
      )
    );
  end if;

  return '{}'::jsonb;
end
$$;

grant execute on function public.archeon_canonical_email(text) to supabase_auth_admin;
grant execute on function public.archeon_before_user_created(jsonb) to supabase_auth_admin;
grant usage on schema public to supabase_auth_admin;
revoke execute on function public.archeon_canonical_email(text) from anon, authenticated, public;
revoke execute on function public.archeon_before_user_created(jsonb) from anon, authenticated, public;
