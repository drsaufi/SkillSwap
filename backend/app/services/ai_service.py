"""Business logic and LLM integration for the AI Skill Match Assistant — Lite."""

from __future__ import annotations

import json
import re
from typing import Any
from uuid import UUID

import httpx

from app.core.config import Settings
from app.core.errors import AppError
from app.core.supabase import UserScopedClient
from app.repositories import profile_repo, skill_repo
from app.schemas.ai import (
    AiMatchedSkillSummary,
    AiSkillMatchItem,
    AiSkillMatchListResponse,
)
from app.services.profile_service import profile_not_found_error

MAX_CANDIDATES_CAP = 20
MAX_RETURNED_MATCHES = 3
MAX_EXPLANATION_LENGTH = 500
DIRECTORY_SKILLS_PAGE_SIZE = 100
DIRECTORY_SKILLS_MAX_PAGES = 5

_PLACEHOLDER_KEYS = frozenset(
    {"", "your-llm-api-key-here", "changeme", "placeholder"}
)
_PLACEHOLDER_MODELS = frozenset(
    {"", "your-chosen-model-name", "changeme", "placeholder"}
)

GEMINI_API_BASE = "https://generativelanguage.googleapis.com/v1beta/models"
OPENAI_CHAT_COMPLETIONS_URL = "https://api.openai.com/v1/chat/completions"

SYSTEM_PROMPT = (
    "You are the SkillSwap AI Skill Match Assistant. "
    "Rank up to 3 compatible peer-learning candidates for the requesting member "
    "using ONLY the provided candidate records. "
    "Never invent member IDs, skill IDs, display names or compatibility claims. "
    "Respond strictly with a JSON object of the form: "
    '{"matches": [{"member_user_id": "<uuid>", "offered_skill_id": "<uuid>", '
    '"matching_wanted_skill_id": "<uuid or null>", '
    '"explanation": "<1-2 concise sentences grounded in the provided data>"}]}'
)


def ai_unavailable_error() -> AppError:
    """Return safe HTTP 503 error when the AI service is unconfigured or unavailable."""
    return AppError(
        status_code=503,
        error_code="ai_unavailable",
        message="AI matching service is currently unavailable.",
    )


def _is_ai_configured(settings: Settings) -> bool:
    """Verify that non-placeholder LLM API key and model name are configured."""
    key = (settings.LLM_API_KEY or "").strip()
    model = (settings.LLM_MODEL or "").strip()
    if key.lower() in _PLACEHOLDER_KEYS or model.lower() in _PLACEHOLDER_MODELS:
        return False
    return True


def create_llm_http_client(timeout_seconds: int) -> httpx.Client:
    """Create an httpx.Client configured with bounded timeouts for LLM requests."""
    timeout_val = float(max(1, min(timeout_seconds, 60)))
    timeout = httpx.Timeout(timeout_val, connect=min(5.0, timeout_val))
    return httpx.Client(timeout=timeout)


def _tokenize(text: str) -> set[str]:
    """Extract lowercase alphanumeric tokens of length >= 2 for matching."""
    return {
        tok
        for tok in re.split(r"[^a-z0-9+#]+", text.lower())
        if len(tok) >= 2
    }


def _names_match(name_a: str, name_b: str) -> bool:
    """Check if two skill/interest names match by substring or shared tokens."""
    a = name_a.strip().lower()
    b = name_b.strip().lower()
    if not a or not b:
        return False
    if a in b or b in a:
        return True
    tokens_a = _tokenize(a)
    tokens_b = _tokenize(b)
    return bool(tokens_a and tokens_b and (tokens_a & tokens_b))


def _fetch_all_active_user_skills(
    db: UserScopedClient, user_id: UUID
) -> list[dict[str, Any]]:
    """Fetch all active skills belonging to user_id."""
    rows, _ = skill_repo.select_skills(
        db,
        owner_user_id=user_id,
        is_active=True,
        limit=100,
        offset=0,
    )
    return [r for r in rows if r.get("is_active") is True]


def _fetch_directory_active_skills(
    db: UserScopedClient,
) -> list[dict[str, Any]]:
    """Fetch active skills across the directory using bounded pagination."""
    all_rows: list[dict[str, Any]] = []
    offset = 0
    for _ in range(DIRECTORY_SKILLS_MAX_PAGES):
        page_rows, total = skill_repo.select_skills(
            db,
            is_active=True,
            limit=DIRECTORY_SKILLS_PAGE_SIZE,
            offset=offset,
        )
        if not page_rows:
            break
        all_rows.extend(r for r in page_rows if r.get("is_active") is True)
        offset += len(page_rows)
        if len(all_rows) >= total or len(page_rows) < DIRECTORY_SKILLS_PAGE_SIZE:
            break
    return all_rows


