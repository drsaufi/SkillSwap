-- =============================================================================
-- 20261028220400_create_exchange_requests.sql
-- The `exchange_requests` table, its status rules, the checks that run when a
-- request is created, and the protection for skills that have been used.
--
-- Statuses:   pending -> accepted | declined | cancelled
--             accepted -> cancelled | completed
--             declined / cancelled / completed are final.
-- Members may only INSERT a request. Every status change goes through the
-- workflow functions created in the private_workflow_functions and public_wrappers migrations.
-- =============================================================================

create table public.exchange_requests (
  id                uuid        primary key default gen_random_uuid(),
  requester_user_id uuid        not null
                                references public.profiles (user_id) on delete restrict,
  receiver_user_id  uuid        not null
                                references public.profiles (user_id) on delete restrict,
  offered_skill_id  uuid        not null,   -- requester's skill
  wanted_skill_id   uuid        not null,   -- receiver's skill the requester wants
  message           text        not null,
  status            text        not null default 'pending',
  proposed_datetime timestamptz not null,   -- stored in UTC
  format            text        not null,
  created_at        timestamptz not null default now(),
  updated_at        timestamptz not null default now(),

  constraint exchange_requests_members_differ
    check (requester_user_id <> receiver_user_id),
  constraint exchange_requests_status_allowed
    check (status in ('pending', 'accepted', 'declined', 'cancelled', 'completed')),
  constraint exchange_requests_format_allowed
    check (format in ('online', 'in_person')),
  constraint exchange_requests_message_length
    check (char_length(btrim(message)) between 1 and 500),

  -- Ownership is proven by the database itself: the offered skill must belong
  -- to the requester and the wanted skill to the receiver.
  -- RESTRICT: a skill used by a request can never be deleted.
  constraint exchange_requests_offered_skill_fk
    foreign key (offered_skill_id, requester_user_id)
    references public.skills (id, owner_user_id) on delete restrict,
  constraint exchange_requests_wanted_skill_fk
    foreign key (wanted_skill_id, receiver_user_id)
    references public.skills (id, owner_user_id) on delete restrict
);

comment on table public.exchange_requests is
  'Skill exchange requests. Status changes only via workflow functions.';

create index exchange_requests_requester_idx on public.exchange_requests (requester_user_id, status);
create index exchange_requests_receiver_idx  on public.exchange_requests (receiver_user_id, status);
create index exchange_requests_offered_skill_idx on public.exchange_requests (offered_skill_id);
create index exchange_requests_wanted_skill_idx  on public.exchange_requests (wanted_skill_id);

create trigger exchange_requests_set_updated_at
  before update on public.exchange_requests
  for each row execute function private.set_updated_at();

-- -----------------------------------------------------------------------------
-- Checks when a request is CREATED.
-- SECURITY DEFINER so it can read any skill row regardless of RLS. It takes a
-- row lock (FOR SHARE) on both skills so a skill cannot be edited or changed
-- in the middle of request creation.
-- -----------------------------------------------------------------------------
create or replace function private.validate_exchange_request_insert()
returns trigger
language plpgsql
security definer
set search_path = ''
as $$
declare
  v_skill record;
begin
  if new.status <> 'pending' then
    raise exception 'invalid_status: a new request must start as pending'
      using errcode = 'P0001';
  end if;

  if new.proposed_datetime <= now() then
    raise exception 'proposed_time_in_past: the proposed date and time must be in the future'
      using errcode = '22023';
  end if;

  -- Requester's offered skill: must exist, be theirs, be 'offered' and active.
  select s.owner_user_id, s.skill_type, s.is_active
    into v_skill
    from public.skills s
   where s.id = new.offered_skill_id
     for share;
  if not found
     or v_skill.owner_user_id <> new.requester_user_id
     or v_skill.skill_type <> 'offered'
     or not v_skill.is_active then
    raise exception 'invalid_offered_skill: must be an active offered skill owned by the requester'
      using errcode = 'P0001';
  end if;

  -- Receiver's skill: must exist, be theirs, be 'offered' and active.
  select s.owner_user_id, s.skill_type, s.is_active
    into v_skill
    from public.skills s
   where s.id = new.wanted_skill_id
     for share;
  if not found
     or v_skill.owner_user_id <> new.receiver_user_id
     or v_skill.skill_type <> 'offered'
     or not v_skill.is_active then
    raise exception 'invalid_wanted_skill: must be an active offered skill owned by the receiver'
      using errcode = 'P0001';
  end if;

  return new;
end;
$$;

revoke all on function private.validate_exchange_request_insert() from public, anon, authenticated;

create trigger exchange_requests_validate_insert
  before insert on public.exchange_requests
  for each row execute function private.validate_exchange_request_insert();

