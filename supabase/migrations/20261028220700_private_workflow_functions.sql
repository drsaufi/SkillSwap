-- =============================================================================
-- 20261028220700_private_workflow_functions.sql
-- The five privileged workflow operations. They live in the `private` schema,
-- which is NOT exposed through the Supabase API.
--
-- Why SECURITY DEFINER? Members have no direct UPDATE/INSERT right on request
-- status, sessions or reviews. These functions run with their owner's rights so
-- they can make those changes - but ONLY after proving who the caller is and
-- that the caller is allowed to do this specific thing.
--
-- Rules every function follows (do not rely on the public wrapper for safety):
--   1. SECURITY DEFINER + `SET search_path = ''` and fully-qualified names, so
--      nobody can trick the function with look-alike objects.
--   2. Identity comes ONLY from auth.uid() (the caller's JWT), never from a
--      parameter. If it is NULL the function stops (42501).
--   3. The row is locked (FOR UPDATE) before checks, so two simultaneous calls
--      cannot both succeed.
--   4. Participation is checked inside the function. Non-participants get
--      "not found" (P0002) so ids cannot be probed; participants who lack the
--      right role get "not permitted" (42501).
--   5. Wrong state -> P0001. Invalid input -> 22023. Duplicate -> 23505.
--   6. EXECUTE is revoked from PUBLIC/anon and granted to `authenticated` only.
--      (authenticated needs it because the public wrapper runs as the caller.)
-- =============================================================================

-- -----------------------------------------------------------------------------
-- ACCEPT: receiver only, request must be pending.
-- Approved safeguard 2: both skills must still be active.
-- Atomically: request -> accepted AND one session is created.
-- -----------------------------------------------------------------------------
create or replace function private.accept_exchange_request(p_request_id uuid)
returns public.exchange_sessions
language plpgsql
security definer
set search_path = ''
as $$
declare
  v_uid     uuid := auth.uid();
  v_req     public.exchange_requests%rowtype;
  v_session public.exchange_sessions%rowtype;
  v_active  integer;
begin
  if v_uid is null then
    raise exception 'not_authenticated' using errcode = '42501';
  end if;

  select * into v_req
    from public.exchange_requests
   where id = p_request_id
     for update;

  if not found or v_uid not in (v_req.requester_user_id, v_req.receiver_user_id) then
    raise exception 'request_not_found' using errcode = 'P0002';
  end if;
  if v_uid <> v_req.receiver_user_id then
    raise exception 'not_permitted: only the receiver can accept a request' using errcode = '42501';
  end if;
  if v_req.status <> 'pending' then
    raise exception 'invalid_state: only a pending request can be accepted' using errcode = 'P0001';
  end if;
  if v_req.proposed_datetime <= now() then
    raise exception 'proposed_time_passed: the proposed time is in the past; ask for a new request'
      using errcode = 'P0001';
  end if;

  -- Lock both skills first (so they cannot be deactivated at this very moment),
  -- then confirm both are still active.
  perform 1
    from public.skills s
   where s.id in (v_req.offered_skill_id, v_req.wanted_skill_id)
   order by s.id
     for share;

  select count(*) into v_active
    from public.skills s
   where s.id in (v_req.offered_skill_id, v_req.wanted_skill_id)
     and s.is_active;

  if v_active <> 2 then
    raise exception 'skill_inactive: a skill in this request has been deactivated'
      using errcode = 'P0001';
  end if;

  update public.exchange_requests
     set status = 'accepted'
   where id = v_req.id;

  insert into public.exchange_sessions (request_id, scheduled_datetime)
  values (v_req.id, v_req.proposed_datetime)
  returning * into v_session;

  return v_session;
end;
$$;

-- -----------------------------------------------------------------------------
-- DECLINE: receiver only, request must be pending.
-- -----------------------------------------------------------------------------
create or replace function private.decline_exchange_request(p_request_id uuid)
returns public.exchange_requests
language plpgsql
security definer
set search_path = ''
as $$
declare
  v_uid uuid := auth.uid();
  v_req public.exchange_requests%rowtype;
begin
  if v_uid is null then
    raise exception 'not_authenticated' using errcode = '42501';
  end if;

  select * into v_req
    from public.exchange_requests
   where id = p_request_id
     for update;

  if not found or v_uid not in (v_req.requester_user_id, v_req.receiver_user_id) then
    raise exception 'request_not_found' using errcode = 'P0002';
  end if;
  if v_uid <> v_req.receiver_user_id then
    raise exception 'not_permitted: only the receiver can decline a request' using errcode = '42501';
  end if;
  if v_req.status <> 'pending' then
    raise exception 'invalid_state: only a pending request can be declined' using errcode = 'P0001';
  end if;

  update public.exchange_requests
     set status = 'declined'
   where id = v_req.id
  returning * into v_req;

  return v_req;
end;
$$;

-- -----------------------------------------------------------------------------
-- CANCEL: requester may cancel a pending request; either participant may cancel
-- an accepted one. Atomically also cancels the session, if there is one.
-- -----------------------------------------------------------------------------
create or replace function private.cancel_exchange_request(p_request_id uuid)
returns public.exchange_requests
language plpgsql
security definer
set search_path = ''
as $$
declare
  v_uid uuid := auth.uid();
  v_req public.exchange_requests%rowtype;
begin
  if v_uid is null then
    raise exception 'not_authenticated' using errcode = '42501';
  end if;

  select * into v_req
    from public.exchange_requests
   where id = p_request_id
     for update;

  if not found or v_uid not in (v_req.requester_user_id, v_req.receiver_user_id) then
    raise exception 'request_not_found' using errcode = 'P0002';
  end if;

  if v_req.status = 'pending' then
    if v_uid <> v_req.requester_user_id then
      raise exception 'not_permitted: only the requester can cancel a pending request (the receiver can decline)'
        using errcode = '42501';
    end if;
  elsif v_req.status <> 'accepted' then
    raise exception 'invalid_state: only a pending or accepted request can be cancelled'
      using errcode = 'P0001';
  end if;

  update public.exchange_requests
     set status = 'cancelled'
   where id = v_req.id
  returning * into v_req;

  update public.exchange_sessions
     set completion_status = 'cancelled'
   where request_id = v_req.id
     and completion_status = 'scheduled';

  return v_req;
end;
$$;

-- -----------------------------------------------------------------------------
-- CONFIRM: a participant confirms the session took place.
-- Only the caller's own confirmation is recorded (their role is derived from
-- the request, never from input).
-- REPEATED CALLS: if the caller has already confirmed, the function returns the
-- session exactly as it is - no write happens, so the confirmation timestamp and
-- the session's updated_at are untouched. (This also applies once the session
-- is completed, so a double-click on the final confirmation is harmless.)
-- When BOTH have confirmed: session -> completed and request -> completed,
-- in the same transaction.
-- -----------------------------------------------------------------------------
create or replace function private.confirm_exchange_session(p_session_id uuid)
returns public.exchange_sessions
language plpgsql
security definer
set search_path = ''
as $$
declare
  v_uid             uuid := auth.uid();
  v_request_id      uuid;
  v_req             public.exchange_requests%rowtype;
  v_session         public.exchange_sessions%rowtype;
  v_is_requester    boolean;
  v_caller_done     boolean;
  v_other_done      boolean;
