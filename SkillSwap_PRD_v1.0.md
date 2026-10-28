# SkillSwap — Product Requirements Document

**AI-Powered Peer-to-Peer Skill Exchange Platform**

**Version:** 1.0 (Approved)  
**Date:** 28 October 2026

**Project phase:** Phase 1 — Completed

**Status:** Approved as the Phase 1 development baseline

**Basis:** SkillSwap_Full_Stack_AI_Project_Brief.docx and the agreed project planning decisions

> **Purpose:** A single, practical blueprint for AI-assisted implementation, testing, deployment and the final course demonstration. It is not source code.

# 1. Project overview

## 1.1 Product vision

SkillSwap is a responsive web application enabling people to teach skills they know and learn skills they want through peer-to-peer exchanges. Members discover compatible users, organise requests and learning sessions, record completion and review their experience. A focused AI feature improves matching using real member and skill data.

## 1.2 Problem and users

People may have valuable knowledge but struggle to find suitable learning partners. SkillSwap offers structured discovery and exchange without requiring course payments.

| **Role**          | **Permissions / experience**                                                                                                                                                    |
|-------------------|---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| Visitor           | View landing page; register or log in.                                                                                                                                          |
| Registered member | Maintain own profile/skills; discover other members; send/receive exchange requests; complete sessions; review participants; see dashboard; obtain AI matching recommendations. |

## 1.3 Project objectives

- Responsive, accessible interface for desktop and mobile.
- React + TypeScript frontend connected to FastAPI and hosted Supabase PostgreSQL.
- Secure Supabase Auth and user-specific authorisation.
- Fully working profile, skills, discovery, exchange, scheduling and review workflows.
- At least one genuinely useful AI feature.
- Live deployment plus GitHub repository and explainable technical decisions.

## 1.4 MVP boundaries

| **Included in MVP**                                                                                                                                                                                           | **Explicitly excluded from MVP**                                                                                                                   |
|---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|----------------------------------------------------------------------------------------------------------------------------------------------------|
| Profiles and skills; search and filtering; AI Skill Match Assistant; requests and statuses; one session per accepted request; two-party completion; reviews; dashboard; authentication; security; deployment. | Payments, built-in video conferencing, direct messaging, native mobile apps, badges/leaderboards, custom AI model training, administrator console. |

MVP means the smallest complete application satisfying the project brief; it does not mean a visual-only prototype.

# 2. Required technology and architecture

| **Layer**      | **Technology**                   | **Responsibility**                                                           |
|----------------|----------------------------------|------------------------------------------------------------------------------|
| Frontend       | React + TypeScript; Tailwind CSS | Screens, navigation, forms, feedback and responsive layouts.                 |
| Backend        | Python + FastAPI                 | REST APIs, validation, status transitions, authorisation and AI integration. |
| Data           | Supabase PostgreSQL              | Persistent relational records with constraints and RLS.                      |
| Authentication | Supabase Auth                    | Registration, login and identity tokens.                                     |
| AI             | LLM API via FastAPI              | Grounded matching explanation/ranking; server-held key.                      |
| Versioning     | Git + GitHub                     | Source code, commits, documentation.                                         |
| Deployment     | Vercel + suitable FastAPI host   | Public website and backend URLs.                                             |

Proposed request path: Browser (React) → FastAPI with authenticated user token → authorised Supabase data access → response to React. Registration and login use Supabase Auth. AI calls originate only from FastAPI. The implementation must preserve end-user RLS enforcement or provide equivalent robust server-side permission checks; an elevated database key must never be treated as a substitute for authorisation.

# 3. Approved site map and design

| **Page / route (proposed)** | **Core content or actions**                                                                            |
|-----------------------------|--------------------------------------------------------------------------------------------------------|
| Landing /                   | Value proposition, how it works, benefits, register/login calls to action.                             |
| Register /register          | Create account; email, password, confirmation and validation.                                          |
| Login /login                | Sign in, handle invalid credentials; logout available to signed-in members.                            |
| Dashboard /dashboard        | Offered/wanted skills, request summaries, sessions and completed-count/average-rating metrics.         |
| My Profile /profile         | Edit display name, bio, interests, preferences, availability and manage skills.                        |
| Explore /explore            | Search skills/members, category and proficiency filters, usable empty states.                          |
| Member Details /members/:id | Public profile and offered/wanted skills; initiate exchange.                                           |
| Requests /requests          | Incoming/outgoing, status filtering, scheduling, status controls, completion confirmation and reviews. |
| AI Matches /ai-matches      | Request personalised matches, display grounded explanations or helpful fallback.                       |

