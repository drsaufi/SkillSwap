import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { api, ApiError } from '../services/api'
import type { DashboardSummary } from '../types/api'

export function DashboardPage() {
  const [summary, setSummary] = useState<DashboardSummary | null>(null)
  const [loading, setLoading] = useState(true)
  const [errorMsg, setErrorMsg] = useState('')

  useEffect(() => {
    let mounted = true
    api
      .getDashboardSummary()
      .then((data) => {
        if (mounted) {
          setSummary(data)
          setLoading(false)
        }
      })
      .catch((err: unknown) => {
        if (mounted) {
          setErrorMsg(err instanceof ApiError ? err.message : 'Failed to load dashboard summary.')
          setLoading(false)
        }
      })

    return () => {
      mounted = false
    }
  }, [])

  if (loading) {
    return (
      <div className="flex items-center justify-center min-h-[50vh]">
        <div className="animate-spin rounded-full h-10 w-10 border-b-2 border-brand-teal"></div>
      </div>
    )
  }

  if (errorMsg) {
    return (
      <div className="p-6 bg-red-50 border border-red-200 rounded-xl text-red-700 max-w-2xl mx-auto my-8">
        <h3 className="font-bold text-lg mb-1">Dashboard Error</h3>
        <p className="text-sm">{errorMsg}</p>
        <button
          onClick={() => window.location.reload()}
          className="mt-4 px-4 py-2 bg-red-600 text-white rounded-lg text-sm font-semibold hover:bg-red-700"
        >
          Try Again
        </button>
      </div>
    )
  }

  const s = summary || {
    active_offered_skills_count: 0,
    active_wanted_skills_count: 0,
    incoming_pending_requests_count: 0,
    outgoing_pending_requests_count: 0,
    accepted_exchanges_count: 0,
    completed_exchanges_count: 0,
    average_rating: null,
    reviews_received_count: 0,
    upcoming_sessions: [],
  }

  return (
    <div className="space-y-8">
      {/* Welcome header */}
      <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4 pb-2 border-b border-gray-200">
        <div>
          <h1 className="text-2xl sm:text-3xl font-extrabold text-brand-navy">Member Dashboard</h1>
          <p className="text-sm text-gray-600 mt-1">Real-time overview of your skills, exchanges, and schedule</p>
        </div>
        <div className="flex items-center gap-2">
          <Link
            to="/ai-matches"
            className="px-4 py-2 rounded-lg text-sm font-semibold bg-brand-gold text-brand-navy hover:bg-amber-400 transition-colors shadow-sm"
          >
            Find AI Matches
          </Link>
          <Link
            to="/profile"
            className="px-4 py-2 rounded-lg text-sm font-semibold bg-brand-teal text-white hover:bg-teal-700 transition-colors shadow-sm"
          >
            Manage Skills
          </Link>
        </div>
      </div>

      {/* Metrics Grid */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
        <div className="bg-white p-5 rounded-xl border border-gray-200 shadow-sm">
          <span className="text-xs font-semibold text-gray-500 uppercase tracking-wider">Offered Skills</span>
          <div className="text-2xl sm:text-3xl font-extrabold text-brand-teal mt-1">{s.active_offered_skills_count}</div>
          <span className="text-xs text-gray-500 mt-1 block">Active teaching skills</span>
        </div>

        <div className="bg-white p-5 rounded-xl border border-gray-200 shadow-sm">
          <span className="text-xs font-semibold text-gray-500 uppercase tracking-wider">Wanted Skills</span>
          <div className="text-2xl sm:text-3xl font-extrabold text-indigo-600 mt-1">{s.active_wanted_skills_count}</div>
          <span className="text-xs text-gray-500 mt-1 block">Skills you want to learn</span>
        </div>

        <div className="bg-white p-5 rounded-xl border border-gray-200 shadow-sm">
          <span className="text-xs font-semibold text-gray-500 uppercase tracking-wider">Pending Requests</span>
          <div className="text-2xl sm:text-3xl font-extrabold text-amber-500 mt-1">
            {s.incoming_pending_requests_count + s.outgoing_pending_requests_count}
          </div>
          <span className="text-xs text-gray-500 mt-1 block">
            {s.incoming_pending_requests_count} incoming / {s.outgoing_pending_requests_count} outgoing
          </span>
        </div>

        <div className="bg-white p-5 rounded-xl border border-gray-200 shadow-sm">
          <span className="text-xs font-semibold text-gray-500 uppercase tracking-wider">Average Rating</span>
          <div className="text-2xl sm:text-3xl font-extrabold text-brand-navy mt-1">
            {s.average_rating !== null ? `${s.average_rating.toFixed(1)} ★` : '—'}
          </div>
          <span className="text-xs text-gray-500 mt-1 block">
            {s.reviews_received_count} {s.reviews_received_count === 1 ? 'review' : 'reviews'} received
          </span>
        </div>
      </div>

      {/* Exchange Status Progress */}
      <div className="grid md:grid-cols-2 gap-4">
        <div className="bg-white p-5 rounded-xl border border-gray-200 shadow-sm flex items-center justify-between">
          <div>
            <h3 className="font-bold text-gray-900">Accepted Exchanges</h3>
            <p className="text-xs text-gray-500 mt-0.5">Sessions agreed and scheduled</p>
          </div>
          <span className="text-2xl font-black text-brand-teal">{s.accepted_exchanges_count}</span>
        </div>

        <div className="bg-white p-5 rounded-xl border border-gray-200 shadow-sm flex items-center justify-between">
          <div>
            <h3 className="font-bold text-gray-900">Completed Exchanges</h3>
            <p className="text-xs text-gray-500 mt-0.5">Both participants verified</p>
          </div>
          <span className="text-2xl font-black text-emerald-600">{s.completed_exchanges_count}</span>
        </div>
      </div>

      {/* Upcoming Sessions List */}
      <div className="bg-white rounded-xl border border-gray-200 shadow-sm overflow-hidden">
        <div className="p-5 border-b border-gray-200 flex items-center justify-between">
          <div>
            <h2 className="text-lg font-bold text-brand-navy">Upcoming Scheduled Sessions</h2>
            <p className="text-xs text-gray-500 mt-0.5">Your next confirmed learning sessions</p>
          </div>
          <Link to="/requests" className="text-xs font-semibold text-brand-teal hover:underline">
            View All Requests
          </Link>
        </div>

        {s.upcoming_sessions.length === 0 ? (
          <div className="p-8 text-center">
            <p className="text-sm text-gray-500">No upcoming sessions scheduled right now.</p>
            <Link
              to="/explore"
              className="mt-3 inline-block px-4 py-2 rounded-lg text-xs font-semibold bg-gray-100 hover:bg-gray-200 text-gray-800 transition-colors"
            >
              Explore Skills to Request a Swap
            </Link>
          </div>
        ) : (
          <div className="divide-y divide-gray-100">
            {s.upcoming_sessions.map((sess) => (
              <div key={sess.id} className="p-4 sm:p-5 flex flex-col sm:flex-row sm:items-center justify-between gap-3">
                <div className="space-y-1">
                  <div className="flex items-center gap-2">
                    <span className="px-2 py-0.5 text-xs font-semibold rounded bg-teal-50 text-teal-700 border border-teal-200">
                      {sess.completion_status}
                    </span>
                    <span className="text-sm font-bold text-gray-900">
                      {new Date(sess.scheduled_datetime).toLocaleString()}
                    </span>
                  </div>
                  {sess.notes && <p className="text-xs text-gray-600">{sess.notes}</p>}
                </div>
                <Link
                  to="/requests"
                  className="px-3 py-1.5 rounded-lg text-xs font-semibold bg-gray-100 hover:bg-gray-200 text-gray-800 text-center"
                >
                  Manage Session
                </Link>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  )
}