begin
  if v_uid is null then
    raise exception 'not_authenticated' using errcode = '42501';
  end if;

  select s.request_id into v_request_id
    from public.exchange_sessions s
   where s.id = p_session_id;

  if not found then
    raise exception 'session_not_found' using errcode = 'P0002';
  end if;

  -- Lock order is always request first, then session (same as cancel), so two
  -- operations on the same exchange can never deadlock.
  select * into v_req
    from public.exchange_requests
   where id = v_request_id
     for update;

  if not found or v_uid not in (v_req.requester_user_id, v_req.receiver_user_id) then
    raise exception 'session_not_found' using errcode = 'P0002';
  end if;

  select * into v_session
    from public.exchange_sessions
   where id = p_session_id
     for update;

  v_is_requester := (v_uid = v_req.requester_user_id);
  v_caller_done  := case when v_is_requester
                      then v_session.requester_confirmed_at is not null
                      else v_session.receiver_confirmed_at  is not null end;
  v_other_done   := case when v_is_requester
                      then v_session.receiver_confirmed_at  is not null
                      else v_session.requester_confirmed_at is not null end;

  -- Repeated confirmation: nothing to change, so write nothing.
  -- (A cancelled session is excluded and still falls through to the error.)
  if v_caller_done and v_session.completion_status in ('scheduled', 'completed') then
    return v_session;
  end if;

  if v_req.status <> 'accepted' or v_session.completion_status <> 'scheduled' then
    raise exception 'invalid_state: only a scheduled session of an accepted request can be confirmed'
      using errcode = 'P0001';
  end if;

  -- First confirmation by this caller. One single UPDATE records it and, if the
  -- other participant has already confirmed, completes the session as well.
  update public.exchange_sessions s
     set requester_confirmed_at = case when v_is_requester
                                    then now() else s.requester_confirmed_at end,
         receiver_confirmed_at  = case when v_is_requester
                                    then s.receiver_confirmed_at else now() end,
         completion_status      = case when v_other_done
                                    then 'completed' else s.completion_status end,
         completed_at           = case when v_other_done
                                    then now() else s.completed_at end
   where s.id = p_session_id
  returning * into v_session;

  if v_other_done then
    update public.exchange_requests
       set status = 'completed'
     where id = v_req.id;
  end if;

  return v_session;