Navigation: desktop header with Dashboard, Explore Skills, AI Matches, Exchange Requests, My Profile and logout; equivalent collapsible mobile navigation. Visitors see simplified public navigation. Visual direction: modern professional SaaS, light mode; navy `#142D4E`, teal `#087E8B`, off-white `#F5F8FB`, gold accent `#F2B45D`.

Routes are proposed implementation labels, not externally mandated paths. Main features may use modals or subviews without increasing the nine-page count.

# 4. User journeys and business rules

## 4.1 Main successful journey

Register / log in → create profile → add offered and wanted skills → search or receive AI matches → inspect member → send request with proposed date/time and format → recipient accepts → session takes place → both confirm completion → each may leave one review → dashboard updates.

## 4.2 Exchange request state model

| **From**  | **Action / actor**                         | **To**    | **Rule**                                                          |
|-----------|--------------------------------------------|-----------|-------------------------------------------------------------------|
| None      | Requester sends valid request              | Pending   | Different requester and receiver; references valid member skills. |
| Pending   | Receiver accepts                           | Accepted  | Agrees to proposed session details; create one exchange session.  |
| Pending   | Receiver declines                          | Declined  | Preserve history; terminal state.                                 |
| Pending   | Requester cancels                          | Cancelled | Preserve history; terminal state.                                 |
| Accepted  | Either participant cancels                 | Cancelled | Before completion; preserve record; terminal state.               |
| Accepted  | Both participants confirm session occurred | Completed | First confirmation does not by itself complete the request.       |
| Completed | Eligible participant posts review          | Completed | Only one review per participant for that session.                 |

## 4.3 Core rules

- Only authenticated users may perform member functions. Profile owners edit only their own profile and skill records.
- A member cannot request an exchange with themselves. Requester chooses one of their offered skills; the requested-to-learn skill is an active offered skill owned by the receiver.
- Reciprocal skill compatibility is preferred for AI ranking, but an exact two-way match is not mandatory for a user-initiated request.
- Receiver alone accepts/declines pending requests; requester may cancel pending; either participant may cancel accepted.
- The proposed date/time and online/in-person format are agreed upon acceptance. No built-in calendar negotiation or recurring sessions in MVP.
- Each accepted request has one session; participants confirm completion separately; request becomes Completed only after both confirmations.
- Completed, declined and cancelled requests do not reopen. Reviews can be entered only after completion; each person reviews the other at most once.
- Use clear validation, loading, empty, success and error messages for all primary workflows.

# 5. Functional requirements and acceptance criteria

Each item is testable. Priority M = mandatory in the agreed MVP. The IDs support coding prompts, QA and bug reports.

