import { Link, useNavigate, useLocation } from 'react-router-dom'
import { useAuth } from '../../context/AuthContext'
import { useState } from 'react'

export function Navbar() {
  const { user, signOut, isConfigured } = useAuth()
  const navigate = useNavigate()
  const location = useLocation()
  const [mobileMenuOpen, setMobileMenuOpen] = useState(false)

  const handleSignOut = async () => {
    await signOut()
    navigate('/login')
  }

  const isActive = (path: string) => location.pathname === path

  const navLinks = user
    ? [
        { path: '/dashboard', label: 'Dashboard' },
        { path: '/explore', label: 'Explore Skills' },
        { path: '/requests', label: 'Requests' },
        { path: '/ai-matches', label: 'AI Matches' },
        { path: '/profile', label: 'My Profile' },
      ]
    : [{ path: '/explore', label: 'Explore Skills' }]

  return (
    <header className="bg-brand-navy text-white shadow-md sticky top-0 z-50">
      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
        <div className="flex items-center justify-between h-16">
          <div className="flex items-center gap-3">
            <Link to="/" className="flex items-center gap-2 font-bold text-xl tracking-tight text-white hover:text-brand-gold transition-colors">
              <span className="w-8 h-8 rounded-lg bg-brand-teal flex items-center justify-center text-brand-gold font-black">SS</span>
              <span>SkillSwap</span>
            </Link>
          </div>

          {/* Desktop Nav */}
          <nav className="hidden md:flex items-center gap-1">
            {navLinks.map((link) => (
              <Link
                key={link.path}
                to={link.path}
                className={`px-3 py-2 rounded-md text-sm font-medium transition-colors ${
                  isActive(link.path)
                    ? 'bg-brand-teal text-white'
                    : 'text-gray-200 hover:bg-slate-800 hover:text-white'
                }`}
              >
                {link.label}
              </Link>
            ))}
          </nav>

          <div className="hidden md:flex items-center gap-3">
            {!isConfigured && (
              <span className="text-xs bg-amber-500/20 text-amber-300 border border-amber-500/30 px-2.5 py-1 rounded-full">
                Setup Required
              </span>
            )}

            {user ? (
              <div className="flex items-center gap-3">
                <span className="text-xs text-gray-300 truncate max-w-[160px]">{user.email}</span>
                <button
                  onClick={handleSignOut}
                  className="px-3 py-1.5 rounded-md text-sm font-medium bg-slate-800 hover:bg-slate-700 text-white transition-colors"
                >
                  Log out
                </button>
              </div>
            ) : (
              <div className="flex items-center gap-2">
                <Link
                  to="/login"
                  className="px-3.5 py-1.5 rounded-md text-sm font-medium text-gray-200 hover:text-white hover:bg-slate-800 transition-colors"
                >
                  Log in
                </Link>
                <Link
                  to="/register"
                  className="px-3.5 py-1.5 rounded-md text-sm font-semibold bg-brand-gold text-brand-navy hover:bg-amber-400 transition-colors shadow-sm"
                >
                  Join Free
                </Link>
              </div>
            )}
          </div>

          {/* Mobile menu toggle */}
          <div className="flex md:hidden">
            <button
              onClick={() => setMobileMenuOpen(!mobileMenuOpen)}
              className="p-2 rounded-md text-gray-300 hover:text-white hover:bg-slate-800 focus:outline-none"
              aria-label="Toggle menu"
            >
              <svg className="w-6 h-6" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                {mobileMenuOpen ? (
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
                ) : (
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 6h16M4 12h16M4 18h16" />
                )}
              </svg>
            </button>
          </div>
        </div>
      </div>

      {/* Mobile nav dropdown */}
      {mobileMenuOpen && (
        <div className="md:hidden border-t border-slate-800 px-4 pt-2 pb-4 space-y-1 bg-brand-navy">
          {navLinks.map((link) => (
            <Link
              key={link.path}
              to={link.path}
              onClick={() => setMobileMenuOpen(false)}
              className={`block px-3 py-2 rounded-md text-base font-medium ${
                isActive(link.path)
                  ? 'bg-brand-teal text-white'
                  : 'text-gray-200 hover:bg-slate-800 hover:text-white'
              }`}
            >
              {link.label}
            </Link>
          ))}
          <div className="pt-4 border-t border-slate-800 mt-2 flex flex-col gap-2">
            {user ? (
              <>
                <div className="text-xs text-gray-400 px-3">{user.email}</div>
                <button
                  onClick={() => {
                    setMobileMenuOpen(false)
                    handleSignOut()
                  }}
                  className="w-full text-left px-3 py-2 rounded-md text-base font-medium text-gray-200 hover:bg-slate-800"
                >
                  Log out
                </button>
              </>
            ) : (
              <div className="grid grid-cols-2 gap-2 pt-1">
                <Link
                  to="/login"
                  onClick={() => setMobileMenuOpen(false)}
                  className="text-center px-3 py-2 rounded-md text-sm font-medium bg-slate-800 text-white"
                >
                  Log in
                </Link>
                <Link
                  to="/register"
                  onClick={() => setMobileMenuOpen(false)}
                  className="text-center px-3 py-2 rounded-md text-sm font-semibold bg-brand-gold text-brand-navy"
                >
                  Join Free
                </Link>
              </div>
            )}
          </div>
        </div>
      )}
    </header>
  )
}
