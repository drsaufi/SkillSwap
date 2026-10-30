import { API_BASE_URL, supabase } from './supabase'
import type {
  AiSkillMatchListResponse,
  DashboardSummary,
  ExchangeRequest,
  ExchangeRequestCreate,
  ExchangeSession,
  MemberDetail,
  Profile,
  ProfileUpdate,
  ReviewCreate,
  ReviewResponse,
  Skill,
  SkillCreate,
  SkillUpdate,
} from '../types/api'

export class ApiError extends Error {
  status: number
  code: string

  constructor(status: number, code: string, message: string) {
    super(message)
    this.name = 'ApiError'
    this.status = status
    this.code = code
  }
}

async function request<T>(path: string, options: RequestInit = {}): Promise<T> {
  const { data: sessionData } = await supabase.auth.getSession()
  const token = sessionData.session?.access_token

  const headers: Record<string, string> = {
    'Content-Type': 'application/json',
    ...(options.headers as Record<string, string>),
  }

  if (token) {
    headers['Authorization'] = `Bearer ${token}`
  }

  const url = `${API_BASE_URL}${path.startsWith('/') ? path : `/${path}`}`

  let response: Response
  try {
    response = await fetch(url, {
      ...options,
      headers,
    })
  } catch (err: unknown) {
    throw new ApiError(
      0,
      'network_error',
      err instanceof Error ? err.message : 'Unable to connect to SkillSwap API server.'
    )
  }

  if (!response.ok) {
    let errorCode = 'api_error'
    let errorMessage = `Request failed with status ${response.status}`

    try {
      const errBody = await response.json()
      if (errBody?.error?.code && errBody?.error?.message) {
        errorCode = errBody.error.code
        errorMessage = errBody.error.message
      } else if (errBody?.detail) {
        if (typeof errBody.detail === 'string') {
          errorMessage = errBody.detail
        } else if (Array.isArray(errBody.detail)) {
          errorMessage = errBody.detail.map((d: { msg?: string }) => d.msg || '').filter(Boolean).join('; ')
        }
      }
    } catch {
      // Non-JSON response, keep default message
    }

    throw new ApiError(response.status, errorCode, errorMessage)
  }

  if (response.status === 204) {
    return {} as T
  }

  return response.json()
}

export const api = {
  // Profiles
  getMyProfile: () => request<Profile>('/profile/me'),
  updateMyProfile: (data: ProfileUpdate) =>
    request<Profile>('/profile/me', {
      method: 'PATCH',
      body: JSON.stringify(data),
    }),

  // Skills
  getMySkills: (ownerUserId: string) =>
    request<{ items: Skill[]; total: number }>(`/skills?owner_user_id=${ownerUserId}&limit=100`),
  getDirectorySkills: (params?: { category?: string; skill_type?: string; search?: string; offset?: number; limit?: number }) => {
    const q = new URLSearchParams()
    if (params?.category) q.set('category', params.category)
    if (params?.skill_type) q.set('skill_type', params.skill_type)
    if (params?.search) q.set('search', params.search)
    if (params?.offset !== undefined) q.set('offset', String(params.offset))
    if (params?.limit !== undefined) q.set('limit', String(params.limit || 20))
    q.set('is_active', 'true')
    return request<{ items: Skill[]; total: number }>(`/skills?${q.toString()}`)
  },
  createSkill: (data: SkillCreate) =>
    request<Skill>('/skills', {
      method: 'POST',
      body: JSON.stringify(data),
    }),
  updateSkill: (id: string, data: SkillUpdate) =>
    request<Skill>(`/skills/${id}`, {
      method: 'PATCH',
      body: JSON.stringify(data),
    }),
  deactivateSkill: (id: string) =>
    request<Skill>(`/skills/${id}`, {
      method: 'DELETE',
    }),

  // Members
  getMemberDetail: (id: string) => request<MemberDetail>(`/members/${id}`),

  // Exchange Requests & Sessions
  getExchangeRequests: (role?: 'incoming' | 'outgoing') => {
    const q = new URLSearchParams()
    if (role) q.set('role', role)
    q.set('limit', '50')
    return request<{ items: ExchangeRequest[]; total: number }>(`/exchange-requests?${q.toString()}`)
  },
  createExchangeRequest: (data: ExchangeRequestCreate) =>
    request<ExchangeRequest>('/exchange-requests', {
      method: 'POST',
      body: JSON.stringify(data),
    }),
  acceptExchangeRequest: (id: string) =>
    request<ExchangeSession>(`/exchange-requests/${id}/accept`, {
      method: 'POST',
    }),
  declineExchangeRequest: (id: string) =>
    request<ExchangeRequest>(`/exchange-requests/${id}/decline`, {
      method: 'POST',
    }),
  cancelExchangeRequest: (id: string) =>
    request<ExchangeRequest>(`/exchange-requests/${id}/cancel`, {
      method: 'POST',
    }),
  getExchangeSession: (id: string) => request<ExchangeSession>(`/exchange-sessions/${id}`),
  getExchangeRequestSession: (requestId: string) =>
    request<ExchangeSession>(`/exchange-requests/${requestId}/session`),
  confirmExchangeSession: (id: string) =>
    request<ExchangeSession>(`/exchange-sessions/${id}/confirm`, {
      method: 'POST',
    }),
  submitSessionReview: (sessionId: string, data: ReviewCreate) =>
    request<ReviewResponse>(`/exchange-sessions/${sessionId}/reviews`, {
      method: 'POST',
      body: JSON.stringify(data),
    }),

  // Dashboard
  getDashboardSummary: () => request<DashboardSummary>('/dashboard/summary'),

  // AI Matches
  getAiSkillMatches: () =>
    request<AiSkillMatchListResponse>('/ai/skill-matches', {
      method: 'POST',
      body: JSON.stringify({}),
    }),
}
