import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { ProfilePage } from '../pages/ProfilePage'
import { MemberDetailPage } from '../pages/MemberDetailPage'
import { RequestsPage } from '../pages/RequestsPage'
import { api } from '../services/api'
import type { MemberDetail, Profile, Skill, ExchangeRequest, ExchangeSession } from '../types/api'

// Mock the AuthContext so we can supply an authenticated user
const mockUser = { id: 'usr-123', email: 'test@example.com' }
vi.mock('../context/AuthContext', () => ({
  useAuth: () => ({
    user: mockUser,
    session: { access_token: 'fake-token' },
    loading: false,
    isConfigured: true,
    signOut: vi.fn(),
  }),
  AuthProvider: ({ children }: { children: React.ReactNode }) => <>{children}</>,
}))

// Mock the api module
vi.mock('../services/api', () => ({
  api: {
    getMyProfile: vi.fn(),
    updateMyProfile: vi.fn(),
    getMySkills: vi.fn(),
    createSkill: vi.fn(),
    updateSkill: vi.fn(),
    deactivateSkill: vi.fn(),
    getMemberDetail: vi.fn(),
    getDirectorySkills: vi.fn(),
    getExchangeRequests: vi.fn(),
    createExchangeRequest: vi.fn(),
    getExchangeRequestSession: vi.fn(),
    cancelExchangeRequest: vi.fn(),
    acceptExchangeRequest: vi.fn(),
    declineExchangeRequest: vi.fn(),
    confirmExchangeSession: vi.fn(),
    submitSessionReview: vi.fn(),
    getDashboardSummary: vi.fn(),
    getAiMatches: vi.fn(),
  },
  ApiError: class extends Error {},
}))

