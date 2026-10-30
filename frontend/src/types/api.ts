export type SkillCategory =
  | 'Technology'
  | 'Design'
  | 'Business'
  | 'Languages'
  | 'Music'
  | 'Arts and Crafts'
  | 'Health and Fitness'
  | 'Cooking'
  | 'Academics'
  | 'Other'

export type SkillProficiencyLevel = 'beginner' | 'intermediate' | 'advanced' | 'expert'
export type SkillType = 'offered' | 'wanted'
export type ExchangeRequestStatus = 'pending' | 'accepted' | 'declined' | 'cancelled' | 'completed'
export type ExchangeFormat = 'online' | 'in_person'
export type CompletionStatus = 'scheduled' | 'completed' | 'cancelled'

export interface Profile {
  user_id: string
  display_name: string
  bio: string
  interests: string[]
  learning_preferences: string
  availability: string
  created_at: string
  updated_at: string
}

export interface ProfileUpdate {
  display_name?: string
  bio?: string
  interests?: string[]
  learning_preferences?: string
  availability?: string
}

export interface Skill {
  id: string
  owner_user_id: string
  skill_name: string
  category: SkillCategory
  description: string
  proficiency_level: SkillProficiencyLevel
  skill_type: SkillType
  is_active: boolean
  created_at: string
  updated_at: string
}

export interface SkillCreate {
  skill_name: string
  category: SkillCategory
  description?: string
  proficiency_level: SkillProficiencyLevel
  skill_type: SkillType
}

export interface SkillUpdate {
  skill_name?: string
  category?: SkillCategory
  description?: string
  proficiency_level?: SkillProficiencyLevel
}

export interface MemberDetail extends Profile {
  skills: Skill[]
}

export interface ExchangeSession {
  id: string
  request_id: string
  scheduled_datetime: string
  completion_status: CompletionStatus
  requester_confirmed_at: string | null
  receiver_confirmed_at: string | null
  completed_at: string | null
  notes: string
  created_at: string
  updated_at: string
}

export interface ExchangeRequest {
  id: string
  requester_user_id: string
  receiver_user_id: string
  offered_skill_id: string
  wanted_skill_id: string
  message: string
  status: ExchangeRequestStatus
  proposed_datetime: string
  format: ExchangeFormat
  created_at: string
  updated_at: string
  requester_display_name?: string | null
  receiver_display_name?: string | null
  offered_skill_name?: string | null
  wanted_skill_name?: string | null
}

export interface ExchangeRequestCreate {
  receiver_user_id: string
  offered_skill_id: string
  wanted_skill_id: string
  message: string
  proposed_datetime: string
  format: ExchangeFormat
}

export interface ReviewCreate {
  rating: number
  comment?: string
}

export interface ReviewResponse {
  id: string
  session_id: string
  reviewer_user_id: string
  reviewee_user_id: string
  rating: number
  comment: string
  created_at: string
}

export interface DashboardSummary {
  active_offered_skills_count: number
  active_wanted_skills_count: number
  incoming_pending_requests_count: number
  outgoing_pending_requests_count: number
  accepted_exchanges_count: number
  completed_exchanges_count: number
  average_rating: number | null
  reviews_received_count: number
  upcoming_sessions: ExchangeSession[]
}

export interface AiMatchedSkillSummary {
  id: string
  skill_name: string
  category: SkillCategory
  proficiency_level: SkillProficiencyLevel
  skill_type: SkillType
}

export interface AiSkillMatchItem {
  member_user_id: string
  display_name: string
  offered_skill_id: string
  offered_skill: AiMatchedSkillSummary
  matching_wanted_skill_id: string | null
  matching_wanted_skill: AiMatchedSkillSummary | null
  explanation: string
}

export interface AiSkillMatchListResponse {
  matches: AiSkillMatchItem[]
  candidate_count: number
}

export interface ApiErrorResponse {
  detail?: string
  error?: {
    code: string
    message: string
  }
}