def _score_candidate(
    *,
    user_offered: list[dict[str, Any]],
    user_wanted: list[dict[str, Any]],
    user_interests: list[str],
    cand_offered: list[dict[str, Any]],
    cand_wanted: list[dict[str, Any]],
    cand_interests: list[str],
) -> int:
    """Compute a deterministic compatibility score (>0 means plausible match)."""
    score = 0

    user_wanted_names = [s["skill_name"] for s in user_wanted]
    user_wanted_cats = {s["category"] for s in user_wanted}
    user_offered_names = [s["skill_name"] for s in user_offered]
    user_offered_cats = {s["category"] for s in user_offered}

    # 1. Candidate offers what the user wants or is interested in
    for c_off in cand_offered:
        c_name = c_off["skill_name"]
        c_cat = c_off["category"]
        if any(_names_match(c_name, w_name) for w_name in user_wanted_names):
            score += 10
        elif c_cat in user_wanted_cats:
            score += 4
        if any(_names_match(c_name, interest) for interest in user_interests):
            score += 6

    # 2. Reciprocal: candidate wants what the user offers
    for c_want in cand_wanted:
        w_name = c_want["skill_name"]
        w_cat = c_want["category"]
        if any(_names_match(w_name, o_name) for o_name in user_offered_names):
            score += 8
        elif w_cat in user_offered_cats:
            score += 3

    # 3. Candidate interests align with user's offered skills or interests
    for c_int in cand_interests:
        if any(_names_match(c_int, o_name) for o_name in user_offered_names):
            score += 3
        if any(_names_match(c_int, u_int) for u_int in user_interests):
            score += 2

    return score


def _build_allowlisted_llm_payload(
    *,
    user_profile: dict[str, Any],
    user_offered: list[dict[str, Any]],
    user_wanted: list[dict[str, Any]],
    candidates: list[dict[str, Any]],
) -> dict[str, Any]:
    """Build minimal, non-sensitive allowlisted JSON payload for the LLM prompt."""
    return {
        "requester": {
            "interests": list(user_profile.get("interests") or []),
            "learning_preferences": str(
                user_profile.get("learning_preferences") or ""
            ),
            "availability": str(user_profile.get("availability") or ""),
            "offered_skills": [
                {
                    "skill_name": s["skill_name"],
                    "category": s["category"],
                    "proficiency_level": s["proficiency_level"],
                }
                for s in user_offered
            ],
            "wanted_skills": [
                {
                    "skill_name": s["skill_name"],
                    "category": s["category"],
                    "proficiency_level": s["proficiency_level"],
                }
                for s in user_wanted
            ],
        },
        "candidates": [
            {
                "member_user_id": str(c["user_id"]),
                "display_name": c["display_name"],
                "interests": c["interests"],
                "learning_preferences": c["learning_preferences"],
                "availability": c["availability"],
                "offered_skills": [
                    {
                        "id": str(s["id"]),
                        "skill_name": s["skill_name"],
                        "category": s["category"],
                        "proficiency_level": s["proficiency_level"],
                    }
                    for s in c["offered_skills"]
                ],
                "wanted_skills": [
                    {
                        "id": str(s["id"]),
                        "skill_name": s["skill_name"],
                        "category": s["category"],
                        "proficiency_level": s["proficiency_level"],
                    }
                    for s in c["wanted_skills"]
                ],
            }
            for c in candidates
        ],
    }


def _call_llm_provider(
    settings: Settings,
    prompt_payload: dict[str, Any],
) -> dict[str, Any]:
    """Send allowlisted candidate data to the configured LLM API and parse JSON output."""
    api_key = settings.LLM_API_KEY.strip()
    model = settings.LLM_MODEL.strip()
    user_message = json.dumps(prompt_payload, separators=(",", ":"))

    client = create_llm_http_client(settings.LLM_TIMEOUT_SECONDS)
    try:
        if model.lower().startswith("gemini"):
            url = f"{GEMINI_API_BASE}/{model}:generateContent"
            headers = {
                "x-goog-api-key": api_key,
                "Content-Type": "application/json",
            }
            body: dict[str, Any] = {
                "systemInstruction": {"parts": [{"text": SYSTEM_PROMPT}]},
                "contents": [
                    {"role": "user", "parts": [{"text": user_message}]}
                ],
                "generationConfig": {
                    "temperature": 0.2,
                    "responseMimeType": "application/json",
                },
            }
            response = client.post(url, headers=headers, json=body)
            if response.status_code != 200:
                raise ai_unavailable_error()
            resp_json = response.json()
            raw_text = (
                resp_json["candidates"][0]["content"]["parts"][0]["text"]
            )
        else:
            headers = {
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            }
            body = {
                "model": model,
                "temperature": 0.2,
                "response_format": {"type": "json_object"},
                "messages": [
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": user_message},
                ],
            }
            response = client.post(
                OPENAI_CHAT_COMPLETIONS_URL, headers=headers, json=body
            )
            if response.status_code != 200:
                raise ai_unavailable_error()
            resp_json = response.json()
            raw_text = resp_json["choices"][0]["message"]["content"]

        parsed = json.loads(raw_text)
        if not isinstance(parsed, dict) or not isinstance(
            parsed.get("matches"), list
        ):
            raise ai_unavailable_error()
        return parsed
    except AppError:
        raise
    except Exception as exc:
        raise ai_unavailable_error() from exc
    finally:
        client.close()


