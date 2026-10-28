-- =============================================================================
-- 20261028220800_public_wrappers_and_permissions.sql
-- 1. Thin public "entry point" functions that FastAPI calls through the
--    Supabase API (RPC). They are SECURITY INVOKER: they run as the signed-in
--    member and do nothing except call the matching private function.
-- 2. A final explicit REVOKE / GRANT pass.
-- 3. A built-in, READ-ONLY self-check of the permission model.
--
-- IMPORTANT: a wrapper is NOT what makes the system safe. Each private function
-- (private_workflow_functions migration) validates the caller's identity,
-- participation and the request state itself, so it stays safe even if it were
-- called some other way.
-- =============================================================================

create or replace function public.accept_exchange_request(p_request_id uuid)
returns public.exchange_sessions
language sql
security invoker
set search_path = ''
as $$
  select * from private.accept_exchange_request(p_request_id);
$$;

create or replace function public.decline_exchange_request(p_request_id uuid)
returns public.exchange_requests
language sql
security invoker
set search_path = ''
as $$
  select * from private.decline_exchange_request(p_request_id);
$$;

create or replace function public.cancel_exchange_request(p_request_id uuid)
returns public.exchange_requests
language sql
security invoker
set search_path = ''
as $$
  select * from private.cancel_exchange_request(p_request_id);
$$;

create or replace function public.confirm_exchange_session(p_session_id uuid)
returns public.exchange_sessions
language sql
security invoker
set search_path = ''
as $$
  select * from private.confirm_exchange_session(p_session_id);
$$;

create or replace function public.create_review(
  p_session_id uuid,
  p_rating     integer,
  p_comment    text default ''
)
returns public.reviews
language sql
security invoker
set search_path = ''
as $$
  select * from private.create_review(p_session_id, p_rating, p_comment);
$$;

-- Execution permissions: nobody by default, then `authenticated` only.
revoke all on function public.accept_exchange_request(uuid)         from public, anon, authenticated;
revoke all on function public.decline_exchange_request(uuid)        from public, anon, authenticated;
revoke all on function public.cancel_exchange_request(uuid)         from public, anon, authenticated;
revoke all on function public.confirm_exchange_session(uuid)        from public, anon, authenticated;
revoke all on function public.create_review(uuid, integer, text)    from public, anon, authenticated;

grant execute on function public.accept_exchange_request(uuid)      to authenticated;
grant execute on function public.decline_exchange_request(uuid)     to authenticated;
grant execute on function public.cancel_exchange_request(uuid)      to authenticated;
grant execute on function public.confirm_exchange_session(uuid)     to authenticated;
grant execute on function public.create_review(uuid, integer, text) to authenticated;

-- -----------------------------------------------------------------------------
-- SELF-CHECK (read-only: it only reads the system catalogs and calls the
-- has_*_privilege() functions. It changes nothing.)
--
-- If any check fails it raises an error and THIS migration is rolled back.
--
-- LIMITS - please read:
--   * A failure here does NOT undo earlier migrations. Each earlier migration
--     has already been committed. Fix forward with a new migration (or, on a
--     disposable development project and only with explicit approval, reset it).
--   * It checks ACCESS RIGHTS (who may do what) at the moment it runs. It does
--     not test what RLS policy conditions actually allow, how triggers behave,
--     or whether the workflow functions' logic is right. Those need the
--     two-account tests in the migrations README.
--   * It does not re-run when later migrations change permissions.
--   * It cannot see Supabase platform settings, such as which schemas the API
--     exposes. Check that manually (README checklist).
-- -----------------------------------------------------------------------------
do $$
declare
  -- The ONLY columns an authenticated member may write directly.
  -- Every other column is protected. [] means "no direct writes at all".
  v_expected constant jsonb := '{
    "profiles": {
      "insert": [],
      "update": ["display_name", "bio", "interests", "learning_preferences", "availability"]
    },
    "skills": {
      "insert": ["owner_user_id", "skill_name", "category", "proficiency_level", "skill_type", "description"],
      "update": ["skill_name", "category", "proficiency_level", "description", "is_active"]
    },
    "exchange_requests": {
      "insert": ["requester_user_id", "receiver_user_id", "offered_skill_id", "wanted_skill_id", "message", "proposed_datetime", "format"],
      "update": []
    },
    "exchange_sessions": {
      "insert": [],
      "update": ["notes"]
    },
    "reviews": {
      "insert": [],
      "update": []
    }
  }';

  -- Functions members may call directly (RPC + the helpers they rely on).
  -- Stored as `regprocedure` (function OIDs) so comparisons never depend on
  -- how PostgreSQL formats argument spaces or type aliases in text output.
  v_workflow constant regprocedure[] := array[
    'public.accept_exchange_request(uuid)'::regprocedure,
    'public.decline_exchange_request(uuid)'::regprocedure,
    'public.cancel_exchange_request(uuid)'::regprocedure,
    'public.confirm_exchange_session(uuid)'::regprocedure,
    'public.create_review(uuid, integer, text)'::regprocedure,
    'private.accept_exchange_request(uuid)'::regprocedure,
    'private.decline_exchange_request(uuid)'::regprocedure,
    'private.cancel_exchange_request(uuid)'::regprocedure,
    'private.confirm_exchange_session(uuid)'::regprocedure,
    'private.create_review(uuid, integer, text)'::regprocedure
  ];
  -- The one other private function members must be able to execute: a CHECK
  -- constraint on profiles.interests runs with the member's privileges.
  v_allowed_helper constant regprocedure := 'private.valid_interests(text[])'::regprocedure;

  v_table   text;
  v_col     text;
  v_priv    text;
  v_fn      regprocedure;
  v_fn_oid  oid;
  v_schema  text;
  v_found   boolean;
