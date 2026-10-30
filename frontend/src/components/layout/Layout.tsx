import type { ReactNode } from 'react'
import { Navbar } from './Navbar'

export function Layout({ children }: { children: ReactNode }) {
  return (
    <div className="min-h-screen flex flex-col bg-brand-light text-gray-800">
      <Navbar />
      <main className="flex-1 max-w-7xl w-full mx-auto px-4 sm:px-6 lg:px-8 py-8">
        {children}
      </main>
      <footer className="bg-slate-900 text-gray-400 py-6 text-sm border-t border-slate-800">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 flex flex-col sm:flex-row items-center justify-between gap-4">
          <p>© 2026 SkillSwap Platform. Peer-to-peer reciprocal skill exchange.</p>
          <p className="text-xs text-gray-500">FastAPI • Supabase PostgreSQL • React TypeScript • Tailwind CSS</p>
        </div>
      </footer>
    </div>
  )
}