def _parse_uuid_safe(value: Any) -> UUID | None:
    """Parse a UUID safely or return None if invalid."""
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        return UUID(value.strip())
    except ValueError:
        return None


def _validate_and_ground_matches(
    raw_matches: list[Any],
    candidates_by_id: dict[UUID, dict[str, Any]],
) -> list[AiSkillMatchItem]:
    """Validate AI-suggested matches against actual database records and discard invalid items."""
    validated: list[AiSkillMatchItem] = []
    seen_members: set[UUID] = set()

    for item in raw_matches:
        if not isinstance(item, dict):
            continue

        member_uid = _parse_uuid_safe(item.get("member_user_id"))
        if (
            member_uid is None
            or member_uid not in candidates_by_id
            or member_uid in seen_members
        ):
            continue

        candidate = candidates_by_id[member_uid]

        # If the LLM optionally echoed display_name, verify it matches the DB record
        if "display_name" in item and item["display_name"] is not None:
            if (
                not isinstance(item["display_name"], str)
                or item["display_name"].strip().lower()
                != candidate["display_name"].lower()
            ):
                continue

        offered_skill_uid = _parse_uuid_safe(item.get("offered_skill_id"))
        if (
            offered_skill_uid is None
            or offered_skill_uid not in candidate["offered_by_id"]
        ):
            continue

        db_offered_skill = candidate["offered_by_id"][offered_skill_uid]

        # If the LLM optionally echoed offered_skill_name, verify it matches the DB record
        if (
            "offered_skill_name" in item
            and item["offered_skill_name"] is not None
        ):
            if (
                not isinstance(item["offered_skill_name"], str)
                or item["offered_skill_name"].strip().lower()
                != db_offered_skill["skill_name"].lower()
            ):
                continue

        # Validate optional matching_wanted_skill_id if supplied
        raw_wanted_id = item.get("matching_wanted_skill_id")
        wanted_skill_uid: UUID | None = None
        wanted_skill_summary: AiMatchedSkillSummary | None = None
        if raw_wanted_id is not None and raw_wanted_id != "":
            wanted_skill_uid = _parse_uuid_safe(raw_wanted_id)
            if (
                wanted_skill_uid is None
                or wanted_skill_uid not in candidate["wanted_by_id"]
            ):
                continue
            db_wanted_skill = candidate["wanted_by_id"][wanted_skill_uid]
            wanted_skill_summary = AiMatchedSkillSummary(
                id=UUID(str(db_wanted_skill["id"])),
                skill_name=db_wanted_skill["skill_name"],
                category=db_wanted_skill["category"],
                proficiency_level=db_wanted_skill["proficiency_level"],
                skill_type=db_wanted_skill["skill_type"],
            )

        raw_explanation = item.get("explanation")
        if not isinstance(raw_explanation, str) or not raw_explanation.strip():
            continue

        offered_skill_summary = AiMatchedSkillSummary(
            id=UUID(str(db_offered_skill["id"])),
            skill_name=db_offered_skill["skill_name"],
            category=db_offered_skill["category"],
            proficiency_level=db_offered_skill["proficiency_level"],
            skill_type=db_offered_skill["skill_type"],
        )

        # Generate a concise factual explanation strictly grounded in database records
        # rather than trusting unrestricted LLM-generated claims.
        cand_name = candidate["display_name"]
        offered_name = db_offered_skill["skill_name"]
        if wanted_skill_summary is not None:
            wanted_name = wanted_skill_summary.skill_name
            grounded_explanation = (
                f"{cand_name} offers {offered_name} and is looking to learn {wanted_name}."
            )
        else:
            grounded_explanation = (
                f"{cand_name} offers {offered_name}, which is available through their SkillSwap profile."
            )

        validated.append(
            AiSkillMatchItem(
                member_user_id=member_uid,
                display_name=cand_name,
                offered_skill_id=offered_skill_uid,
                offered_skill=offered_skill_summary,
                matching_wanted_skill_id=wanted_skill_uid,
                matching_wanted_skill=wanted_skill_summary,
                explanation=grounded_explanation,
            )
        )
        seen_members.add(member_uid)

        if len(validated) >= MAX_RETURNED_MATCHES:
            break

    return validated


