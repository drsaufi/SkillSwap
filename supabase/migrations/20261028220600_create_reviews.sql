-- =============================================================================
-- 20261028220600_create_reviews.sql
-- The `reviews` table. One review per participant per session.
--
-- Protection against duplicate / unauthorised reviews:
--   1. No INSERT right exists for members: reviews are written only by the
--      create_review workflow function (see the private_workflow_functions migration).
--   2. A trigger re-checks eligibility on every insert.
--   3. UNIQUE (session_id, reviewer_user_id) blocks duplicates in the database.
-- Reviews cannot be edited or deleted in the MVP.
-- =============================================================================

create table public.reviews (
  id               uuid        primary key default gen_random_uuid(),
  session_id       uuid        not null
                               references public.exchange_sessions (id) on delete restrict,
  reviewer_user_id uuid        not null
                               references public.profiles (user_id) on delete restrict,
  reviewee_user_id uuid        not null
                               references public.profiles (user_id) on delete restrict,
  rating           smallint    not null,
  comment          text        not null default '',
  created_at       timestamptz not null default now(),

  constraint reviews_rating_range
    check (rating between 1 and 5),
  constraint reviews_comment_length
    check (char_length(comment) <= 500),
  constraint reviews_reviewer_not_reviewee
    check (reviewer_user_id <> reviewee_user_id),
  -- Duplicate protection: one review per reviewer per session.
  constraint reviews_one_per_reviewer_per_session
    unique (session_id, reviewer_user_id)
);

comment on table public.reviews is
  'Post-session reviews. Written only by create_review(); immutable afterwards.';

-- Used for average-rating queries on the dashboard.
create index reviews_reviewee_idx on public.reviews (reviewee_user_id);

-- -----------------------------------------------------------------------------
-- Eligibility trigger (runs on every insert, whoever inserts).
-- SECURITY DEFINER so it can read the session and request regardless of RLS.
-- -----------------------------------------------------------------------------
create or replace function private.validate_review_insert()
returns trigger
language plpgsql
security definer
set search_path = ''
as $$
declare
  v_status    text;
  v_requester uuid;
  v_receiver  uuid;
begin
  select s.completion_status, r.requester_user_id, r.receiver_user_id
    into v_status, v_requester, v_receiver
    from public.exchange_sessions s
    join public.exchange_requests r on r.id = s.request_id
   where s.id = new.session_id;

  if not found then
    raise exception 'session_not_found' using errcode = 'P0002';
  end if;

  if v_status <> 'completed' then
    raise exception 'session_not_completed: reviews are only allowed after both participants confirm'
      using errcode = 'P0001';
  end if;

  -- The reviewer and reviewee must be the two (different) participants.
  if not (
    (new.reviewer_user_id = v_requester and new.reviewee_user_id = v_receiver)
    or
    (new.reviewer_user_id = v_receiver and new.reviewee_user_id = v_requester)
  ) then
    raise exception 'review_not_permitted: reviewer must be a participant reviewing the other participant'
      using errcode = '42501';
  end if;

  return new;
end;
$$;

revoke all on function private.validate_review_insert() from public, anon, authenticated;

create trigger reviews_validate_insert
  before insert on public.reviews
  for each row execute function private.validate_review_insert();

-- -----------------------------------------------------------------------------
-- Permissions (least privilege): read-only for members.
-- -----------------------------------------------------------------------------
alter table public.reviews enable row level security;

revoke all on table public.reviews from public, anon, authenticated;

grant select on table public.reviews to authenticated;

-- All signed-in members may read reviews (PRD section 8).
-- There are deliberately no INSERT / UPDATE / DELETE policies.
create policy reviews_select_authenticated
  on public.reviews for select to authenticated
  using (true);