end;
$$;

-- -----------------------------------------------------------------------------
-- CREATE REVIEW: a participant reviews the OTHER participant of a completed
-- session. The reviewer is the caller; the reviewee is derived, not supplied.
-- -----------------------------------------------------------------------------
create or replace function private.create_review(
  p_session_id uuid,
  p_rating     integer,
  p_comment    text default ''
)
returns public.reviews
language plpgsql
security definer
set search_path = ''
as $$
declare
  v_uid        uuid := auth.uid();
  v_request_id uuid;
  v_req        public.exchange_requests%rowtype;
  v_status     text;
  v_comment  text := btrim(coalesce(p_comment, ''));
  v_reviewee uuid;
  v_review   public.reviews%rowtype;
begin
  if v_uid is null then
    raise exception 'not_authenticated' using errcode = '42501';
  end if;

  if p_rating is null or p_rating < 1 or p_rating > 5 then
    raise exception 'invalid_rating: rating must be between 1 and 5' using errcode = '22023';
  end if;
  if char_length(v_comment) > 500 then
    raise exception 'invalid_comment: comment must be at most 500 characters' using errcode = '22023';
  end if;

  select s.request_id, s.completion_status
    into v_request_id, v_status
    from public.exchange_sessions s
   where s.id = p_session_id;

  if not found then
    raise exception 'session_not_found' using errcode = 'P0002';
  end if;

  select * into v_req
    from public.exchange_requests
   where id = v_request_id;

  if not found or v_uid not in (v_req.requester_user_id, v_req.receiver_user_id) then
    raise exception 'session_not_found' using errcode = 'P0002';
  end if;

  if v_status <> 'completed' then
    raise exception 'session_not_completed: reviews are only allowed after both participants confirm'
      using errcode = 'P0001';
  end if;

  if exists (
    select 1 from public.reviews rv
     where rv.session_id = p_session_id
       and rv.reviewer_user_id = v_uid
  ) then
    raise exception 'review_already_exists: you have already reviewed this session'
      using errcode = '23505';
  end if;

  v_reviewee := case
    when v_uid = v_req.requester_user_id then v_req.receiver_user_id
    else v_req.requester_user_id
  end;

  -- The unique constraint and the validate_review_insert trigger are still the
  -- final backstops if two calls race each other.
  insert into public.reviews (session_id, reviewer_user_id, reviewee_user_id, rating, comment)
  values (p_session_id, v_uid, v_reviewee, p_rating::smallint, v_comment)
  returning * into v_review;

  return v_review;
end;
$$;

-- -----------------------------------------------------------------------------
-- Execution permissions: nobody by default, then `authenticated` only.
-- -----------------------------------------------------------------------------
revoke all on function private.accept_exchange_request(uuid)          from public, anon, authenticated;
revoke all on function private.decline_exchange_request(uuid)         from public, anon, authenticated;
revoke all on function private.cancel_exchange_request(uuid)          from public, anon, authenticated;
revoke all on function private.confirm_exchange_session(uuid)         from public, anon, authenticated;
revoke all on function private.create_review(uuid, integer, text)     from public, anon, authenticated;

grant execute on function private.accept_exchange_request(uuid)       to authenticated;
grant execute on function private.decline_exchange_request(uuid)      to authenticated;
grant execute on function private.cancel_exchange_request(uuid)       to authenticated;
grant execute on function private.confirm_exchange_session(uuid)      to authenticated;
grant execute on function private.create_review(uuid, integer, text)  to authenticated;
