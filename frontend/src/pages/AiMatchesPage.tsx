import { useState } from 'react'
import { Link } from 'react-router-dom'
import { api, ApiError } from '../services/api'
import type { AiSkillMatchItem } from '../types/api'

export function AiMatchesPage() {
  const [matches, setMatches] = useState<AiSkillMatchItem[]>([])
  const [candidateCount, setCandidateCount] = useState<number | null>(null)
  const [loading, setLoading] = useState(false)
  const [errorMsg, setErrorMsg] = useState('')
  const [searched, setSearched] = useState(false)

  const handleFindMatches = async () => {
    setLoading(true)
    setErrorMsg('')
    try {
      const res = await api.getAiSkillMatches()
      setMatches(res.matches || [])
      setCandidateCount(res.candidate_count)
      setSearched(true)
    } catch (err: unknown) {
      if (err instanceof ApiError && err.code === 'ai_unavailable') {
        setErrorMsg('The AI Match Assistant is temporarily unavailable. Please try again later.')
      } else {
        setErrorMsg(err instanceof ApiError ? err.message : 'Failed to retrieve AI matches.')
      }
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="space-y-8 max-w-4xl mx-auto">
      {/* Header */}
      <div className="bg-white p-6 sm:p-8 rounded-2xl border border-gray-200 shadow-sm text-center space-y-4">
        <span className="inline-block px-3 py-1 text-xs font-semibold uppercase tracking-wider text-brand-teal bg-teal-50 border border-teal-200 rounded-full">
          Grounded AI Match Assistant
        </span>
        <h1 className="text-2xl sm:text-3xl font-extrabold text-brand-navy">Find Compatible Skill Matches</h1>
        <p className="text-sm text-gray-600 max-w-2xl mx-auto leading-relaxed">
          The assistant analyzes your active offered and wanted skills against compatible community members.
          Every recommendation is strictly verified against active database records.
        </p>
        <div className="pt-2">
          <button
            onClick={handleFindMatches}
            disabled={loading}
            className="px-6 py-3 rounded-xl font-bold bg-brand-gold text-brand-navy hover:bg-amber-400 transition-all shadow-md disabled:opacity-50 text-sm cursor-pointer inline-flex items-center gap-2"
          >
            {loading ? (
              <>
                <div className="animate-spin rounded-full h-4 w-4 border-b-2 border-brand-navy"></div>
                Analyzing Compatible Matches...
              </>
            ) : (
              'Find My Matches'
            )}
          </button>
        </div>
      </div>

      {/* Error alert */}
      {errorMsg && (
        <div className="p-4 bg-amber-50 border border-amber-200 rounded-xl text-sm text-amber-800 flex items-start gap-3">
          <span className="text-lg">⚠️</span>
          <div>
            <h4 className="font-bold">Match Assistant Notice</h4>
            <p className="text-xs mt-0.5">{errorMsg}</p>
          </div>
        </div>
      )}

      {/* Results Display */}
      {searched && (
        <div className="space-y-6">
          <div className="flex items-center justify-between">
            <h2 className="text-lg font-bold text-brand-navy">
              Top Recommendations ({matches.length})
            </h2>
            {candidateCount !== null && (
              <span className="text-xs text-gray-500">
                Filtered from {candidateCount} active candidate {candidateCount === 1 ? 'member' : 'members'}
              </span>
            )}
          </div>

          {matches.length === 0 ? (
            <div className="bg-white p-10 rounded-2xl border border-gray-200 text-center space-y-3">
              <p className="text-sm text-gray-600">
                No compatible matches found right now based on your active listings.
              </p>
              <p className="text-xs text-gray-400">
                Tip: Add more skills to your profile or broaden your wanted skills and interests to find compatible exchange partners.
              </p>
              <Link
                to="/profile"
                className="inline-block mt-2 px-4 py-2 bg-brand-teal text-white rounded-lg text-xs font-semibold hover:bg-teal-700"
              >
                Update My Profile & Skills
              </Link>
            </div>
          ) : (
            <div className="grid gap-5">
              {matches.map((item, idx) => (
                <div
                  key={idx}
                  className="bg-white p-6 rounded-2xl border border-gray-200 shadow-sm hover:shadow-md transition-shadow space-y-4"
                >
                  <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3">
                    <div className="flex items-center gap-3">
                      <div className="w-10 h-10 rounded-full bg-brand-teal text-white font-bold flex items-center justify-center">
                        {item.display_name.charAt(0).toUpperCase()}
                      </div>
                      <div>
                        <h3 className="font-bold text-gray-900 text-base">{item.display_name}</h3>
                        <span className="text-xs text-gray-500">Verified SkillSwap Member</span>
                      </div>
                    </div>

                    <Link
                      to={`/members/${item.member_user_id}`}
                      className="px-4 py-1.5 rounded-lg text-xs font-semibold bg-brand-teal text-white hover:bg-teal-700 transition-colors text-center"
                    >
                      View Profile & Propose Exchange →
                    </Link>
                  </div>

                  <div className="grid sm:grid-cols-2 gap-3 pt-2">
                    <div className="p-3 bg-teal-50 border border-teal-200 rounded-xl space-y-1">
                      <span className="text-xs font-semibold text-teal-800 uppercase tracking-wider block">
                        They Can Teach You
                      </span>
                      <p className="font-bold text-sm text-gray-900">{item.offered_skill.skill_name}</p>
                      <span className="text-xs text-gray-500">
                        {item.offered_skill.category} • {item.offered_skill.proficiency_level}
                      </span>
                    </div>

                    {item.matching_wanted_skill ? (
                      <div className="p-3 bg-indigo-50 border border-indigo-200 rounded-xl space-y-1">
                        <span className="text-xs font-semibold text-indigo-800 uppercase tracking-wider block">
                          They Want to Learn
                        </span>
                        <p className="font-bold text-sm text-gray-900">{item.matching_wanted_skill.skill_name}</p>
                        <span className="text-xs text-gray-500">
                          {item.matching_wanted_skill.category} • {item.matching_wanted_skill.proficiency_level}
                        </span>
                      </div>
                    ) : (
                      <div className="p-3 bg-gray-50 border border-gray-200 rounded-xl flex items-center">
                        <span className="text-xs text-gray-500 italic">
                          Explore their profile to align your teaching skills.
                        </span>
                      </div>
                    )}
                  </div>

                  <div className="p-3 bg-amber-50/60 border border-amber-200/60 rounded-xl text-xs text-gray-700 leading-relaxed">
                    <strong>Match rationale:</strong> {item.explanation}
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  )
}
