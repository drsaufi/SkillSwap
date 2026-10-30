import { useEffect, useState } from 'react'
import { useParams, Link } from 'react-router-dom'
import { api, ApiError } from '../services/api'
import { useAuth } from '../context/AuthContext'
import type { MemberDetail } from '../types/api'

export function MemberDetailPage() {
  const { id } = useParams<{ id: string }>()
  const { user } = useAuth()
  const [member, setMember] = useState<MemberDetail | null>(null)
  const [loading, setLoading] = useState(true)
  const [errorMsg, setErrorMsg] = useState('')

  useEffect(() => {
    if (!id) return
    let mounted = true
    setLoading(true)

    api
      .getMemberDetail(id)
      .then((data) => {
        if (mounted) {
          setMember(data)
          setLoading(false)
        }
      })
      .catch((err: unknown) => {
        if (mounted) {
          setErrorMsg(err instanceof ApiError ? err.message : 'Failed to load member profile.')
          setLoading(false)
        }
      })

    return () => {
      mounted = false
    }
  }, [id])

  if (loading) {
    return (
      <div className="flex items-center justify-center min-h-[50vh]">
        <div className="animate-spin rounded-full h-10 w-10 border-b-2 border-brand-teal"></div>
      </div>
    )
  }

  if (errorMsg || !member) {
    return (
      <div className="p-8 bg-red-50 border border-red-200 rounded-2xl text-red-700 max-w-xl mx-auto text-center my-10">
        <h2 className="text-lg font-bold mb-2">Member Not Found</h2>
        <p className="text-sm mb-4">{errorMsg || 'Could not locate this member.'}</p>
        <Link to="/explore" className="px-4 py-2 bg-brand-teal text-white rounded-lg text-sm font-semibold">
          Return to Skills Directory
        </Link>
      </div>
    )
  }

  const isOwnProfile = user?.id === member.user_id
  const offeredSkills = (member.skills || []).filter((s) => s.skill_type === 'offered' && s.is_active)
  const wantedSkills = (member.skills || []).filter((s) => s.skill_type === 'wanted' && s.is_active)

  return (
    <div className="space-y-8 max-w-4xl mx-auto">
      {/* Profile Header */}
      <div className="bg-white p-6 sm:p-8 rounded-2xl border border-gray-200 shadow-sm flex flex-col sm:flex-row sm:items-center justify-between gap-6">
        <div className="space-y-2">
          <div className="flex items-center gap-3">
            <div className="w-14 h-14 rounded-full bg-brand-teal text-white font-black text-xl flex items-center justify-center shadow-inner">
              {member.display_name ? member.display_name.charAt(0).toUpperCase() : 'M'}
            </div>
            <div>
              <h1 className="text-2xl font-extrabold text-brand-navy">{member.display_name}</h1>
            </div>
          </div>
          {member.bio && <p className="text-sm text-gray-700 leading-relaxed pt-2">{member.bio}</p>}
        </div>

        <div>
          {isOwnProfile ? (
            <Link
              to="/profile"
              className="px-5 py-2.5 rounded-xl font-semibold bg-gray-100 hover:bg-gray-200 text-gray-800 text-sm transition-colors"
            >
              Edit My Profile
            </Link>
          ) : user ? (
            <Link
              to={`/requests?new_with=${member.user_id}`}
              className="px-5 py-2.5 rounded-xl font-semibold bg-brand-gold text-brand-navy hover:bg-amber-400 transition-colors shadow-sm text-sm"
            >
              Request Skill Exchange
            </Link>
          ) : (
            <Link
              to="/login"
              className="px-5 py-2.5 rounded-xl font-semibold bg-brand-teal text-white hover:bg-teal-700 text-sm"
            >
              Sign In to Request
            </Link>
          )}
        </div>
      </div>

      {/* Preferences & Interests */}
      <div className="grid sm:grid-cols-2 gap-4">
        <div className="bg-white p-5 rounded-xl border border-gray-200 shadow-sm space-y-1">
          <span className="text-xs font-semibold text-gray-500 uppercase tracking-wider">Interests</span>
          <div className="flex flex-wrap gap-1.5 pt-1">
            {member.interests && member.interests.length > 0 ? (
              member.interests.map((int, i) => (
                <span key={i} className="px-2.5 py-0.5 bg-gray-100 text-gray-700 rounded-full text-xs font-medium">
                  {int}
                </span>
              ))
            ) : (
              <span className="text-xs text-gray-400 italic">None listed</span>
            )}
          </div>
        </div>

        <div className="bg-white p-5 rounded-xl border border-gray-200 shadow-sm space-y-1">
          <span className="text-xs font-semibold text-gray-500 uppercase tracking-wider">Availability & Preferences</span>
          <p className="text-xs text-gray-700 pt-1">
            <strong>Availability:</strong> {member.availability || 'Flexible / unstated'}
          </p>
          <p className="text-xs text-gray-700">
            <strong>Learning style:</strong> {member.learning_preferences || 'Flexible'}
          </p>
        </div>
      </div>

      {/* Offered Skills */}
      <div className="space-y-4">
        <h2 className="text-xl font-bold text-brand-navy flex items-center gap-2">
          <span>Offered Skills</span>
          <span className="text-xs bg-teal-100 text-brand-teal px-2 py-0.5 rounded-full font-semibold">
            {offeredSkills.length}
          </span>
        </h2>

        {offeredSkills.length === 0 ? (
          <p className="text-xs text-gray-500 bg-white p-4 rounded-xl border border-gray-200 italic">
            This member currently has no active offered skills listed.
          </p>
        ) : (
          <div className="grid sm:grid-cols-2 gap-4">
            {offeredSkills.map((skill) => (
              <div key={skill.id} className="bg-white p-5 rounded-xl border border-gray-200 shadow-sm space-y-2">
                <div className="flex items-center justify-between">
                  <span className="text-xs text-gray-500 font-medium">{skill.category}</span>
                  <span className="text-xs bg-teal-50 text-teal-700 border border-teal-200 px-2 py-0.5 rounded font-semibold capitalize">
                    {skill.proficiency_level}
                  </span>
                </div>
                <h3 className="font-bold text-gray-900">{skill.skill_name}</h3>
                {skill.description && <p className="text-xs text-gray-600 line-clamp-2">{skill.description}</p>}
              </div>
            ))}
          </div>
        )}
      </div>

      {/* Wanted Skills */}
      <div className="space-y-4">
        <h2 className="text-xl font-bold text-brand-navy flex items-center gap-2">
          <span>Skills Wanted</span>
          <span className="text-xs bg-indigo-100 text-indigo-700 px-2 py-0.5 rounded-full font-semibold">
            {wantedSkills.length}
          </span>
        </h2>

        {wantedSkills.length === 0 ? (
          <p className="text-xs text-gray-500 bg-white p-4 rounded-xl border border-gray-200 italic">
            This member currently has no wanted skills listed.
          </p>
        ) : (
          <div className="grid sm:grid-cols-2 gap-4">
            {wantedSkills.map((skill) => (
              <div key={skill.id} className="bg-white p-5 rounded-xl border border-gray-200 shadow-sm space-y-2">
                <div className="flex items-center justify-between">
                  <span className="text-xs text-gray-500 font-medium">{skill.category}</span>
                  <span className="text-xs bg-indigo-50 text-indigo-700 border border-indigo-200 px-2 py-0.5 rounded font-semibold capitalize">
                    {skill.proficiency_level}
                  </span>
                </div>
                <h3 className="font-bold text-gray-900">{skill.skill_name}</h3>
                {skill.description && <p className="text-xs text-gray-600 line-clamp-2">{skill.description}</p>}
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  )
}
