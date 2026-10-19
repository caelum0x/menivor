-- Menivor (ReelForge) social-auth profiles.
--
-- One row per Supabase auth user, created automatically on sign-up. Row Level
-- Security ensures a user can only read/update their own profile.
--
-- NOTE: Menivor shares one Supabase project with the rest of the fleet, so all
-- of its objects live in a dedicated `menivor` schema (never `public`) to avoid
-- collisions with the other apps. Apply with `supabase db push`.

create schema if not exists menivor;
grant usage on schema menivor to anon, authenticated, service_role;

create table if not exists menivor.profiles (
  id uuid primary key references auth.users (id) on delete cascade,
  email text,
  full_name text,
  avatar_url text,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

alter table menivor.profiles enable row level security;
grant select, insert, update on menivor.profiles to anon, authenticated;

-- A user can see only their own profile row.
drop policy if exists "profiles_select_own" on menivor.profiles;
create policy "profiles_select_own"
  on menivor.profiles
  for select
  using (auth.uid() = id);

-- A user can insert only their own profile row.
drop policy if exists "profiles_insert_own" on menivor.profiles;
create policy "profiles_insert_own"
  on menivor.profiles
  for insert
  with check (auth.uid() = id);

-- A user can update only their own profile row.
drop policy if exists "profiles_update_own" on menivor.profiles;
create policy "profiles_update_own"
  on menivor.profiles
  for update
  using (auth.uid() = id)
  with check (auth.uid() = id);

-- Keep updated_at fresh on every write.
create or replace function menivor.set_profiles_updated_at()
returns trigger
language plpgsql
as $$
begin
  new.updated_at = now();
  return new;
end;
$$;

drop trigger if exists profiles_set_updated_at on menivor.profiles;
create trigger profiles_set_updated_at
  before update on menivor.profiles
  for each row
  execute function menivor.set_profiles_updated_at();

-- Create a profile row automatically when a new auth user signs up. Pulls the
-- display name / avatar from the OAuth identity metadata when present. The
-- trigger name is app-scoped so it coexists with every other app's auth trigger.
create or replace function menivor.handle_new_user()
returns trigger
language plpgsql
security definer
set search_path = menivor, public
as $$
begin
  insert into menivor.profiles (id, email, full_name, avatar_url)
  values (
    new.id,
    new.email,
    coalesce(
      new.raw_user_meta_data ->> 'full_name',
      new.raw_user_meta_data ->> 'name'
    ),
    new.raw_user_meta_data ->> 'avatar_url'
  )
  on conflict (id) do nothing;
  return new;
end;
$$;

drop trigger if exists on_auth_user_created_menivor on auth.users;
create trigger on_auth_user_created_menivor
  after insert on auth.users
  for each row
  execute function menivor.handle_new_user();
