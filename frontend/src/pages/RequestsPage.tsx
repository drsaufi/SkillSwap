import { useEffect, useState, type FormEvent } from 'react'
import { useSearchParams } from 'react-router-dom'
import { api, ApiError } from '../services/api'
import { useAuth } from '../context/AuthContext'
import type {
  ExchangeFormat,
  ExchangeRequest,
  ExchangeRequestCreate,
  ExchangeSession,
  MemberDetail,
  Skill,
} from '../types/api'

export function RequestsPage() {
  const { user } = useAuth()
  const [searchParams] = useSearchParams()
  const targetRecipientId = searchParams.get('new_with')

  const [activeTab, setActiveTab] = useState<'incoming' | 'outgoing' | 'new'>('incoming')
  const [requests, setRequests] = useState<ExchangeRequest[]>([])
  const [loading, setLoading] = useState(true)
  const [errorMsg, setErrorMsg] = useState('')
  const [actionMsg, setActionMsg] = useState('')

  // Selected session modal/drawer
  const [activeSession, setActiveSession] = useState<ExchangeSession | null>(null)
  const [loadingSession, setLoadingSession] = useState(false)

  // Review submission state
  const [reviewRating, setReviewRating] = useState(5)
  const [reviewComment, setReviewComment] = useState('')
  const [submittingReview, setSubmittingReview] = useState(false)
  const [reviewSuccess, setReviewSuccess] = useState('')

  // New Request Form state
  const [myOfferedSkills, setMyOfferedSkills] = useState<Skill[]>([])
  const [recipient, setRecipient] = useState<MemberDetail | null>(null)
  const [selectedMySkill, setSelectedMySkill] = useState('')
  const [selectedTheirSkill, setSelectedTheirSkill] = useState('')
  const [proposedDatetime, setProposedDatetime] = useState('')
  const [format, setFormat] = useState<ExchangeFormat>('online')
  const [message, setMessage] = useState('')
  const [submittingRequest, setSubmittingRequest] = useState(false)

  const loadRequests = async (role: 'incoming' | 'outgoing') => {
    try {
      setLoading(true)
      setErrorMsg('')
      const res = await api.getExchangeRequests(role)
      setRequests(res.items || [])
    } catch (err: unknown) {
      setErrorMsg(err instanceof ApiError ? err.message : 'Failed to load exchange requests.')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    if (targetRecipientId) {
      setActiveTab('new')
      // Fetch recipient details to pick skills
      api.getMemberDetail(targetRecipientId).then(setRecipient).catch(() => {})
      if (user) {
        api.getMySkills(user.id).then((res) => {
          setMyOfferedSkills((res.items || []).filter((s) => s.skill_type === 'offered' && s.is_active))
        })
      }
    } else {
      loadRequests(activeTab === 'outgoing' ? 'outgoing' : 'incoming')
    }
  }, [targetRecipientId])

  useEffect(() => {
    if (activeTab === 'new') {
      if (user) {
        api.getMySkills(user.id).then((res) => {
          setMyOfferedSkills((res.items || []).filter((s) => s.skill_type === 'offered' && s.is_active))
        })
      }
    } else {
      loadRequests(activeTab)
    }
  }, [activeTab])

  const handleCreateRequest = async (e: FormEvent) => {
    e.preventDefault()
    setErrorMsg('')
    setActionMsg('')

    if (!recipient || !selectedMySkill || !selectedTheirSkill || !proposedDatetime || !message.trim()) {
      setErrorMsg('Please complete all required fields.')
      return
    }

    const isoDate = new Date(proposedDatetime).toISOString()

    const payload: ExchangeRequestCreate = {
      receiver_user_id: recipient.user_id,
      offered_skill_id: selectedMySkill,
      wanted_skill_id: selectedTheirSkill,
      message: message.trim(),
      proposed_datetime: isoDate,
      format,
    }

    setSubmittingRequest(true)
    try {
      await api.createExchangeRequest(payload)
      setActionMsg('Exchange request sent successfully!')
      setActiveTab('outgoing')
    } catch (err: unknown) {
      setErrorMsg(err instanceof ApiError ? err.message : 'Failed to send exchange request.')
    } finally {
      setSubmittingRequest(false)
    }
  }

  const handleAccept = async (id: string) => {
    setActionMsg('')
    try {
      const session = await api.acceptExchangeRequest(id)
      setActionMsg('Request accepted! Session has been scheduled.')
      setActiveSession(session)
      loadRequests(activeTab === 'outgoing' ? 'outgoing' : 'incoming')
    } catch (err: unknown) {
      alert(err instanceof ApiError ? err.message : 'Failed to accept request.')
    }
  }

  const handleDecline = async (id: string) => {
    if (!confirm('Decline this exchange request?')) return
    try {
      await api.declineExchangeRequest(id)
      setActionMsg('Request declined.')
      loadRequests(activeTab === 'outgoing' ? 'outgoing' : 'incoming')
    } catch (err: unknown) {
      alert(err instanceof ApiError ? err.message : 'Failed to decline request.')
    }
  }

  const handleCancel = async (id: string) => {
    if (!confirm('Cancel this exchange request?')) return
    try {
      await api.cancelExchangeRequest(id)
      setActionMsg('Request cancelled.')
      loadRequests(activeTab === 'outgoing' ? 'outgoing' : 'incoming')
    } catch (err: unknown) {
      alert(err instanceof ApiError ? err.message : 'Failed to cancel request.')
    }
  }

  const handleViewSession = async (reqId: string) => {
    setLoadingSession(true)
    setActiveSession(null)
    setReviewSuccess('')
    try {
      // Fetch session by request ID using the dedicated endpoint
      const session = await api.getExchangeRequestSession(reqId)
      setActiveSession(session)
    } catch (err: unknown) {
      alert(err instanceof ApiError ? err.message : 'Could not find session details for this request.')
    } finally {
      setLoadingSession(false)
    }
  }

  const handleConfirmCompletion = async (sessionId: string) => {
    try {
      const updated = await api.confirmExchangeSession(sessionId)
      setActiveSession(updated)
      setActionMsg('Completion confirmed! Once both participants confirm, you can review each other.')
      loadRequests(activeTab === 'outgoing' ? 'outgoing' : 'incoming')
    } catch (err: unknown) {
      alert(err instanceof ApiError ? err.message : 'Failed to confirm session.')
    }
  }

  const handleSubmitReview = async (e: FormEvent, sessionId: string) => {
    e.preventDefault()
    setSubmittingReview(true)
    setReviewSuccess('')
    try {
      await api.submitSessionReview(sessionId, {
        rating: reviewRating,
        comment: reviewComment.trim() || undefined,
      })
      setReviewSuccess('Thank you! Your review has been recorded.')
      setReviewComment('')
    } catch (err: unknown) {
      alert(err instanceof ApiError ? err.message : 'Failed to submit review.')
    } finally {
      setSubmittingReview(false)
    }
  }

  return (
    <div className="space-y-8">
      <div>
        <h1 className="text-2xl sm:text-3xl font-extrabold text-brand-navy">Exchange Requests & Sessions</h1>
        <p className="text-sm text-gray-600 mt-1">Manage skill proposals, coordinate schedules, and confirm completed swaps</p>
      </div>

      {actionMsg && (
        <div className="p-4 bg-emerald-50 border border-emerald-200 rounded-xl text-sm text-emerald-800">
          {actionMsg}
        </div>
      )}

      {errorMsg && (
        <div className="p-4 bg-red-50 border border-red-200 rounded-xl text-sm text-red-700">
          {errorMsg}
        </div>
      )}

      {/* Tabs */}
      <div className="flex border-b border-gray-200 gap-4">
        <button
          onClick={() => setActiveTab('incoming')}
          className={`pb-3 text-sm font-bold border-b-2 transition-colors cursor-pointer ${
            activeTab === 'incoming'
              ? 'border-brand-teal text-brand-teal'
              : 'border-transparent text-gray-500 hover:text-gray-700'
          }`}
        >
          Incoming Requests
        </button>
        <button
          onClick={() => setActiveTab('outgoing')}
          className={`pb-3 text-sm font-bold border-b-2 transition-colors cursor-pointer ${
            activeTab === 'outgoing'
              ? 'border-brand-teal text-brand-teal'
              : 'border-transparent text-gray-500 hover:text-gray-700'
          }`}
        >
          Outgoing Requests
        </button>
        {targetRecipientId && (
          <button
            onClick={() => setActiveTab('new')}
            className={`pb-3 text-sm font-bold border-b-2 transition-colors cursor-pointer ${
              activeTab === 'new'
                ? 'border-brand-teal text-brand-teal'
                : 'border-transparent text-gray-500 hover:text-gray-700'
            }`}
          >
            New Request
          </button>
        )}
      </div>

      {/* New Request Tab Content */}
      {activeTab === 'new' && (
        <div className="bg-white p-6 sm:p-8 rounded-2xl border border-gray-200 shadow-sm max-w-2xl space-y-6">
          <h2 className="text-xl font-bold text-brand-navy">
            Propose Skill Exchange {recipient ? `with ${recipient.display_name}` : ''}
          </h2>

          <form onSubmit={handleCreateRequest} className="space-y-4">
            <div>
              <label className="block text-xs font-semibold text-gray-700 uppercase tracking-wider mb-1">
                Your Offered Skill (What you will teach) *
              </label>
              <select
                required
                value={selectedMySkill}
                onChange={(e) => setSelectedMySkill(e.target.value)}
                className="w-full px-3 py-2 border border-gray-300 rounded-lg text-sm bg-white"
              >
                <option value="">Select one of your active offered skills...</option>
                {myOfferedSkills.map((s) => (
                  <option key={s.id} value={s.id}>
                    {s.skill_name} ({s.category} - {s.proficiency_level})
                  </option>
                ))}
              </select>
            </div>

            <div>
              <label className="block text-xs font-semibold text-gray-700 uppercase tracking-wider mb-1">
                Their Offered Skill (What you want to learn) *
              </label>
              <select
                required
                value={selectedTheirSkill}
                onChange={(e) => setSelectedTheirSkill(e.target.value)}
                className="w-full px-3 py-2 border border-gray-300 rounded-lg text-sm bg-white"
              >
                <option value="">Select their skill...</option>
                {(recipient?.skills || [])
                  .filter((s) => s.skill_type === 'offered' && s.is_active)
                  .map((s) => (
                    <option key={s.id} value={s.id}>
                      {s.skill_name} ({s.category} - {s.proficiency_level})
                    </option>
                  ))}
              </select>
            </div>

            <div className="grid sm:grid-cols-2 gap-4">
              <div>
                <label className="block text-xs font-semibold text-gray-700 uppercase tracking-wider mb-1">
                  Proposed Date & Time *
                </label>
                <input
                  type="datetime-local"
                  required
                  value={proposedDatetime}
                  onChange={(e) => setProposedDatetime(e.target.value)}
                  className="w-full px-3 py-2 border border-gray-300 rounded-lg text-sm bg-white"
                />
              </div>

              <div>
                <label className="block text-xs font-semibold text-gray-700 uppercase tracking-wider mb-1">
                  Format *
                </label>
                <select
                  value={format}
                  onChange={(e) => setFormat(e.target.value as ExchangeFormat)}
                  className="w-full px-3 py-2 border border-gray-300 rounded-lg text-sm bg-white"
                >
                  <option value="online">Online (Video/Audio link)</option>
                  <option value="in_person">In Person</option>
                </select>
              </div>
            </div>

            <div>
              <label className="block text-xs font-semibold text-gray-700 uppercase tracking-wider mb-1">
                Introduction Message *
              </label>
              <textarea
                required
                rows={4}
                value={message}
                onChange={(e) => setMessage(e.target.value)}
                placeholder="Introduce yourself, describe your learning goals, and share how you can coordinate the exchange..."
                className="w-full px-3 py-2 border border-gray-300 rounded-lg text-sm"
              />
            </div>

            <button
              type="submit"
              disabled={submittingRequest}
              className="w-full py-2.5 px-4 rounded-lg font-semibold bg-brand-gold text-brand-navy hover:bg-amber-400 transition-colors disabled:opacity-50 cursor-pointer"
            >
              {submittingRequest ? 'Sending Request...' : 'Send Exchange Request'}
            </button>
          </form>
        </div>
      )}

      {/* Requests List */}
      {activeTab !== 'new' && (
        <div className="space-y-4">
          {loading ? (
            <div className="flex items-center justify-center py-12">
              <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-brand-teal"></div>
            </div>
          ) : requests.length === 0 ? (
            <div className="bg-white p-12 text-center rounded-2xl border border-gray-200">
              <p className="text-gray-500 text-sm">No {activeTab} exchange requests found.</p>
            </div>
          ) : (
            <div className="space-y-4">
              {requests.map((req) => (
                <div key={req.id} className="bg-white p-5 sm:p-6 rounded-2xl border border-gray-200 shadow-sm space-y-4">
                  <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-2 border-b border-gray-100 pb-3">
                    <div className="flex items-center gap-3">
                      <span
                        className={`px-2.5 py-0.5 rounded-full text-xs font-bold uppercase tracking-wider ${
                          req.status === 'accepted'
                            ? 'bg-emerald-50 text-emerald-700 border border-emerald-200'
                            : req.status === 'pending'
                            ? 'bg-amber-50 text-amber-700 border border-amber-200'
                            : req.status === 'completed'
                            ? 'bg-blue-50 text-blue-700 border border-blue-200'
                            : 'bg-gray-100 text-gray-600'
                        }`}
                      >
                        {req.status}
                      </span>
                      <span className="text-xs text-gray-500">
                        {new Date(req.created_at).toLocaleDateString()} • {req.format}
                      </span>
                    </div>

                    <div className="text-xs text-gray-600">
                      <strong>Proposed Time:</strong> {new Date(req.proposed_datetime).toLocaleString()}
                    </div>
                  </div>

                  <p className="text-sm text-gray-700 bg-gray-50 p-3.5 rounded-xl italic">&ldquo;{req.message}&rdquo;</p>

                  <div className="flex flex-wrap items-center justify-between gap-3 pt-1">
                    <div className="text-xs text-gray-500">
                      Request ID: <code className="font-mono">{req.id.slice(0, 8)}</code>
                    </div>

                    <div className="flex items-center gap-2">
                      {/* Incoming Pending Actions: Accept or Decline */}
                      {activeTab === 'incoming' && req.status === 'pending' && (
                        <>
                          <button
                            onClick={() => handleAccept(req.id)}
                            className="px-3.5 py-1.5 rounded-lg text-xs font-semibold bg-brand-teal text-white hover:bg-teal-700 transition-colors cursor-pointer"
                          >
                            Accept
                          </button>
                          <button
                            onClick={() => handleDecline(req.id)}
                            className="px-3.5 py-1.5 rounded-lg text-xs font-semibold bg-gray-100 hover:bg-gray-200 text-red-600 transition-colors cursor-pointer"
                          >
                            Decline
                          </button>
                        </>
                      )}

                      {/* Cancel Action: Outgoing Pending OR any Accepted request (either participant) */}
                      {((activeTab === 'outgoing' && req.status === 'pending') || req.status === 'accepted') && (
                        <button
                          onClick={() => handleCancel(req.id)}
                          className="px-3.5 py-1.5 rounded-lg text-xs font-semibold bg-gray-100 hover:bg-gray-200 text-red-600 transition-colors cursor-pointer"
                        >
                          Cancel Request
                        </button>
                      )}

                      {/* Accepted or Completed Action: View Session */}
                      {(req.status === 'accepted' || req.status === 'completed') && (
                        <button
                          onClick={() => handleViewSession(req.id)}
                          className="px-3.5 py-1.5 rounded-lg text-xs font-semibold bg-brand-navy text-white hover:bg-slate-800 transition-colors cursor-pointer"
                        >
                          View Session Details
                        </button>
                      )}
                    </div>
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>
      )}

      {/* Session Modal / Inspection Panel */}
      {loadingSession && (
        <div className="fixed inset-0 bg-black/40 flex items-center justify-center p-4 z-50">
          <div className="bg-white p-6 rounded-2xl shadow-xl flex items-center gap-3">
            <div className="animate-spin rounded-full h-6 w-6 border-b-2 border-brand-teal"></div>
            <span className="text-sm font-semibold">Loading session details...</span>
          </div>
        </div>
      )}

      {activeSession && (
        <div className="fixed inset-0 bg-black/50 flex items-center justify-center p-4 z-50">
          <div className="bg-white rounded-2xl max-w-lg w-full p-6 sm:p-8 space-y-6 shadow-2xl max-h-[90vh] overflow-y-auto">
            <div className="flex items-center justify-between border-b border-gray-100 pb-3">
              <div>
                <h3 className="text-lg font-bold text-brand-navy">Exchange Session</h3>
                <span className="text-xs text-gray-500">Session ID: {activeSession.id.slice(0, 8)}</span>
              </div>
              <button
                onClick={() => setActiveSession(null)}
                className="text-gray-400 hover:text-gray-600 text-lg font-bold"
              >
                ✕
              </button>
            </div>

            <div className="space-y-3 text-sm">
              <div className="flex justify-between py-1 border-b border-gray-100">
                <span className="text-gray-500">Scheduled Time</span>
                <span className="font-semibold text-gray-900">
                  {new Date(activeSession.scheduled_datetime).toLocaleString()}
                </span>
              </div>
              <div className="flex justify-between py-1 border-b border-gray-100">
                <span className="text-gray-500">Completion Status</span>
                <span className="font-bold capitalize text-brand-teal">{activeSession.completion_status}</span>
              </div>
              <div className="flex justify-between py-1 border-b border-gray-100">
                <span className="text-gray-500">Requester Confirmed</span>
                <span className="text-xs text-gray-700">
                  {activeSession.requester_confirmed_at
                    ? new Date(activeSession.requester_confirmed_at).toLocaleString()
                    : 'Pending'}
                </span>
              </div>
              <div className="flex justify-between py-1 border-b border-gray-100">
                <span className="text-gray-500">Receiver Confirmed</span>
                <span className="text-xs text-gray-700">
                  {activeSession.receiver_confirmed_at
                    ? new Date(activeSession.receiver_confirmed_at).toLocaleString()
                    : 'Pending'}
                </span>
              </div>
            </div>

            {/* Confirm Completion Button */}
            {activeSession.completion_status === 'scheduled' && (
              <div className="p-4 bg-teal-50 border border-teal-200 rounded-xl space-y-2">
                <h4 className="text-xs font-bold text-teal-900 uppercase tracking-wider">Confirm Participation</h4>
                <p className="text-xs text-teal-800">
                  Did your session take place? Confirming lets the system know the exchange completed.
                </p>
                <button
                  onClick={() => handleConfirmCompletion(activeSession.id)}
                  className="w-full py-2 px-3 rounded-lg bg-brand-teal text-white font-semibold text-xs hover:bg-teal-700 transition-colors cursor-pointer"
                >
                  Confirm I Completed This Session
                </button>
              </div>
            )}

            {/* Submit Review when Completed */}
            {activeSession.completion_status === 'completed' && (
              <div className="p-5 bg-gray-50 border border-gray-200 rounded-xl space-y-4">
                <h4 className="text-sm font-bold text-gray-900">Leave a Post-Exchange Review</h4>

                {reviewSuccess ? (
                  <p className="text-xs text-emerald-800 bg-emerald-50 border border-emerald-200 p-3 rounded-lg font-medium">
                    {reviewSuccess}
                  </p>
                ) : (
                  <form onSubmit={(e) => handleSubmitReview(e, activeSession.id)} className="space-y-3">
                    <div>
                      <label className="block text-xs font-semibold text-gray-600 mb-1">Rating (1 to 5 stars)</label>
                      <select
                        value={reviewRating}
                        onChange={(e) => setReviewRating(Number(e.target.value))}
                        className="w-full px-3 py-1.5 border border-gray-300 rounded-lg text-sm bg-white"
                      >
                        <option value={5}>⭐⭐⭐⭐⭐ (5 - Excellent)</option>
                        <option value={4}>⭐⭐⭐⭐ (4 - Very Good)</option>
                        <option value={3}>⭐⭐⭐ (3 - Good)</option>
                        <option value={2}>⭐⭐ (2 - Fair)</option>
                        <option value={1}>⭐ (1 - Poor)</option>
                      </select>
                    </div>

                    <div>
                      <label className="block text-xs font-semibold text-gray-600 mb-1">Feedback Comment</label>
                      <textarea
                        rows={3}
                        value={reviewComment}
                        onChange={(e) => setReviewComment(e.target.value)}
                        placeholder="Share your experience learning with this peer..."
                        className="w-full px-3 py-2 border border-gray-300 rounded-lg text-xs"
                      />
                    </div>

                    <button
                      type="submit"
                      disabled={submittingReview}
                      className="w-full py-2 px-3 bg-brand-gold text-brand-navy font-semibold text-xs rounded-lg hover:bg-amber-400 transition-colors disabled:opacity-50 cursor-pointer"
                    >
                      {submittingReview ? 'Submitting...' : 'Submit Review'}
                    </button>
                  </form>
                )}
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  )
}
