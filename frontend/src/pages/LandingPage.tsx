import { Link } from 'react-router-dom'
import { useAuth } from '../context/AuthContext'

export function LandingPage() {
  const { user } = useAuth()

  return (
    <div className="space-y-16 py-6">
      {/* Hero Section */}
      <section className="text-center max-w-3xl mx-auto space-y-6 pt-6 sm:pt-12">
        <span className="inline-block px-3 py-1 text-xs font-semibold uppercase tracking-wider text-brand-teal bg-teal-50 border border-teal-200 rounded-full">
          Pure Peer-to-Peer Learning
        </span>
        <h1 className="text-4xl sm:text-5xl font-extrabold text-brand-navy tracking-tight leading-tight">
          Learn any skill. <br />
          <span className="text-brand-teal">Teach what you know.</span> No money exchanged.
        </h1>
        <p className="text-lg text-gray-600 leading-relaxed">
          SkillSwap is a reciprocal peer-learning platform where members swap knowledge directly.
          Offer a skill you excel in, find someone who wants to learn it, and learn their skill in return.
        </p>
        <div className="flex flex-col sm:flex-row items-center justify-center gap-3 pt-2">
          {user ? (
            <Link
              to="/dashboard"
              className="w-full sm:w-auto px-6 py-3 rounded-lg font-semibold bg-brand-teal text-white hover:bg-teal-700 shadow-md transition-all text-center"
            >
              Go to Your Dashboard
            </Link>
          ) : (
            <>
              <Link
                to="/register"
                className="w-full sm:w-auto px-6 py-3 rounded-lg font-semibold bg-brand-gold text-brand-navy hover:bg-amber-400 shadow-md transition-all text-center"
              >
                Get Started Free
              </Link>
              <Link
                to="/explore"
                className="w-full sm:w-auto px-6 py-3 rounded-lg font-semibold bg-white text-gray-700 border border-gray-300 hover:bg-gray-50 transition-all text-center"
              >
                Explore Skills Directory
              </Link>
            </>
          )}
        </div>
      </section>

      {/* How it Works Section */}
      <section className="max-w-5xl mx-auto">
        <div className="text-center mb-10">
          <h2 className="text-2xl sm:text-3xl font-bold text-brand-navy">How SkillSwap Works</h2>
          <p className="text-gray-600 mt-2">Three straightforward steps to reciprocal learning.</p>
        </div>

        <div className="grid md:grid-cols-3 gap-8">
          <div className="bg-white p-6 rounded-xl border border-gray-200 shadow-sm hover:shadow-md transition-shadow">
            <div className="w-12 h-12 bg-teal-100 text-brand-teal font-bold text-xl rounded-lg flex items-center justify-center mb-4">
              1
            </div>
            <h3 className="text-lg font-bold text-gray-900 mb-2">List Your Skills</h3>
            <p className="text-sm text-gray-600">
              Create your profile. List skills you can share and skills you are excited to learn across Technology, Languages, Design, and more.
            </p>
          </div>

          <div className="bg-white p-6 rounded-xl border border-gray-200 shadow-sm hover:shadow-md transition-shadow">
            <div className="w-12 h-12 bg-teal-100 text-brand-teal font-bold text-xl rounded-lg flex items-center justify-center mb-4">
              2
            </div>
            <h3 className="text-lg font-bold text-gray-900 mb-2">Request an Exchange</h3>
            <p className="text-sm text-gray-600">
              Explore the directory or tap the AI Match Assistant to find compatible peers. Propose a date, time, and session format (online or in person).
            </p>
          </div>

          <div className="bg-white p-6 rounded-xl border border-gray-200 shadow-sm hover:shadow-md transition-shadow">
            <div className="w-12 h-12 bg-teal-100 text-brand-teal font-bold text-xl rounded-lg flex items-center justify-center mb-4">
              3
            </div>
            <h3 className="text-lg font-bold text-gray-900 mb-2">Learn & Review</h3>
            <p className="text-sm text-gray-600">
              Meet and share your knowledge. Both participants confirm completion in the app and exchange feedback to build a verified reputation.
            </p>
          </div>
        </div>
      </section>

      {/* Key Features Banner */}
      <section className="bg-brand-navy text-white rounded-2xl p-8 sm:p-12 text-center max-w-4xl mx-auto space-y-4 shadow-lg">
        <h2 className="text-2xl sm:text-3xl font-bold">Grounded AI Match Assistant</h2>
        <p className="text-gray-300 max-w-2xl mx-auto text-sm sm:text-base leading-relaxed">
          Our built-in match assistant suggests compatible peers based on reciprocal offerings and learning interests.
          Every recommendation is strictly grounded in real, active database records.
        </p>
        <div className="pt-2">
          <Link
            to={user ? '/ai-matches' : '/register'}
            className="inline-block px-6 py-2.5 rounded-lg font-semibold bg-brand-gold text-brand-navy hover:bg-amber-400 transition-colors"
          >
            Try Match Assistant
          </Link>
        </div>
      </section>
    </div>
  )
}