def generate_skill_matches(
    db: UserScopedClient,
    user_id: UUID,
    settings: Settings,
) -> AiSkillMatchListResponse:
    """Find, rank and validate grounded AI skill matches for the authenticated member."""
    if not _is_ai_configured(settings):
        raise ai_unavailable_error()

    user_profile = profile_repo.select_by_user_id(db, user_id)
    if user_profile is None:
        raise profile_not_found_error()

    user_skills = _fetch_all_active_user_skills(db, user_id)
    user_offered = [
        s for s in user_skills if s.get("skill_type") == "offered"
    ]
    user_wanted = [
        s for s in user_skills if s.get("skill_type") == "wanted"
    ]
    user_interests = list(user_profile.get("interests") or [])

    directory_skills = _fetch_directory_active_skills(db)

    # Group active skills by owner, strictly excluding the current user
    skills_by_owner: dict[UUID, list[dict[str, Any]]] = {}
    for row in directory_skills:
        if not row.get("is_active"):
            continue
        owner_uid = _parse_uuid_safe(str(row.get("owner_user_id", "")))
        if owner_uid is None or owner_uid == user_id:
            continue
        skills_by_owner.setdefault(owner_uid, []).append(row)

    # Evaluate candidate eligibility and compatibility score
    scored_candidates: list[tuple[int, str, dict[str, Any]]] = []
    for cand_uid, cand_skills in skills_by_owner.items():
        cand_offered = [
            s for s in cand_skills if s.get("skill_type") == "offered"
        ]
        if not cand_offered:
            continue

        cand_wanted = [
            s for s in cand_skills if s.get("skill_type") == "wanted"
        ]

        cand_profile = profile_repo.select_by_user_id(db, cand_uid)
        if cand_profile is None or not cand_profile.get("display_name"):
            continue

        cand_interests = list(cand_profile.get("interests") or [])
        score = _score_candidate(
            user_offered=user_offered,
            user_wanted=user_wanted,
            user_interests=user_interests,
            cand_offered=cand_offered,
            cand_wanted=cand_wanted,
            cand_interests=cand_interests,
        )
        if score <= 0:
            continue

        offered_by_id = {
            UUID(str(s["id"])): s
            for s in cand_offered
            if _parse_uuid_safe(str(s.get("id", ""))) is not None
        }
        wanted_by_id = {
            UUID(str(s["id"])): s
            for s in cand_wanted
            if _parse_uuid_safe(str(s.get("id", ""))) is not None
        }

        candidate_record = {
            "user_id": cand_uid,
            "display_name": str(cand_profile["display_name"]),
            "interests": cand_interests,
            "learning_preferences": str(
                cand_profile.get("learning_preferences") or ""
            ),
            "availability": str(cand_profile.get("availability") or ""),
            "offered_skills": cand_offered,
            "wanted_skills": cand_wanted,
            "offered_by_id": offered_by_id,
            "wanted_by_id": wanted_by_id,
        }
        scored_candidates.append((-score, str(cand_uid), candidate_record))

    scored_candidates.sort(key=lambda entry: (entry[0], entry[1]))
    max_candidates = max(1, min(settings.AI_MAX_CANDIDATES, MAX_CANDIDATES_CAP))
    selected_candidates = [
        entry[2] for entry in scored_candidates[:max_candidates]
    ]

    if not selected_candidates:
        return AiSkillMatchListResponse(matches=[], candidate_count=0)

    candidates_by_id = {c["user_id"]: c for c in selected_candidates}

    prompt_payload = _build_allowlisted_llm_payload(
        user_profile=user_profile,
        user_offered=user_offered,
        user_wanted=user_wanted,
        candidates=selected_candidates,
    )

    llm_output = _call_llm_provider(settings, prompt_payload)
    raw_matches = llm_output.get("matches", [])

    validated_matches = _validate_and_ground_matches(
        raw_matches, candidates_by_id
    )

    return AiSkillMatchListResponse(
        matches=validated_matches,
        candidate_count=len(selected_candidates),
    )