| **ID** | **Requirement (priority M)**         | **Acceptance / visible evidence**                                                                            |
|--------|--------------------------------------|--------------------------------------------------------------------------------------------------------------|
| FR-01  | Register, login and logout           | Valid account registers/logs in; incorrect credentials fail; logout removes access to protected screens.     |
| FR-02  | Edit own member profile              | Valid updates persist across refresh and sign-in; another user cannot edit.                                  |
| FR-03  | Manage offered/wanted skills         | Create, edit and deactivate skills; store category, level and type; persist changes.                         |
| FR-04  | View member summaries                | Members can view public profile fields and skills; private credentials do not appear.                        |
| FR-05  | Search and filter directory          | Search by skill/category, filter by proficiency/preferences where represented; correct empty/loading states. |
| FR-06  | Send exchange request                | Select valid skills, message, proposed date/time and format; creates Pending row.                            |
| FR-07  | Manage request lifecycle             | Only authorised actors change status; both members see current persisted state.                              |
| FR-08  | Track session and confirm completion | Accepted request creates session; both confirmations required for Completed.                                 |
| FR-09  | Leave post-exchange reviews          | Review only completed participation; rating 1–5; no duplicate reviewer for a session.                        |
| FR-10  | Member dashboard                     | Counts and sections are calculated from actual member data, not hardcoded placeholders.                      |
| FR-11  | AI grounded matches                  | AI suggests only existing eligible members/skills and explains fit; no invented records.                     |
| FR-12  | AI failure handling                  | Shows loading/empty/error states; ordinary directory still works if AI is unavailable.                       |
| FR-13  | End-to-end persistent data           | All main actions persist in Supabase after refresh and backend restart.                                      |
| FR-14  | Mobile and desktop usability         | Navigation, forms, cards and status actions usable at small and large viewports.                             |
| FR-15  | Privacy/permission enforcement       | User A cannot read another user’s private request data or change their profile/requests by changing IDs.     |
| FR-16  | Live deployment and repository       | Public frontend calls deployed API; README documents installation, configuration and architecture.           |

# 6. AI Skill Match Assistant

Selected AI option: AI Skill Match Assistant, as recommended in the course project brief. Its objective is to increase the relevance of skill discovery, not to supply a generic conversational chatbot.

## 6.1 Proposed matching design

1. Authenticate the requesting member and retrieve their active offered/wanted skills, interests and learning preferences.
2. Query Supabase for real, active candidate members and skill records; exclude the requesting member.
3. Use deterministic application checks to identify plausible candidate matches (e.g. candidate offers a wanted skill; optionally reciprocal compatibility).
4. Send a minimal, allowlisted set of candidate IDs, skills and non-sensitive preferences to the AI model via FastAPI.
5. Accept structured AI output only after server-side validation; discard IDs, attributes or explanations inconsistent with the database.
6. Display ranked recommendations with concise reason(s) and links to actual member pages. If none, suggest updating skills/preferences.

## 6.2 AI safeguards

- API key and provider credentials remain only in backend environment variables.
- Limits on input size, candidate count and AI cost; timeout and graceful errors.
- No unrestricted database queries or direct database modification by the model.
- Never send passwords, email addresses or unnecessary personal data to the model.
- No fabricated member IDs, skills or compatibility claims.

Exact matching weights, candidate limits, LLM provider/model and response JSON schema will be implementation decisions, verified against this PRD. They are not additional approved product features.

# 7. Data model and relationship rules

Supabase Auth manages accounts in auth.users. The application uses five relational tables. Identifiers, foreign keys and timestamps are required, as are appropriate uniqueness and integrity constraints.

| **Table**         | **Fields (high-level design)**                                                                                                                 | **Core integrity requirements**                                                                   |
|-------------------|------------------------------------------------------------------------------------------------------------------------------------------------|---------------------------------------------------------------------------------------------------|
| profiles          | user_id, display_name, bio, interests, learning_preferences, availability, created_at, updated_at                                              | user_id uniquely references auth.users; public fields separated from authentication secrets.      |
| skills            | id, owner_user_id, skill_name, category, proficiency_level, skill_type, description, is_active, created_at, updated_at                         | owner references profile; skill_type offered/wanted; level in defined categories.                 |
| exchange_requests | id, requester_user_id, receiver_user_id, offered_skill_id, wanted_skill_id, message, status, proposed_datetime, format, created_at, updated_at | Members differ; both skill IDs valid and belong to correct owners; valid status/format.           |
| exchange_sessions | id, request_id, scheduled_datetime, completion_status, requester_confirmed_at, receiver_confirmed_at, completed_at, notes                      | Unique request_id (one session per request); completion requires both confirmations.              |
| reviews           | id, session_id, reviewer_user_id, reviewee_user_id, rating, comment, created_at                                                                | Rating 1–5; reviewer is a participant reviewing the other; unique (session_id, reviewer_user_id). |

Relationship summary: auth.users 1:1 profiles; profiles 1:many skills; each member 1:many incoming/outgoing exchange_requests; exchange_requests 1:0–1 exchange_sessions; each completed exchange_session 0–2 reviews.

