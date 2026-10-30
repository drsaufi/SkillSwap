import type { ReactNode } from 'react'
import { Navigate, useLocation } from 'react-router-dom'
import { useAuth } from '../context/AuthContext'

export function ProtectedRoute({ children }: { children: ReactNode }) {
  const { user, loading, isConfigured } = useAuth()
  const location = useLocation()

  if (loading) {
    return (
      <div className="flex items-center justify-center min-h-[50vh]">
        <div className="animate-spin rounded-full h-10 w-10 border-b-2 border-brand-teal"></div>
      </div>
    )
  }

  if (!isConfigured) {
    return (
      <div className="max-w-md mx-auto my-12 p-6 bg-white border border-amber-200 rounded-xl shadow-sm text-center">
        <h2 className="text-xl font-bold text-gray-900 mb-2">Supabase Configuration Required</h2>
        <p className="text-sm text-gray-600 mb-4">
          Please add your <code className="bg-gray-100 px-1 py-0.5 rounded text-xs font-mono">VITE_SUPABASE_URL</code> and{' '}
          <code className="bg-gray-100 px-1 py-0.5 rounded text-xs font-mono">VITE_SUPABASE_PUBLISHABLE_KEY</code> in{' '}
          <code className="bg-gray-100 px-1 py-0.5 rounded text-xs font-mono">frontend/.env</code> to access protected member routes.
        </p>
      </div>
    )
  }

  if (!user) {
    return <Navigate to="/login" state={{ from: location }} replace />
  }

  return <>{children}</>
}