begin
  foreach v_table in array array[
    'profiles', 'skills', 'exchange_requests', 'exchange_sessions', 'reviews'
  ] loop

    -- 1. RLS must be on.
    if not (select c.relrowsecurity
              from pg_class c
             where c.oid = format('public.%I', v_table)::regclass) then
      raise exception 'SELF-CHECK FAILED: RLS is not enabled on public.%', v_table;
    end if;

    -- 2. Anonymous users: no table-level privilege of any kind.
    foreach v_priv in array array[
      'SELECT', 'INSERT', 'UPDATE', 'DELETE', 'TRUNCATE', 'REFERENCES', 'TRIGGER'
    ] loop
      if has_table_privilege('anon', format('public.%I', v_table), v_priv) then
        raise exception 'SELF-CHECK FAILED: anon has table-level % on public.%', v_priv, v_table;
      end if;
    end loop;

    -- 3. Members: SELECT yes; no table-wide writes of any kind.
    if not has_table_privilege('authenticated', format('public.%I', v_table), 'SELECT') then
      raise exception 'SELF-CHECK FAILED: authenticated cannot SELECT public.%', v_table;
    end if;
    foreach v_priv in array array[
      'INSERT', 'UPDATE', 'DELETE', 'TRUNCATE', 'REFERENCES', 'TRIGGER'
    ] loop
      if has_table_privilege('authenticated', format('public.%I', v_table), v_priv) then
        raise exception 'SELF-CHECK FAILED: authenticated has table-wide % on public.%', v_priv, v_table;
      end if;
    end loop;

    -- 4. Every expected writable column really is writable by members.
    --    (has_column_privilege raises an error if a column name is wrong, so a
    --    typo in the list above cannot slip through silently.)
    foreach v_priv in array array['insert', 'update'] loop
      for v_col in
        select jsonb_array_elements_text(v_expected -> v_table -> v_priv)
      loop
        if not has_column_privilege('authenticated', format('public.%I', v_table),
                                    v_col, upper(v_priv)) then
          raise exception 'SELF-CHECK FAILED: authenticated cannot % column %.% (expected)',
            upper(v_priv), v_table, v_col;
        end if;
      end loop;
    end loop;

    -- 5. Column by column: members can write ONLY the expected columns, and
    --    anonymous users have no column-level access at all.
    for v_col in
      select a.attname::text
        from pg_attribute a
       where a.attrelid = format('public.%I', v_table)::regclass
         and a.attnum > 0
         and not a.attisdropped
       order by a.attnum
    loop
      -- Protected-column check: INSERT
      if has_column_privilege('authenticated', format('public.%I', v_table), v_col, 'INSERT')
         and not ((v_expected -> v_table -> 'insert') @> to_jsonb(v_col)) then
        raise exception 'SELF-CHECK FAILED: protected column %.% is INSERTable by authenticated',
          v_table, v_col;
      end if;
      -- Protected-column check: UPDATE
      if has_column_privilege('authenticated', format('public.%I', v_table), v_col, 'UPDATE')
         and not ((v_expected -> v_table -> 'update') @> to_jsonb(v_col)) then
        raise exception 'SELF-CHECK FAILED: protected column %.% is UPDATEable by authenticated',
          v_table, v_col;
      end if;
      -- REFERENCES is never needed by members.
      if has_column_privilege('authenticated', format('public.%I', v_table), v_col, 'REFERENCES') then
        raise exception 'SELF-CHECK FAILED: authenticated has REFERENCES on %.%', v_table, v_col;
      end if;
      -- Anonymous users: nothing at column level either.
      foreach v_priv in array array['SELECT', 'INSERT', 'UPDATE', 'REFERENCES'] loop
        if has_column_privilege('anon', format('public.%I', v_table), v_col, v_priv) then
          raise exception 'SELF-CHECK FAILED: anon has column-level % on %.%', v_priv, v_table, v_col;
        end if;
      end loop;
    end loop;

    -- 6. RLS policies: none may apply to anon / PUBLIC, and none may allow DELETE
    --    (cmd 'ALL' would include DELETE).
    if exists (
      select 1
        from pg_policies p
       where p.schemaname = 'public'
         and p.tablename  = v_table
         and (p.roles && array['anon', 'public']::name[]
              or p.cmd in ('DELETE', 'ALL'))
    ) then
      raise exception 'SELF-CHECK FAILED: public.% has a policy for anon/PUBLIC or one that allows DELETE', v_table;
    end if;
  end loop;

  -- 7. Schema access: anonymous users cannot reach `private`.
  if has_schema_privilege('anon', 'private', 'USAGE') or has_schema_privilege('anon', 'private', 'CREATE') then
    raise exception 'SELF-CHECK FAILED: anon has access to schema private';
  end if;
  if has_schema_privilege('authenticated', 'private', 'CREATE') then
    raise exception 'SELF-CHECK FAILED: authenticated can CREATE objects in schema private';
  end if;

  -- 8. The five workflow functions (public wrapper + private implementation):
  --    members yes, anonymous no.
  foreach v_fn in array v_workflow loop
    if has_function_privilege('anon', v_fn, 'EXECUTE') then
      raise exception 'SELF-CHECK FAILED: anon can execute %', v_fn;
    end if;
    if not has_function_privilege('authenticated', v_fn, 'EXECUTE') then
      raise exception 'SELF-CHECK FAILED: authenticated cannot execute %', v_fn;
    end if;
  end loop;

  -- Wrappers must run as the caller; private workflow functions must run as owner.
  -- Inspect pg_namespace.nspname directly instead of formatting the signature text.
  foreach v_fn in array v_workflow loop
    select n.nspname, p.prosecdef
      into v_schema, v_found
      from pg_proc p
      join pg_namespace n on n.oid = p.pronamespace
     where p.oid = v_fn;
    if v_schema = 'public' and v_found then
      raise exception 'SELF-CHECK FAILED: % must be SECURITY INVOKER', v_fn;
    end if;
    if v_schema = 'private' and not v_found then
      raise exception 'SELF-CHECK FAILED: % must be SECURITY DEFINER', v_fn;
    end if;
  end loop;

  -- 9. EVERY function in `private`, including any added by mistake later:
  --    anon never; authenticated only the workflow functions and the one
  --    CHECK-constraint helper (compared by OID / regprocedure, not formatted text).
  --    Everything else (trigger and helper functions) must not be directly
  --    executable by application users. All of them must also have a fixed
  --    search_path.
  for v_fn_oid, v_fn in
    select p.oid, p.oid::regprocedure
      from pg_proc p
      join pg_namespace n on n.oid = p.pronamespace
     where n.nspname = 'private'
  loop
    if has_function_privilege('anon', v_fn_oid, 'EXECUTE') then
      raise exception 'SELF-CHECK FAILED: anon can execute %', v_fn;
    end if;

    if has_function_privilege('authenticated', v_fn_oid, 'EXECUTE')
       and not (v_fn = any (v_workflow) or v_fn = v_allowed_helper) then
      raise exception 'SELF-CHECK FAILED: authenticated can execute helper/trigger function %', v_fn;
    end if;

    select exists (
             select 1
               from pg_proc p, unnest(p.proconfig) as cfg
              where p.oid = v_fn_oid
                and cfg like 'search_path=%'
           )
      into v_found;
    if not v_found then
      raise exception 'SELF-CHECK FAILED: % has no fixed search_path', v_fn;
    end if;
  end loop;

  -- The helper that members legitimately need must exist and be executable.
  if not has_function_privilege('authenticated', v_allowed_helper, 'EXECUTE') then
    raise exception 'SELF-CHECK FAILED: authenticated cannot execute %', v_allowed_helper;
  end if;
  if has_function_privilege('anon', v_allowed_helper, 'EXECUTE') then
    raise exception 'SELF-CHECK FAILED: anon can execute %', v_allowed_helper;
  end if;

  -- 10. The GLOBAL default (no IN SCHEMA) must no longer give PUBLIC EXECUTE on
  --     future functions. When the built-in default has been changed, Postgres
  --     stores a row in pg_default_acl (object type 'f' = functions, namespace 0
  --     = global) for the role that ran the migrations. Its ACL must exist and
  --     must grant nothing to PUBLIC (grantee OID 0 in aclexplode()).
  --     This is about future functions only; the per-function checks above cover
  --     the existing ones.
  if not exists (
       select 1
         from pg_default_acl d
        where d.defaclobjtype = 'f'
          and d.defaclnamespace = 0
          and d.defaclrole = current_user::regrole
     )
     or exists (
       select 1
         from pg_default_acl d, aclexplode(d.defaclacl) as acl
        where d.defaclobjtype = 'f'
          and d.defaclnamespace = 0
          and d.defaclrole = current_user::regrole
          and acl.grantee = 0
          and acl.privilege_type = 'EXECUTE'
     ) then
    raise exception 'SELF-CHECK FAILED: the global default still lets PUBLIC execute new functions';
  end if;
end;
$$;
