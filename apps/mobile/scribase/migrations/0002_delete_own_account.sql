-- Sign-in identity deletion (App Store guideline 5.1.1(v)).
-- NEW (the shared project had no deletion function for Menivor): the Menivor
-- account itself is erased by the Menivor API (POST /me/privacy erase); this
-- removes the Apple/Google sign-in identity and its profile from Menivor's
-- Scribase project afterwards, so nothing personal is left here either.

create or replace function public.delete_own_account()
returns text
language plpgsql
security definer
set search_path = ''
as $$
declare
  uid uuid := auth.uid();
begin
  if uid is null then
    raise exception 'not authenticated' using errcode = '28000';
  end if;
  delete from public.profiles where id = uid;
  delete from auth.users where id = uid;
  return 'account_deleted';
end;
$$;

revoke all on function public.delete_own_account() from public, anon;
grant execute on function public.delete_own_account() to authenticated;
