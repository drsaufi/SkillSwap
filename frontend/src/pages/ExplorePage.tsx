import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { api, ApiError } from '../services/api'
import type { Skill, SkillCategory, SkillType } from '../types/api'

const CATEGORIES: SkillCategory[] = [
  'Technology',
  'Design',
  'Business',
  'Languages',
  'Music',
  'Arts and Crafts',
  'Health and Fitness',
  'Cooking',
  'Academics',
  'Other',
]

export function ExplorePage() {
  const [skills, setSkills] = useState<Skill[]>([])
  const [total, setTotal] = useState(0)
  const [loading, setLoading] = useState(true)
  const [errorMsg, setErrorMsg] = useState('')

  // Filters
  const [search, setSearch] = useState('')
  const [selectedCategory, setSelectedCategory] = useState<string>('')
  const [selectedType, setSelectedType] = useState<string>('')
  const [offset, setOffset] = useState(0)
  const limit = 12

  const fetchSkills = async (newOffset = 0, append = false) => {
    try {
      setLoading(true)
      const res = await api.getDirectorySkills({
        search: search.trim() || undefined,
        category: selectedCategory || undefined,
        skill_type: selectedType || undefined,
        offset: newOffset,
        limit,
      })

      setTotal(res.total)
      if (append) {
        setSkills((prev) => [...prev, ...res.items])
      } else {
        setSkills(res.items)
      }
      setOffset(newOffset)
    } catch (err: unknown) {
      setErrorMsg(err instanceof ApiError ? err.message : 'Failed to load skills directory.')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    fetchSkills(0, false)
  }, [selectedCategory, selectedType])

  const handleSearchSubmit = (e: React.FormEvent) => {
    e.preventDefault()
    fetchSkills(0, false)
  }

  const handleLoadMore = () => {
    fetchSkills(offset + limit, true)
  }

  return (
    <div className="space-y-8">
      <div>
        <h1 className="text-2xl sm:text-3xl font-extrabold text-brand-navy">Explore Skills Directory</h1>
        <p className="text-sm text-gray-600 mt-1">Discover active skills offered and wanted by community members</p>
      </div>

      {/* Filter Controls */}
      <div className="bg-white p-4 sm:p-5 rounded-2xl border border-gray-200 shadow-sm space-y-4">
        <form onSubmit={handleSearchSubmit} className="flex flex-col sm:flex-row gap-3">
          <input
            type="text"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="Search skills by keyword..."
            className="flex-1 px-4 py-2 border border-gray-300 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-brand-teal"
          />
          <button
            type="submit"
            className="px-5 py-2 bg-brand-teal text-white rounded-lg text-sm font-semibold hover:bg-teal-700 transition-colors cursor-pointer"
          >
            Search
          </button>
        </form>

        <div className="flex flex-wrap items-center gap-3 pt-1 border-t border-gray-100 text-xs">
          <span className="font-semibold text-gray-500 uppercase tracking-wider">Filter:</span>
          <select
            value={selectedType}
            onChange={(e) => setSelectedType(e.target.value as SkillType | '')}
            className="px-3 py-1.5 border border-gray-300 rounded-lg bg-white font-medium"
          >
            <option value="">All Skill Types</option>
            <option value="offered">Offered (Can Teach)</option>
            <option value="wanted">Wanted (Wants to Learn)</option>
          </select>

          <select
            value={selectedCategory}
            onChange={(e) => setSelectedCategory(e.target.value as SkillCategory | '')}
            className="px-3 py-1.5 border border-gray-300 rounded-lg bg-white font-medium"
          >
            <option value="">All Categories</option>
            {CATEGORIES.map((c) => (
              <option key={c} value={c}>
                {c}
              </option>
            ))}
          </select>

          {(selectedCategory || selectedType || search) && (
            <button
              onClick={() => {
                setSelectedCategory('')
                setSelectedType('')
                setSearch('')
              }}
              className="text-xs text-brand-teal font-semibold hover:underline cursor-pointer"
            >
              Reset filters
            </button>
          )}
        </div>
      </div>

      {errorMsg && (
        <div className="p-4 bg-red-50 border border-red-200 rounded-xl text-sm text-red-700">
          {errorMsg}
        </div>
      )}

      {/* Skills Grid */}
      {skills.length === 0 && !loading ? (
        <div className="bg-white p-12 text-center rounded-2xl border border-gray-200">
          <p className="text-gray-500 text-sm">No skills found matching your search or filters.</p>
        </div>
      ) : (
        <div className="grid sm:grid-cols-2 lg:grid-cols-3 gap-5">
          {skills.map((skill) => (
            <div
              key={skill.id}
              className="bg-white p-5 rounded-2xl border border-gray-200 shadow-sm hover:shadow-md transition-shadow flex flex-col justify-between"
            >
              <div className="space-y-3">
                <div className="flex items-center justify-between gap-2">
                  <span
                    className={`px-2 py-0.5 rounded text-xs font-bold uppercase tracking-wider ${
                      skill.skill_type === 'offered'
                        ? 'bg-teal-50 text-teal-700 border border-teal-200'
                        : 'bg-indigo-50 text-indigo-700 border border-indigo-200'
                    }`}
                  >
                    {skill.skill_type}
                  </span>
                  <span className="text-xs text-gray-500 font-medium">{skill.category}</span>
                </div>

                <h3 className="text-base font-bold text-gray-900 leading-snug">{skill.skill_name}</h3>

                {skill.description ? (
                  <p className="text-xs text-gray-600 line-clamp-2 leading-relaxed">{skill.description}</p>
                ) : (
                  <p className="text-xs text-gray-400 italic">No additional description provided.</p>
                )}
              </div>

              <div className="pt-4 mt-4 border-t border-gray-100 flex items-center justify-between">
                <span className="text-xs text-gray-500 capitalize font-medium">{skill.proficiency_level}</span>
                <Link
                  to={`/members/${skill.owner_user_id}`}
                  className="text-xs font-semibold text-brand-teal hover:underline flex items-center gap-1"
                >
                  View Member Profile →
                </Link>
              </div>
            </div>
          ))}
        </div>
      )}

      {/* Pagination Load More */}
      {skills.length < total && (
        <div className="text-center pt-4">
          <button
            onClick={handleLoadMore}
            disabled={loading}
            className="px-6 py-2.5 rounded-xl font-semibold bg-white border border-gray-300 text-gray-700 hover:bg-gray-50 transition-colors shadow-sm text-sm cursor-pointer disabled:opacity-50"
          >
            {loading ? 'Loading...' : `Load More (${total - skills.length} remaining)`}
          </button>
        </div>
      )}
    </div>
  )
}
