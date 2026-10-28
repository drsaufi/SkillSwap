-- =============================================================================
-- 20261028220300_create_skills.sql
-- The `skills` table. Offered and wanted skills share one table, separated by
-- `skill_type`. Skills are never deleted - they are deactivated (`is_active`).
--
-- Protection of skills that have been used in exchange requests is added in
-- the create_exchange_requests migration (it needs that table to exist).
-- =============================================================================

create table public.skills (
  id                uuid        primary key default gen_random_uuid(),
  owner_user_id     uuid        not null
                                references public.profiles (user_id) on delete cascade,
  skill_name        text        not null,
  category          text        not null,
  proficiency_level text        not null,
  skill_type        text        not null,
  description       text        not null default '',
  is_active         boolean     not null default true,
  created_at        timestamptz not null default now(),
  updated_at        timestamptz not null default now(),

  constraint skills_name_length
    check (char_length(btrim(skill_name)) between 2 and 80),
  constraint skills_category_allowed
    check (category in (
      'Technology', 'Design', 'Business', 'Languages', 'Music',
      'Arts and Crafts', 'Health and Fitness', 'Cooking', 'Academics', 'Other'
    )),
  constraint skills_level_allowed
    check (proficiency_level in ('beginner', 'intermediate', 'advanced', 'expert')),
  constraint skills_type_allowed
    check (skill_type in ('offered', 'wanted')),
  constraint skills_description_length
    check (char_length(description) <= 500),

  -- Lets exchange_requests prove that a skill belongs to a given member
  -- (composite foreign key: skill id + owner id).
  constraint skills_id_owner_unique unique (id, owner_user_id)
);

comment on table public.skills is
  'Offered and wanted skills. Deactivate (is_active=false) instead of deleting.';

-- A member cannot list the same ACTIVE skill twice for the same type.
-- Deactivated rows are ignored, so a replacement listing is always possible.
create unique index skills_unique_active_per_owner
  on public.skills (owner_user_id, lower(btrim(skill_name)), skill_type)
  where is_active;

create index skills_owner_idx on public.skills (owner_user_id);
-- Supports the Explore page filters.
create index skills_discovery_idx on public.skills (skill_type, is_active, category);

create trigger skills_set_updated_at
  before update on public.skills
  for each row execute function private.set_updated_at();

-- -----------------------------------------------------------------------------
-- Identity fields can never change: id, owner and type.
-- (Column grants below already block this; the trigger is a second safeguard.)
-- -----------------------------------------------------------------------------
create or replace function private.guard_skill_identity()
returns trigger
language plpgsql
set search_path = ''
as $$
begin
  if new.id is distinct from old.id
     or new.owner_user_id is distinct from old.owner_user_id
     or new.skill_type is distinct from old.skill_type then
    raise exception 'skill_identity_immutable: id, owner and type of a skill cannot change'
      using errcode = 'P0001';
  end if;
  return new;
end;
$$;

revoke all on function private.guard_skill_identity() from public, anon, authenticated;

create trigger skills_guard_identity
  before update on public.skills
  for each row execute function private.guard_skill_identity();

-- -----------------------------------------------------------------------------
-- Permissions (least privilege)
-- -----------------------------------------------------------------------------
alter table public.skills enable row level security;

revoke all on table public.skills from public, anon, authenticated;

grant select on table public.skills to authenticated;
-- INSERT: is_active is not listed, so it always starts as true.
grant insert (owner_user_id, skill_name, category, proficiency_level, skill_type, description)
  on table public.skills to authenticated;
-- UPDATE: owner and skill_type are deliberately not listed (immutable).
-- No DELETE grant: skills are deactivated, never deleted.
grant update (skill_name, category, proficiency_level, description, is_active)
  on table public.skills to authenticated;

-- Every signed-in member may read all skills (including inactive ones, which
-- other members need to see in their exchange history). The backend filters
-- on is_active for discovery.
create policy skills_select_authenticated
  on public.skills for select to authenticated
  using (true);

create policy skills_insert_own
  on public.skills for insert to authenticated
  with check (owner_user_id = (select auth.uid()));

create policy skills_update_own
  on public.skills for update to authenticated
  using      (owner_user_id = (select auth.uid()))
  with check (owner_user_id = (select auth.uid()));