describe('SkillSwap Frontend Integration & Contract Tests', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  describe('ProfilePage: Contract & Skill Management', () => {
    const mockProfile: Profile = {
      user_id: 'usr-123',
      display_name: 'Alice Developer',
      bio: 'Loves TypeScript and Python',
      interests: ['Coding', 'Music'],
      learning_preferences: 'Hands-on practice',
      availability: 'Weekends',
      created_at: '2026-10-01T00:00:00Z',
      updated_at: '2026-10-01T00:00:00Z',
    }

    const mockSkills: Skill[] = [
      {
        id: 'sk-1',
        owner_user_id: 'usr-123',
        skill_name: 'Python',
        category: 'Technology',
        proficiency_level: 'advanced',
        description: 'Backend web services with FastAPI',
        skill_type: 'offered',
        is_active: true,
        created_at: '2026-10-01T00:00:00Z',
        updated_at: '2026-10-01T00:00:00Z',
      },
    ]

    it('saves profile without location field in payload', async () => {
      vi.mocked(api.getMyProfile).mockResolvedValue(mockProfile)
      vi.mocked(api.getMySkills).mockResolvedValue({ items: mockSkills, total: 1 })
      vi.mocked(api.updateMyProfile).mockResolvedValue({ ...mockProfile, bio: 'Updated bio' })

      render(
        <MemoryRouter>
          <ProfilePage />
        </MemoryRouter>
      )

      await waitFor(() => {
        expect(screen.getByDisplayValue('Alice Developer')).toBeInTheDocument()
      })

      // Verify location field does not exist in the DOM
      expect(screen.queryByLabelText(/location/i)).not.toBeInTheDocument()
      expect(screen.queryByPlaceholderText(/city/i)).not.toBeInTheDocument()

      // Submit profile form
      const saveButton = screen.getByRole('button', { name: /save profile/i })
      fireEvent.click(saveButton)

      await waitFor(() => {
        expect(api.updateMyProfile).toHaveBeenCalledTimes(1)
      })

      const callArgs = vi.mocked(api.updateMyProfile).mock.calls[0][0]
      expect(callArgs).toEqual({
        display_name: 'Alice Developer',
        bio: 'Loves TypeScript and Python',
        interests: ['Coding', 'Music'],
        learning_preferences: 'Hands-on practice',
        availability: 'Weekends',
      })
      expect((callArgs as Record<string, unknown>).location).toBeUndefined()
    })

    it('deactivates skill by calling api.deactivateSkill', async () => {
      vi.mocked(api.getMyProfile).mockResolvedValue(mockProfile)
      vi.mocked(api.getMySkills).mockResolvedValue({ items: mockSkills, total: 1 })
      vi.mocked(api.deactivateSkill).mockResolvedValue({ ...mockSkills[0], is_active: false })

      render(
        <MemoryRouter>
          <ProfilePage />
        </MemoryRouter>
      )

      await waitFor(() => {
        expect(screen.getByText('Python')).toBeInTheDocument()
      })

      const deactivateBtn = screen.getByRole('button', { name: /deactivate/i })
      fireEvent.click(deactivateBtn)

      await waitFor(() => {
        expect(api.deactivateSkill).toHaveBeenCalledWith('sk-1')
      })
    })

    it('edits skill details via modal and calls api.updateSkill', async () => {
      vi.mocked(api.getMyProfile).mockResolvedValue(mockProfile)
      vi.mocked(api.getMySkills).mockResolvedValue({ items: mockSkills, total: 1 })
      vi.mocked(api.updateSkill).mockResolvedValue({
        ...mockSkills[0],
        skill_name: 'Python 3.12',
        proficiency_level: 'expert',
      })

      render(
        <MemoryRouter>
          <ProfilePage />
        </MemoryRouter>
      )

      await waitFor(() => {
        expect(screen.getByText('Python')).toBeInTheDocument()
      })

      // Click Edit button
      const editBtn = screen.getByRole('button', { name: /^edit$/i })
      fireEvent.click(editBtn)

      // Modal appears
      expect(screen.getByRole('heading', { name: 'Edit Skill' })).toBeInTheDocument()

      // Change skill name and proficiency level
      const nameInput = screen.getByDisplayValue('Python')
      fireEvent.change(nameInput, { target: { value: 'Python 3.12' } })

      // Save changes in modal
      const saveChangesBtn = screen.getByRole('button', { name: /save changes/i })
      fireEvent.click(saveChangesBtn)

      await waitFor(() => {
        expect(api.updateSkill).toHaveBeenCalledWith('sk-1', {
          skill_name: 'Python 3.12',
          category: 'Technology',
          proficiency_level: 'advanced',
          description: 'Backend web services with FastAPI',
        })
      })
    })
  })

  describe('MemberDetailPage: Skills Derivation Contract', () => {
    const mockMemberDetail: MemberDetail = {
      user_id: 'usr-bob',
      display_name: 'Bob Smith',
      bio: 'Guitar player and chef',
      interests: ['Rock music', 'Italian cuisine'],
      learning_preferences: 'Video calls',
      availability: 'Evenings',
      created_at: '2026-10-01T00:00:00Z',
      updated_at: '2026-10-01T00:00:00Z',
      skills: [
        {
          id: 'sk-bob-1',
          owner_user_id: 'usr-bob',
          skill_name: 'Acoustic Guitar',
          category: 'Music',
          proficiency_level: 'intermediate',
          description: 'Chords and fingerpicking',
          skill_type: 'offered',
          is_active: true,
          created_at: '2026-10-01T00:00:00Z',
          updated_at: '2026-10-01T00:00:00Z',
        },
        {
          id: 'sk-bob-2',
          owner_user_id: 'usr-bob',
          skill_name: 'React and Vite',
          category: 'Technology',
          proficiency_level: 'beginner',
          description: 'Want to build interactive web apps',
          skill_type: 'wanted',
          is_active: true,
          created_at: '2026-10-01T00:00:00Z',
          updated_at: '2026-10-01T00:00:00Z',
        },
      ],
    }

    it('derives and renders offered and wanted skills from skills array', async () => {
      vi.mocked(api.getMemberDetail).mockResolvedValue(mockMemberDetail)

      render(
        <MemoryRouter initialEntries={['/members/usr-bob']}>
          <Routes>
            <Route path="/members/:id" element={<MemberDetailPage />} />
          </Routes>
        </MemoryRouter>
      )

      await waitFor(() => {
        expect(screen.getByText('Bob Smith')).toBeInTheDocument()
      })

      // Offered skills section has Acoustic Guitar
      expect(screen.getByText('Acoustic Guitar')).toBeInTheDocument()
      expect(screen.getByText('Chords and fingerpicking')).toBeInTheDocument()

      // Wanted skills section has React and Vite
      expect(screen.getByText('React and Vite')).toBeInTheDocument()
      expect(screen.getByText('Want to build interactive web apps')).toBeInTheDocument()

      // Confirm no location icon or text is rendered
      expect(screen.queryByText(/📍/)).not.toBeInTheDocument()
    })
  })

  describe('RequestsPage: Contract, Sessions & Cancellation', () => {
    const mockRecipient: MemberDetail = {
      user_id: 'usr-bob',
      display_name: 'Bob Smith',
      bio: 'Guitar player',
      interests: [],
      learning_preferences: 'Online',
      availability: 'Evenings',
      created_at: '2026-10-01T00:00:00Z',
      updated_at: '2026-10-01T00:00:00Z',
      skills: [
        {
          id: 'sk-bob-1',
          owner_user_id: 'usr-bob',
          skill_name: 'Acoustic Guitar',
          category: 'Music',
          proficiency_level: 'intermediate',
          description: 'Chords and rhythm',
          skill_type: 'offered',
          is_active: true,
          created_at: '2026-10-01T00:00:00Z',
          updated_at: '2026-10-01T00:00:00Z',
        },
        {
          id: 'sk-bob-2',
          owner_user_id: 'usr-bob',
          skill_name: 'Past Inactive Skill',
          category: 'Music',
          proficiency_level: 'beginner',
          description: 'Not offered anymore',
          skill_type: 'offered',
          is_active: false,
          created_at: '2026-10-01T00:00:00Z',
          updated_at: '2026-10-01T00:00:00Z',
        },
      ],
    }

    const mockMyOfferedSkills: Skill[] = [
      {
        id: 'sk-alice-1',
        owner_user_id: 'usr-123',
        skill_name: 'Python',
        category: 'Technology',
        proficiency_level: 'advanced',
        description: 'Web APIs',
        skill_type: 'offered',
        is_active: true,
        created_at: '2026-10-01T00:00:00Z',
        updated_at: '2026-10-01T00:00:00Z',
      },
    ]

    const mockAcceptedRequest: ExchangeRequest = {
      id: 'req-acc-1',
      requester_user_id: 'usr-123',
      receiver_user_id: 'usr-bob',
      offered_skill_id: 'sk-alice-1',
      wanted_skill_id: 'sk-bob-1',
      status: 'accepted',
      message: 'Excited to swap Python for Guitar!',
      proposed_datetime: '2026-11-01T15:00:00Z',
      format: 'online',
      created_at: '2026-10-25T10:00:00Z',
      updated_at: '2026-10-26T12:00:00Z',
    }

    const mockSession: ExchangeSession = {
      id: 'sess-12345678',
      request_id: 'req-acc-1',
      completion_status: 'scheduled',
      scheduled_datetime: '2026-11-01T15:00:00Z',
      requester_confirmed_at: null,
      receiver_confirmed_at: null,
      completed_at: null,
      notes: '',
      created_at: '2026-10-26T12:00:00Z',
      updated_at: '2026-10-26T12:00:00Z',
    }

    it('populates recipient active offered skills in new request form', async () => {
      vi.mocked(api.getMemberDetail).mockResolvedValue(mockRecipient)
      vi.mocked(api.getMySkills).mockResolvedValue({ items: mockMyOfferedSkills, total: 1 })

      render(
        <MemoryRouter initialEntries={['/requests?new_with=usr-bob']}>
          <RequestsPage />
        </MemoryRouter>
      )

      await waitFor(() => {
        expect(screen.getByText(/Propose Skill Exchange with Bob Smith/i)).toBeInTheDocument()
      })

      // Recipient's active offered skill is present in options
      expect(screen.getByText(/Acoustic Guitar \(Music - intermediate\)/i)).toBeInTheDocument()
      // Inactive skill is NOT present
      expect(screen.queryByText(/Past Inactive Skill/i)).not.toBeInTheDocument()
    })

    it('fetches session by request id using getExchangeRequestSession and displays details', async () => {
      vi.mocked(api.getExchangeRequests).mockResolvedValue({
        items: [mockAcceptedRequest],
        total: 1,
      })
      vi.mocked(api.getExchangeRequestSession).mockResolvedValue(mockSession)

      render(
        <MemoryRouter initialEntries={['/requests']}>
          <RequestsPage />
        </MemoryRouter>
      )

      await waitFor(() => {
        expect(screen.getByText('View Session Details')).toBeInTheDocument()
      })

      fireEvent.click(screen.getByText('View Session Details'))

      await waitFor(() => {
        expect(api.getExchangeRequestSession).toHaveBeenCalledWith('req-acc-1')
      })

      // Session modal should display session ID and details
      await waitFor(() => {
        expect(screen.getByRole('heading', { name: /Exchange Session/i })).toBeInTheDocument()
        expect(screen.getByRole('button', { name: /Confirm I Completed This Session/i })).toBeInTheDocument()
      })
    })

    it('displays Cancel Request for accepted requests and calls cancelExchangeRequest', async () => {
      vi.mocked(api.getExchangeRequests).mockResolvedValue({
        items: [mockAcceptedRequest],
        total: 1,
      })
      vi.mocked(api.cancelExchangeRequest).mockResolvedValue({
        ...mockAcceptedRequest,
        status: 'cancelled',
      })
      vi.spyOn(window, 'confirm').mockImplementation(() => true)

      render(
        <MemoryRouter initialEntries={['/requests']}>
          <RequestsPage />
        </MemoryRouter>
      )

      await waitFor(() => {
        expect(screen.getByText('Cancel Request')).toBeInTheDocument()
      })

      fireEvent.click(screen.getByText('Cancel Request'))

      await waitFor(() => {
        expect(api.cancelExchangeRequest).toHaveBeenCalledWith('req-acc-1')
      })
    })
  })
})
