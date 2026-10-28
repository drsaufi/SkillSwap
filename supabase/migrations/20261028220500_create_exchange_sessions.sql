-- =============================================================================
-- 20261028220500_create_exchange_sessions.sql
-- The `exchange_sessions` table: exactly one session per accepted request.
--
-- Both participants must confirm. Each confirmation has its own timestamp;
-- the session is only 'completed' once both are set.
-- Sessions are created / confirmed only by the workflow functions (see the private_workflow_functions migration).
-- Participants may directly edit just the `notes` column.
-- =============================================================================

create table public.exchange_sessions (
  id                     uuid        primary key default gen_random_uuid(),
  request_id             uuid        not null unique   -- one session per request
                                     references public.exchange_requests (id) on delete restrict,
  scheduled_datetime     timestamptz not null,         -- copied from the request, UTC
  completion_status      text        not null default 'scheduled',
  requester_confirmed_at timestamptz,
  receiver_confirmed_at  timestamptz,
  completed_at           timestamptz,
  notes                  text        not null default '',
  created_at             timestamptz not null default now(),
  updated_at             timestamptz not null default now(),

  constraint exchange_sessions_status_allowed
    check (completion_status in ('scheduled', 'completed', 'cancelled')),
  constraint exchange_sessions_notes_length
    check (char_length(notes) <= 1000),
  -- 'completed' requires BOTH confirmations and a completion time, and a
  -- completion time only makes sense for a completed session.
  constraint exchange_sessions_completion_requires_both
    check (
      (
        completion_status = 'completed'
        and requester_confirmed_at is not null
        and receiver_confirmed_at is not null
        and completed_at is not null
      )
      or
      (
        completion_status <> 'completed'
        and completed_at is null
      )
    )
);

comment on table public.exchange_sessions is
  'One session per accepted request; completion needs both participants to confirm.';

create trigger exchange_sessions_set_updated_at
  before update on public.exchange_sessions
  for each row execute function private.set_updated_at();

-- -----------------------------------------------------------------------------
-- Guard on UPDATE: the request link and scheduled time never change, the final
-- states are final, and a confirmation can never be removed or changed.
-- Editing `notes` is always allowed here (RLS decides who and when).
-- -----------------------------------------------------------------------------
create or replace function private.guard_exchange_session_update()
returns trigger
language plpgsql
set search_path = ''
as $$
begin
  if new.id                 is distinct from old.id
     or new.request_id         is distinct from old.request_id
     or new.scheduled_datetime is distinct from old.scheduled_datetime
     or new.created_at         is distinct from old.created_at then
    raise exception 'session_fields_immutable: request, schedule and id cannot change'
      using errcode = 'P0001';
  end if;

  if new.completion_status is distinct from old.completion_status then
    if not (old.completion_status = 'scheduled'
            and new.completion_status in ('completed', 'cancelled')) then
      raise exception 'invalid_transition: cannot change session from % to %',
        old.completion_status, new.completion_status
        using errcode = 'P0001';
    end if;
  end if;

  if (old.requester_confirmed_at is not null
      and new.requester_confirmed_at is distinct from old.requester_confirmed_at)
     or (old.receiver_confirmed_at is not null
      and new.receiver_confirmed_at is distinct from old.receiver_confirmed_at)
     or (old.completed_at is not null
      and new.completed_at is distinct from old.completed_at) then
    raise exception 'confirmation_immutable: a recorded confirmation cannot be changed'
      using errcode = 'P0001';
  end if;

  return new;
end;
$$;

revoke all on function private.guard_exchange_session_update() from public, anon, authenticated;

create trigger exchange_sessions_guard_update
  before update on public.exchange_sessions
  for each row execute function private.guard_exchange_session_update();

-- -----------------------------------------------------------------------------
-- Permissions (least privilege)
-- -----------------------------------------------------------------------------
alter table public.exchange_sessions enable row level security;

revoke all on table public.exchange_sessions from public, anon, authenticated;

grant select on table public.exchange_sessions to authenticated;
-- Only `notes` is directly editable. No INSERT, no DELETE.
grant update (notes) on table public.exchange_sessions to authenticated;

-- Participants only. The sub-select reads exchange_requests, which RLS already
-- limits to the caller's own requests; the explicit check keeps it obvious.
create policy exchange_sessions_select_participants
  on public.exchange_sessions for select to authenticated
  using (exists (
    select 1
      from public.exchange_requests r
     where r.id = exchange_sessions.request_id
       and (select auth.uid()) in (r.requester_user_id, r.receiver_user_id)
  ));

-- Participants may edit notes, except on a cancelled session.
create policy exchange_sessions_update_notes_participants
  on public.exchange_sessions for update to authenticated
  using (
    completion_status <> 'cancelled'
    and exists (
      select 1
        from public.exchange_requests r
       where r.id = exchange_sessions.request_id
         and (select auth.uid()) in (r.requester_user_id, r.receiver_user_id)
    )
  )
  with check (exists (
    select 1
      from public.exchange_requests r
     where r.id = exchange_sessions.request_id
       and (select auth.uid()) in (r.requester_user_id, r.receiver_user_id)
  ));