## 7.1 Persistence and lifecycle conventions

- Use timestamp columns consistently and use timezone-aware values for scheduled sessions.
- Deactivate previously used skills instead of deleting historical references.
- Never permit arbitrary client updates to protected status/confirmation/review fields; enforce rules in the backend and database.
- Dashboard metrics must be computed from persisted requests, sessions and reviews.

# 8. Authentication, authorisation and privacy

| **Resource**                | **Who may read**                    | **Who may write/change**                                      |
|-----------------------------|-------------------------------------|---------------------------------------------------------------|
| Auth identity / credentials | Account owner through Supabase Auth | Supabase Auth-managed operations only.                        |
| Public profile fields       | Authenticated members               | Profile owner only.                                           |
| Skills                      | Authenticated members               | Skill owner only; historical references protected.            |
| Exchange requests           | Requester and receiver only         | Status-specific actor validated at API/server boundary.       |
| Exchange sessions           | Two request participants            | Confirmation/cancellation actions restricted to participants. |
| Reviews                     | Authenticated members               | Only eligible completed-session participant; one per person.  |

Apply RLS on application tables; prefer authenticated-user-scoped database access from FastAPI or enforce equivalently rigorous server-side permissions if administrative access is essential. Never expose elevated Supabase keys in React or GitHub. Validate session identity and ownership at every sensitive endpoint. Protect against cross-user reads and writes, including changes to URL IDs or request payloads.

# 9. Proposed backend API contracts

These are illustrative paths for implementation planning. Supabase Auth handles registration/login; these endpoints cover SkillSwap business operations.

| **Method + route (draft)**                      | **Purpose**                                              |
|-------------------------------------------------|----------------------------------------------------------|
| GET /health                                     | Backend health check.                                    |
| GET /profile/me; PATCH /profile/me              | Read or edit signed-in profile.                          |
| GET /skills; POST /skills                       | Search/list skills; add user skill.                      |
| PATCH /skills/{id}; DELETE /skills/{id}         | Edit skill or deactivate it (soft-delete behaviour).     |
| GET /members/{id}                               | View eligible member summary.                            |
| GET /exchange-requests; POST /exchange-requests | Read own incoming/outgoing requests; submit new request. |
| POST /exchange-requests/{id}/accept             | Recipient accepts; creates session.                      |
| POST /exchange-requests/{id}/decline            | Recipient declines.                                      |
| POST /exchange-requests/{id}/cancel             | Authorised participant cancels.                          |
| POST /exchange-sessions/{id}/confirm            | Participant confirms completion.                         |
| POST /exchange-sessions/{id}/reviews            | Eligible participant creates review.                     |
| GET /dashboard/summary                          | Counts and upcoming/completed activity.                  |
| POST /ai/skill-matches                          | Grounded AI member matching.                             |

Every protected endpoint requires authentication, validates input, checks participant/owner permissions and returns appropriate HTTP errors. API documentation should remain available for demonstration without exposing secrets.

# 10. Non-functional requirements

- Accessibility and usability: readable forms, labels, keyboard focus, consistent responsive navigation, colour contrast and feedback.
- Performance: search and dashboard should load with sensible pagination/limits; show loading indicators for network/AI actions.
- Reliability: database-backed data survives refresh/restart; API errors should not result in silent data loss.
- Security: environment-variable secrets, clean Git history, RLS/permission tests, validation on frontend and backend.
- Privacy: sample accounts use fictional data; distinguish public profile fields from private information.
- AI safety: constrained inputs/outputs; failure and timeouts do not block core skill discovery.
- Code quality: clear module structure, basic automated tests, small commits and documented decisions.

# 11. Test and acceptance strategy

## 11.1 Minimum end-to-end demonstration

- Create fictional Ahmad and Sarah accounts. Verify independent logins and profiles.
- Ahmad offers Excel and wants Graphic Design; Sarah offers Graphic Design and wants Excel.
- Find Sarah via Explore Skills and via grounded AI Matches; recommendation points to real profile.
- Ahmad sends Pending request with date/time and online/in-person format; Sarah receives it.
- Sarah accepts; check both accounts see Accepted and a session row with agreed details.
- Confirm on Ahmad only: still not Completed. Confirm on Sarah: now Completed.
- Submit valid reviews from both participants; verify average rating and completed count.
- Refresh both browsers / restart backend: all records persist.
- Try to access other-user private request or change another profile; request is blocked.
- Simulate no AI matches or AI provider failure; directory and core exchange remain usable.

