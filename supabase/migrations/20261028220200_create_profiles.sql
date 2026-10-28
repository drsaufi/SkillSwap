-- =============================================================================
-- 20261028220200_create_profiles.sql
-- The `profiles` table (one row per Supabase Auth account) plus:
--   * RLS policies and least-privilege grants
--   * automatic profile creation when a user registers
--   * a one-off backfill for accounts that already exist
--
-- Passwords and emails stay in auth.users. They are never copied here.
-- =============================================================================

-- Helper for the `interests` column: at most 10 tags, each 1-40 characters.
-- (A CHECK constraint cannot loop over array items itself, so it calls this.)
create or replace function private.valid_interests(p_interests text[])
returns boolean
language sql
immutable
set search_path = ''
as $$
  select p_interests is not null
     and coalesce(cardinality(p_interests), 0) <= 10
     and not exists (
       select 1
       from unnest(p_interests) as t(item)
       where item is null
          or char_length(btrim(item)) < 1
          or char_length(item) > 40
     );
$$;

revoke all on function private.valid_interests(text[]) from public, anon;
-- Needed because the CHECK constraint runs with the caller's privileges.
grant execute on function private.valid_interests(text[]) to authenticated;

create table public.profiles (
  user_id              uuid        primary key
                                   references auth.users (id) on delete cascade,
  display_name         text        not null,
  bio                  text        not null default '',
  interests            text[]      not null default '{}',
  learning_preferences text        not null default '',
  availability         text        not null default '',
  created_at           timestamptz not null default now(),
  updated_at           timestamptz not null default now(),

  constraint profiles_display_name_length
    check (char_length(btrim(display_name)) between 2 and 60),
  constraint profiles_bio_length
    check (char_length(bio) <= 500),
  constraint profiles_interests_valid
    check (private.valid_interests(interests)),
  constraint profiles_learning_preferences_length
    check (char_length(learning_preferences) <= 300),
  constraint profiles_availability_length
    check (char_length(availability) <= 300)
);

comment on table public.profiles is
  'Public member profile. 1:1 with auth.users. Contains no credentials or email.';

create trigger profiles_set_updated_at
  before update on public.profiles
  for each row execute function private.set_updated_at();

-- -----------------------------------------------------------------------------
-- Permissions (least privilege)
-- -----------------------------------------------------------------------------
alter table public.profiles enable row level security;

revoke all on table public.profiles from public, anon, authenticated;

grant select on table public.profiles to authenticated;
-- Members may edit only these columns. user_id / created_at stay fixed.
-- There is no INSERT grant: profiles are created by the sign-up trigger below.
-- There is no DELETE grant: account deletion is not part of the MVP.
grant update (display_name, bio, interests, learning_preferences, availability)
  on table public.profiles to authenticated;

create policy profiles_select_authenticated
  on public.profiles for select to authenticated
  using (true);

create policy profiles_update_own
  on public.profiles for update to authenticated
  using      (user_id = (select auth.uid()))
  with check (user_id = (select auth.uid()));

-- -----------------------------------------------------------------------------
-- Automatic profile creation on registration
--
-- SECURITY DEFINER because the new user has no rights yet (and no INSERT grant).
-- The display name comes from the sign-up metadata, which is untrusted input,
-- so it is sanitised. If it is missing or invalid the neutral fallback
-- 'New member' is used. The email address is NEVER used for the name.
-- The sanitised value always satisfies the table's NOT NULL and 2-60 length
-- rules, so a bad name cannot make registration fail.
-- -----------------------------------------------------------------------------
create or replace function private.handle_new_user()
returns trigger
language plpgsql
security definer
set search_path = ''
as $$
declare
  v_name text;
begin
  -- Only accept the value if it really is a JSON string.
  if jsonb_typeof(new.raw_user_meta_data -> 'display_name') = 'string' then
    v_name := btrim(new.raw_user_meta_data ->> 'display_name', E' \t\r\n');
  end if;

  if v_name is null
     or char_length(v_name) < 2
     or char_length(v_name) > 60 then
    v_name := 'New member';
  end if;

  insert into public.profiles (user_id, display_name)
  values (new.id, v_name)
  on conflict (user_id) do nothing;

  return new;
end;
$$;

revoke all on function private.handle_new_user() from public, anon, authenticated;

create trigger on_auth_user_created
  after insert on auth.users
  for each row execute function private.handle_new_user();

-- -----------------------------------------------------------------------------
-- One-off backfill: any account created before this trigger existed (for
-- example Phase 2 test accounts) gets a neutral profile so no user is left
-- without one. Idempotent: existing profiles are left untouched.
-- -----------------------------------------------------------------------------
insert into public.profiles (user_id, display_name)
select u.id, 'New member'
from auth.users as u
on conflict (user_id) do nothing;