-- -----------------------------------------------------------------------------
-- Status-transition guard on UPDATE (second line of defence: members have no
-- UPDATE right at all, so this only ever sees the workflow functions).
--   * freezes every column except status / updated_at
--   * allows only the permitted transitions
-- -----------------------------------------------------------------------------
create or replace function private.guard_exchange_request_update()
returns trigger
language plpgsql
set search_path = ''
as $$
begin
  if new.id                is distinct from old.id
     or new.requester_user_id is distinct from old.requester_user_id
     or new.receiver_user_id  is distinct from old.receiver_user_id
     or new.offered_skill_id  is distinct from old.offered_skill_id
     or new.wanted_skill_id   is distinct from old.wanted_skill_id
     or new.message           is distinct from old.message
     or new.proposed_datetime is distinct from old.proposed_datetime
     or new.format            is distinct from old.format
     or new.created_at        is distinct from old.created_at then
    raise exception 'request_fields_immutable: only the status of a request can change'
      using errcode = 'P0001';
  end if;

  if new.status is distinct from old.status then
    if not (
      (old.status = 'pending'  and new.status in ('accepted', 'declined', 'cancelled'))
      or
      (old.status = 'accepted' and new.status in ('cancelled', 'completed'))
    ) then
      raise exception 'invalid_transition: cannot change status from % to %', old.status, new.status
        using errcode = 'P0001';
    end if;
  end if;

  return new;
end;
$$;

revoke all on function private.guard_exchange_request_update() from public, anon, authenticated;

create trigger exchange_requests_guard_update
  before update on public.exchange_requests
  for each row execute function private.guard_exchange_request_update();

-- -----------------------------------------------------------------------------
-- Historical skill integrity (approved safeguard 1)
-- Once a skill has been referenced by ANY exchange request, its identifying
-- details (name, category, level, description) can no longer change. The member
-- may still deactivate it (is_active) and create a replacement listing.
-- SECURITY DEFINER: it must see requests from other members too, which the
-- caller's own RLS view would hide.
-- -----------------------------------------------------------------------------
create or replace function private.protect_referenced_skill()
returns trigger
language plpgsql
security definer
set search_path = ''
as $$
begin
  if (new.skill_name, new.category, new.proficiency_level, new.description)
     is distinct from
     (old.skill_name, old.category, old.proficiency_level, old.description) then

    -- Lock the row first, so a request being created at the same moment
    -- (which holds FOR SHARE on this skill) is fully visible to the check below.
    --
    -- Locking review (no self-lock, no extra deadlock risk):
    --   * Postgres runs BEFORE triggers before it locks the row for the UPDATE
    --     itself, and locks held by your own transaction never block you, so
    --     locking the row we are about to update cannot wait on ourselves.
    --   * It is a single-row lock, taken only when an identifying column really
    --     changes. Deactivating a skill (is_active) and editing nothing else
    --     never reaches this code, so deactivation is never delayed by it.
    --   * The only other lockers are request creation / acceptance, which take
    --     FOR SHARE locks (ordered by skill id in accept). FOR SHARE conflicts
    --     with this lock, so the two sides wait for each other's COMMIT, never
    --     in a cycle: this trigger takes just one lock and then only READS
    --     exchange_requests (no lock on it).
    perform 1 from public.skills s where s.id = old.id for no key update;

    if exists (
      select 1
        from public.exchange_requests r
       where r.offered_skill_id = old.id
          or r.wanted_skill_id  = old.id
    ) then
      raise exception 'skill_in_use: this skill is part of an exchange request; deactivate it and create a new listing instead'
        using errcode = 'P0001';
    end if;
  end if;
  return new;
end;
$$;

revoke all on function private.protect_referenced_skill() from public, anon, authenticated;

create trigger skills_protect_referenced
  before update on public.skills
  for each row execute function private.protect_referenced_skill();

-- -----------------------------------------------------------------------------
-- Permissions (least privilege)
-- -----------------------------------------------------------------------------
alter table public.exchange_requests enable row level security;

revoke all on table public.exchange_requests from public, anon, authenticated;

grant select on table public.exchange_requests to authenticated;
-- INSERT: status is not listed (defaults to 'pending'); there is NO UPDATE and
-- NO DELETE grant. Status changes use the workflow functions only.
grant insert (requester_user_id, receiver_user_id, offered_skill_id, wanted_skill_id,
              message, proposed_datetime, format)
  on table public.exchange_requests to authenticated;

-- Only the two participants can see a request.
create policy exchange_requests_select_participants
  on public.exchange_requests for select to authenticated
  using ((select auth.uid()) in (requester_user_id, receiver_user_id));

-- A member can only create requests as themselves, and only as 'pending'.
create policy exchange_requests_insert_as_requester
  on public.exchange_requests for insert to authenticated
  with check (requester_user_id = (select auth.uid()) and status = 'pending');