## 11.2 Additional negative tests

- Invalid login or empty required fields.
- Self-request or wrong skill ownership.
- Attempted duplicate review, rating out of bounds or premature completion.
- Unauthorised status change; terminal state modification; cancelled accepted session.
- Empty skills, empty request list and empty dashboards; mobile viewport checks.

# 12. Development milestones after Phase 1

| **Next phase**                            | **Deliverable / exit gate**                                                 |
|-------------------------------------------|-----------------------------------------------------------------------------|
| Phase 2 — Environment and setup           | Working local tools, GitHub repository, Supabase project, documented setup. |
| Phase 3 — Core backend and security       | Authentication, schema and RLS, tested profile/skill and request APIs.      |
| Phase 4 — Frontend and integration        | Nine pages and responsive navigation connected to actual APIs.              |
| Phase 5 — Exchange workflow and dashboard | End-to-end two-account request → completion → review; genuine metrics.      |
| Phase 6 — AI matching                     | Server-side grounded matching with validated output and graceful failure.   |
| Phase 7 — Testing and deployment          | Functional/security tests; live React/FastAPI/Supabase integration.         |
| Phase 8 — Submission and presentation     | README, source, URLs, screenshots and 5–7 minute live demo.                 |

These phases are our guided development plan. The course brief specifies a suggested build order; the phase labels are organisational choices for this project.

# 13. Submission, marking and live demo

| **Assessment domain**                    | **Marks** |
|------------------------------------------|-----------|
| Frontend and user experience             | 15        |
| Backend and API integration              | 15        |
| Database and persistence                 | 15        |
| Authentication and authorisation         | 10        |
| Core SkillSwap workflows                 | 15        |
| AI feature                               | 10        |
| Deployment and GitHub                    | 10        |
| Presentation and technical understanding | 10        |
| TOTAL                                    | 100       |

Required submissions: live frontend URL; live FastAPI URL / API docs; GitHub repository with clear README and screenshots; hosted Supabase project with security policies; at least one working AI feature; 5–7 minute live presentation and readiness for questions.

Demo order: brief problem → login/profile/skills → find a compatible member → send/accept request → refresh to demonstrate persistence → completion/review/dashboard → AI matches → show backend health/API docs, data model and GitHub → explain one bug and its resolution.

# 14. Decisions and implementation notes

## 14.1 Approved in Phase 1, Steps 1–4

- General-purpose peer-to-peer skill exchange MVP; visitors and registered members.
- Six functional modules; nine screens with modern professional light-mode interface.
- Manual search plus AI Skill Match Assistant; AI grounded in real records.
- Five request statuses, one accepted session per request, bilateral completion, review by each participant.
- Supabase Auth plus five core tables; RLS and backend access checks.
- Explicit exclusions: payments, integrated video, messaging, native apps, gamification, custom-trained AI, admin console.

## 14.2 Technical details to finalise during implementation

- Exact SQL column types and maximum text lengths, indexes and database policy statements.
- Timezone capture/display for proposed session times and validation of past dates.
- Precise review visibility rules and whether free-text session notes require additional privacy restrictions.
- Exact API route naming, error codes and component-level designs.
- AI provider/model, candidate ranking parameters, token budgets and AI response schema.

Any implementation choice must remain compatible with the approved scope and the project brief. Material changes to product behaviour should be reviewed before coding.

## 14.3 Source materials

Primary: SkillSwap_Full_Stack_AI_Project_Brief.docx (five-page assignment specification). Course alignment: Session 03 (PRD/Git), Session 05 (Supabase database), Session 06 (Auth/JWT), Session 07 (RLS), Sessions 08–10 (React/UI/API), Sessions 12–13 (AI integration), Session 14 (dashboard), Session 15 (deployment), Session 17 (debugging).
