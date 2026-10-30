import { useState, type FormEvent } from 'react'
import { Link, useNavigate, useLocation } from 'react-router-dom'
import { supabase, isSupabaseConfigured } from '../services/supabase'

export function LoginPage() {
  const navigate = useNavigate()
  const location = useLocation()
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [loading, setLoading] = useState(false)
  const [errorMsg, setErrorMsg] = useState('')

  const from = (location.state as { from?: { pathname: string } })?.from?.pathname || '/dashboard'

  const handleLogin = async (e: FormEvent) => {
    e.preventDefault()
    setErrorMsg('')

    if (!isSupabaseConfigured) {
      setErrorMsg('Supabase credentials are not configured. Please check your frontend/.env setup.')
      return
    }

    if (!email.trim() || !password) {
      setErrorMsg('Please enter both email and password.')
      return
    }

    setLoading(true)

    try {
      const { data, error } = await supabase.auth.signInWithPassword({
        email: email.trim(),
        password,
      })

      if (error) {
        setErrorMsg(error.message)
        return
      }

      if (data.session) {
        navigate(from, { replace: true })
      }
    } catch (err: unknown) {
      setErrorMsg(err instanceof Error ? err.message : 'An unexpected login error occurred.')
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="max-w-md mx-auto my-12 p-6 sm:p-8 bg-white border border-gray-200 rounded-2xl shadow-sm">
      <div className="text-center mb-6">
        <h1 className="text-2xl font-bold text-brand-navy">Welcome back</h1>
        <p className="text-sm text-gray-600 mt-1">Sign in to your SkillSwap account</p>
      </div>

      {!isSupabaseConfigured && (
        <div className="mb-6 p-3 bg-amber-50 border border-amber-200 rounded-lg text-xs text-amber-800">
          <strong>Configuration notice:</strong> Live authentication requires valid Supabase environment variables in <code className="font-mono">frontend/.env</code>.
        </div>
      )}

      {errorMsg && (
        <div className="mb-4 p-3 bg-red-50 border border-red-200 rounded-lg text-sm text-red-700">
          {errorMsg}
        </div>
      )}

      <form onSubmit={handleLogin} className="space-y-4">
        <div>
          <label className="block text-xs font-semibold text-gray-700 uppercase tracking-wider mb-1">
            Email Address
          </label>
          <input
            type="email"
            required
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            placeholder="you@example.com"
            className="w-full px-3 py-2 border border-gray-300 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-brand-teal focus:border-transparent"
          />
        </div>

        <div>
          <label className="block text-xs font-semibold text-gray-700 uppercase tracking-wider mb-1">
            Password
          </label>
          <input
            type="password"
            required
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            placeholder="Your password"
            className="w-full px-3 py-2 border border-gray-300 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-brand-teal focus:border-transparent"
          />
        </div>

        <button
          type="submit"
          disabled={loading}
          className="w-full py-2.5 px-4 rounded-lg font-semibold bg-brand-teal text-white hover:bg-teal-700 transition-colors disabled:opacity-50 mt-2 cursor-pointer"
        >
          {loading ? 'Signing in...' : 'Sign In'}
        </button>
      </form>

      <div className="mt-6 text-center text-sm text-gray-600">
        Don&apos;t have an account yet?{' '}
        <Link to="/register" className="font-semibold text-brand-teal hover:underline">
          Join free
        </Link>
      </div>
    </div>
  )
}
