import { useEffect, useState, type FormEvent } from 'react'
import { api, ApiError } from '../services/api'
import type { Profile, ProfileUpdate, Skill, SkillCategory, SkillCreate, SkillProficiencyLevel, SkillType, SkillUpdate } from '../types/api'

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

const PROFICIENCIES: SkillProficiencyLevel[] = ['beginner', 'intermediate', 'advanced', 'expert']

export function ProfilePage() {
  const [profile, setProfile] = useState<Profile | null>(null)
  const [skills, setSkills] = useState<Skill[]>([])
  const [loading, setLoading] = useState(true)
  const [errorMsg, setErrorMsg] = useState('')
  const [successMsg, setSuccessMsg] = useState('')

  // Edit profile form state
  const [displayName, setDisplayName] = useState('')
  const [bio, setBio] = useState('')
  const [interestsText, setInterestsText] = useState('')
  const [learningPreferences, setLearningPreferences] = useState('')
  const [availability, setAvailability] = useState('')
  const [savingProfile, setSavingProfile] = useState(false)

  // Add skill form state
  const [newSkillName, setNewSkillName] = useState('')
  const [newCategory, setNewCategory] = useState<SkillCategory>('Technology')
  const [newProficiency, setNewProficiency] = useState<SkillProficiencyLevel>('intermediate')
  const [newSkillType, setNewSkillType] = useState<SkillType>('offered')
  const [newDescription, setNewDescription] = useState('')
  const [savingSkill, setSavingSkill] = useState(false)
  const [skillMsg, setSkillMsg] = useState('')

  // Edit skill modal state
  const [editingSkill, setEditingSkill] = useState<Skill | null>(null)
  const [editSkillName, setEditSkillName] = useState('')
  const [editCategory, setEditCategory] = useState<SkillCategory>('Technology')
  const [editProficiency, setEditProficiency] = useState<SkillProficiencyLevel>('intermediate')
  const [editDescription, setEditDescription] = useState('')
  const [savingEditSkill, setSavingEditSkill] = useState(false)
  const [editSkillError, setEditSkillError] = useState('')

  const loadData = async () => {
    try {
      setLoading(true)
      const prof = await api.getMyProfile()
      setProfile(prof)
      setDisplayName(prof.display_name || '')
      setBio(prof.bio || '')
      setInterestsText((prof.interests || []).join(', '))
      setLearningPreferences(prof.learning_preferences || '')
      setAvailability(prof.availability || '')

      const skList = await api.getMySkills(prof.user_id)
      setSkills(skList.items || [])
    } catch (err: unknown) {
      setErrorMsg(err instanceof ApiError ? err.message : 'Failed to load profile.')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    loadData()
  }, [])

  const handleUpdateProfile = async (e: FormEvent) => {
    e.preventDefault()
    setErrorMsg('')
    setSuccessMsg('')
    setSavingProfile(true)

    const parsedInterests = interestsText
      .split(',')
      .map((s) => s.trim())
      .filter(Boolean)

    const payload: ProfileUpdate = {
      display_name: displayName.trim(),
      bio: bio.trim(),
      interests: parsedInterests,
      learning_preferences: learningPreferences.trim(),
      availability: availability.trim(),
    }

    try {
      const updated = await api.updateMyProfile(payload)
      setProfile(updated)
      setSuccessMsg('Profile saved successfully!')
    } catch (err: unknown) {
      setErrorMsg(err instanceof ApiError ? err.message : 'Failed to update profile.')
    } finally {
      setSavingProfile(false)
    }
  }

  const handleCreateSkill = async (e: FormEvent) => {
    e.preventDefault()
    setSkillMsg('')
    if (!newSkillName.trim()) return

    setSavingSkill(true)
    const payload: SkillCreate = {
      skill_name: newSkillName.trim(),
      category: newCategory,
      proficiency_level: newProficiency,
      skill_type: newSkillType,
      description: newDescription.trim() || undefined,
    }

    try {
      await api.createSkill(payload)
      setNewSkillName('')
      setNewDescription('')
      setSkillMsg('Skill added successfully!')
      if (profile) {
        const skList = await api.getMySkills(profile.user_id)
        setSkills(skList.items || [])
      }
    } catch (err: unknown) {
      setSkillMsg(err instanceof ApiError ? `Error: ${err.message}` : 'Failed to add skill.')
    } finally {
      setSavingSkill(false)
    }
  }

  const handleDeactivateSkill = async (skillId: string) => {
    if (!confirm('Are you sure you want to deactivate this skill? It will no longer appear in new requests or search.')) {
      return
    }
    try {
      await api.deactivateSkill(skillId)
      if (profile) {
        const skList = await api.getMySkills(profile.user_id)
        setSkills(skList.items || [])
      }
    } catch (err: unknown) {
      alert(err instanceof ApiError ? err.message : 'Failed to deactivate skill.')
    }
  }

  const openEditModal = (skill: Skill) => {
    setEditingSkill(skill)
    setEditSkillName(skill.skill_name)
    setEditCategory(skill.category)
    setEditProficiency(skill.proficiency_level)
    setEditDescription(skill.description || '')
    setEditSkillError('')
  }

  const handleSaveSkillEdit = async (e: FormEvent) => {
    e.preventDefault()
    if (!editingSkill) return
    setEditSkillError('')
    setSavingEditSkill(true)

    const payload: SkillUpdate = {
      skill_name: editSkillName.trim(),
      category: editCategory,
      proficiency_level: editProficiency,
      description: editDescription.trim() || undefined,
    }

    try {
      await api.updateSkill(editingSkill.id, payload)
      setEditingSkill(null)
      if (profile) {
        const skList = await api.getMySkills(profile.user_id)
        setSkills(skList.items || [])
      }
    } catch (err: unknown) {
      setEditSkillError(err instanceof ApiError ? err.message : 'Failed to edit skill.')
    } finally {
      setSavingEditSkill(false)
    }
  }

  if (loading) {
    return (
      <div className="flex items-center justify-center min-h-[50vh]">
        <div className="animate-spin rounded-full h-10 w-10 border-b-2 border-brand-teal"></div>
      </div>
    )
  }

  return (
    <div className="space-y-10">
      <div>
        <h1 className="text-2xl sm:text-3xl font-extrabold text-brand-navy">My Profile & Skills</h1>
        <p className="text-sm text-gray-600 mt-1">Manage your public information and list what you teach or want to learn</p>
      </div>

      {errorMsg && (
        <div className="p-4 bg-red-50 border border-red-200 rounded-xl text-sm text-red-700">
          {errorMsg}
        </div>
      )}

      {successMsg && (
        <div className="p-4 bg-emerald-50 border border-emerald-200 rounded-xl text-sm text-emerald-800">
          {successMsg}
        </div>
      )}

      <div className="grid lg:grid-cols-3 gap-8">
        {/* Profile Info Form */}
        <div className="lg:col-span-1 bg-white p-6 rounded-2xl border border-gray-200 shadow-sm h-fit">
          <h2 className="text-lg font-bold text-brand-navy mb-4">Profile Information</h2>
          <form onSubmit={handleUpdateProfile} className="space-y-4">
            <div>
              <label className="block text-xs font-semibold text-gray-700 uppercase tracking-wider mb-1">
                Display Name *
              </label>
              <input
                type="text"
                required
                value={displayName}
                onChange={(e) => setDisplayName(e.target.value)}
                className="w-full px-3 py-2 border border-gray-300 rounded-lg text-sm focus:ring-2 focus:ring-brand-teal focus:outline-none"
              />
            </div>

            <div>
              <label className="block text-xs font-semibold text-gray-700 uppercase tracking-wider mb-1">
                Bio
              </label>
              <textarea
                rows={3}
                value={bio}
                onChange={(e) => setBio(e.target.value)}
                placeholder="Tell peers about your background..."
                className="w-full px-3 py-2 border border-gray-300 rounded-lg text-sm focus:ring-2 focus:ring-brand-teal focus:outline-none"
              />
            </div>

            <div>
              <label className="block text-xs font-semibold text-gray-700 uppercase tracking-wider mb-1">
                Interests (comma separated)
              </label>
              <input
                type="text"
                value={interestsText}
                onChange={(e) => setInterestsText(e.target.value)}
                placeholder="Python, UI Design, Spanish"
                className="w-full px-3 py-2 border border-gray-300 rounded-lg text-sm focus:ring-2 focus:ring-brand-teal focus:outline-none"
              />
            </div>

            <div>
              <label className="block text-xs font-semibold text-gray-700 uppercase tracking-wider mb-1">
                Learning Preferences
              </label>
              <input
                type="text"
                value={learningPreferences}
                onChange={(e) => setLearningPreferences(e.target.value)}
                placeholder="e.g. Hands-on coding sessions"
                className="w-full px-3 py-2 border border-gray-300 rounded-lg text-sm focus:ring-2 focus:ring-brand-teal focus:outline-none"
              />
            </div>

            <div>
              <label className="block text-xs font-semibold text-gray-700 uppercase tracking-wider mb-1">
                Availability
              </label>
              <input
                type="text"
                value={availability}
                onChange={(e) => setAvailability(e.target.value)}
                placeholder="e.g. Weekday evenings, Weekends"
                className="w-full px-3 py-2 border border-gray-300 rounded-lg text-sm focus:ring-2 focus:ring-brand-teal focus:outline-none"
              />
            </div>

            <button
              type="submit"
              disabled={savingProfile}
              className="w-full py-2.5 px-4 rounded-lg font-semibold bg-brand-teal text-white hover:bg-teal-700 transition-colors disabled:opacity-50 cursor-pointer"
            >
              {savingProfile ? 'Saving...' : 'Save Profile'}
            </button>
          </form>
        </div>

        {/* Skills Section */}
        <div className="lg:col-span-2 space-y-6">
          {/* Add Skill Card */}
          <div className="bg-white p-6 rounded-2xl border border-gray-200 shadow-sm">
            <h2 className="text-lg font-bold text-brand-navy mb-4">Add a Skill</h2>

            {skillMsg && (
              <div className={`p-3 rounded-lg text-xs mb-4 ${skillMsg.startsWith('Error') ? 'bg-red-50 text-red-700 border border-red-200' : 'bg-emerald-50 text-emerald-800 border border-emerald-200'}`}>
                {skillMsg}
              </div>
            )}

            <form onSubmit={handleCreateSkill} className="space-y-4">
              <div className="grid sm:grid-cols-2 gap-4">
                <div>
                  <label className="block text-xs font-semibold text-gray-700 uppercase tracking-wider mb-1">
                    Skill Name *
                  </label>
                  <input
                    type="text"
                    required
                    value={newSkillName}
                    onChange={(e) => setNewSkillName(e.target.value)}
                    placeholder="e.g. Modern React with TypeScript"
                    className="w-full px-3 py-2 border border-gray-300 rounded-lg text-sm focus:ring-2 focus:ring-brand-teal focus:outline-none"
                  />
                </div>

                <div>
                  <label className="block text-xs font-semibold text-gray-700 uppercase tracking-wider mb-1">
                    Category *
                  </label>
                  <select
                    value={newCategory}
                    onChange={(e) => setNewCategory(e.target.value as SkillCategory)}
                    className="w-full px-3 py-2 border border-gray-300 rounded-lg text-sm focus:ring-2 focus:ring-brand-teal focus:outline-none bg-white"
                  >
                    {CATEGORIES.map((c) => (
                      <option key={c} value={c}>
                        {c}
                      </option>
                    ))}
                  </select>
                </div>
              </div>

              <div className="grid sm:grid-cols-2 gap-4">
                <div>
                  <label className="block text-xs font-semibold text-gray-700 uppercase tracking-wider mb-1">
                    Skill Type *
                  </label>
                  <select
                    value={newSkillType}
                    onChange={(e) => setNewSkillType(e.target.value as SkillType)}
                    className="w-full px-3 py-2 border border-gray-300 rounded-lg text-sm focus:ring-2 focus:ring-brand-teal focus:outline-none bg-white font-medium"
                  >
                    <option value="offered">Offered (I can teach this)</option>
                    <option value="wanted">Wanted (I want to learn this)</option>
                  </select>
                </div>

                <div>
                  <label className="block text-xs font-semibold text-gray-700 uppercase tracking-wider mb-1">
                    Proficiency Level *
                  </label>
                  <select
                    value={newProficiency}
                    onChange={(e) => setNewProficiency(e.target.value as SkillProficiencyLevel)}
                    className="w-full px-3 py-2 border border-gray-300 rounded-lg text-sm focus:ring-2 focus:ring-brand-teal focus:outline-none bg-white capitalize"
                  >
                    {PROFICIENCIES.map((p) => (
                      <option key={p} value={p}>
                        {p}
                      </option>
                    ))}
                  </select>
                </div>
              </div>

              <div>
                <label className="block text-xs font-semibold text-gray-700 uppercase tracking-wider mb-1">
                  Description
                </label>
                <input
                  type="text"
                  value={newDescription}
                  onChange={(e) => setNewDescription(e.target.value)}
                  placeholder="Short note on what you can cover or hope to practice..."
                  className="w-full px-3 py-2 border border-gray-300 rounded-lg text-sm focus:ring-2 focus:ring-brand-teal focus:outline-none"
                />
              </div>

              <button
                type="submit"
                disabled={savingSkill}
                className="py-2 px-5 rounded-lg font-semibold bg-brand-gold text-brand-navy hover:bg-amber-400 transition-colors disabled:opacity-50 cursor-pointer text-sm"
              >
                {savingSkill ? 'Adding...' : 'Add Skill'}
              </button>
            </form>
          </div>

          {/* Existing Skills List */}
          <div className="bg-white p-6 rounded-2xl border border-gray-200 shadow-sm space-y-4">
            <h2 className="text-lg font-bold text-brand-navy">Your Skills Listings ({skills.length})</h2>

            {skills.length === 0 ? (
              <p className="text-sm text-gray-500 py-4 text-center">
                You haven&apos;t added any skills yet. Add at least one offered skill so other members can exchange with you!
              </p>
            ) : (
              <div className="space-y-3">
                {skills.map((sk) => (
                  <div
                    key={sk.id}
                    className={`p-4 rounded-xl border flex flex-col sm:flex-row sm:items-center justify-between gap-3 ${sk.is_active ? 'bg-white border-gray-200' : 'bg-gray-50 border-gray-200 opacity-60'}`}
                  >
                    <div className="space-y-1">
                      <div className="flex items-center gap-2 flex-wrap">
                        <span
                          className={`px-2 py-0.5 rounded text-xs font-bold uppercase ${sk.skill_type === 'offered' ? 'bg-teal-50 text-teal-700 border border-teal-200' : 'bg-indigo-50 text-indigo-700 border border-indigo-200'}`}
                        >
                          {sk.skill_type}
                        </span>
                        <span className="font-bold text-gray-900">{sk.skill_name}</span>
                        <span className="text-xs bg-gray-100 text-gray-600 px-2 py-0.5 rounded">
                          {sk.category}
                        </span>
                        <span className="text-xs text-gray-500 capitalize">• {sk.proficiency_level}</span>
                      </div>
                      {sk.description && <p className="text-xs text-gray-600">{sk.description}</p>}
                    </div>

                    <div className="flex items-center gap-2">
                      <span className={`text-xs font-semibold ${sk.is_active ? 'text-emerald-600' : 'text-gray-500'}`}>
                        {sk.is_active ? 'Active' : 'Inactive'}
                      </span>
                      {sk.is_active && (
                        <>
                          <button
                            onClick={() => openEditModal(sk)}
                            className="px-3 py-1 rounded text-xs font-medium border border-gray-300 hover:bg-gray-100 transition-colors cursor-pointer"
                          >
                            Edit
                          </button>
                          <button
                            onClick={() => handleDeactivateSkill(sk.id)}
                            className="px-3 py-1 rounded text-xs font-medium border border-red-200 text-red-600 hover:bg-red-50 transition-colors cursor-pointer"
                          >
                            Deactivate
                          </button>
                        </>
                      )}
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>
        </div>
      </div>

      {/* Edit Skill Modal */}
      {editingSkill && (
        <div className="fixed inset-0 bg-black/50 flex items-center justify-center p-4 z-50">
          <div className="bg-white rounded-2xl max-w-lg w-full p-6 sm:p-8 space-y-4 shadow-xl">
            <div className="flex items-center justify-between border-b border-gray-100 pb-2">
              <h3 className="text-lg font-bold text-brand-navy">Edit Skill</h3>
              <button
                onClick={() => setEditingSkill(null)}
                className="text-gray-400 hover:text-gray-600 font-bold"
              >
                ✕
              </button>
            </div>

            {editSkillError && (
              <div className="p-3 bg-red-50 border border-red-200 rounded-lg text-xs text-red-700">
                {editSkillError}
              </div>
            )}

            <form onSubmit={handleSaveSkillEdit} className="space-y-4">
              <div>
                <label className="block text-xs font-semibold text-gray-700 mb-1">Skill Name *</label>
                <input
                  type="text"
                  required
                  value={editSkillName}
                  onChange={(e) => setEditSkillName(e.target.value)}
                  className="w-full px-3 py-2 border border-gray-300 rounded-lg text-sm"
                />
              </div>

              <div className="grid sm:grid-cols-2 gap-4">
                <div>
                  <label className="block text-xs font-semibold text-gray-700 mb-1">Category *</label>
                  <select
                    value={editCategory}
                    onChange={(e) => setEditCategory(e.target.value as SkillCategory)}
                    className="w-full px-3 py-2 border border-gray-300 rounded-lg text-sm bg-white"
                  >
                    {CATEGORIES.map((c) => (
                      <option key={c} value={c}>{c}</option>
                    ))}
                  </select>
                </div>

                <div>
                  <label className="block text-xs font-semibold text-gray-700 mb-1">Proficiency Level *</label>
                  <select
                    value={editProficiency}
                    onChange={(e) => setEditProficiency(e.target.value as SkillProficiencyLevel)}
                    className="w-full px-3 py-2 border border-gray-300 rounded-lg text-sm bg-white capitalize"
                  >
                    {PROFICIENCIES.map((p) => (
                      <option key={p} value={p}>{p}</option>
                    ))}
                  </select>
                </div>
              </div>

              <div>
                <label className="block text-xs font-semibold text-gray-700 mb-1">Description</label>
                <textarea
                  rows={3}
                  value={editDescription}
                  onChange={(e) => setEditDescription(e.target.value)}
                  className="w-full px-3 py-2 border border-gray-300 rounded-lg text-sm"
                />
              </div>

              <div className="flex justify-end gap-2 pt-2">
                <button
                  type="button"
                  onClick={() => setEditingSkill(null)}
                  className="px-4 py-2 border border-gray-300 rounded-lg text-xs font-medium text-gray-700 hover:bg-gray-50"
                >
                  Cancel
                </button>
                <button
                  type="submit"
                  disabled={savingEditSkill}
                  className="px-4 py-2 bg-brand-teal text-white rounded-lg text-xs font-semibold hover:bg-teal-700 disabled:opacity-50"
                >
                  {savingEditSkill ? 'Saving...' : 'Save Changes'}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}
    </div>
  )
}
