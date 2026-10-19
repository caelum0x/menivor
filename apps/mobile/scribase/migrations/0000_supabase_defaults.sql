-- Scribase: the grants hosted Supabase sets up implicitly.
-- A fresh Scribase project gives anon/authenticated/service_role nothing on new
-- objects in public; Supabase-style migrations assume they get table/function
-- privileges by default and rely on RLS. Apply this before the app's tables.
grant usage on schema public to anon, authenticated, service_role;
alter default privileges in schema public grant all on tables to anon, authenticated, service_role;
alter default privileges in schema public grant all on sequences to anon, authenticated, service_role;
alter default privileges in schema public grant execute on functions to anon, authenticated, service_role;
