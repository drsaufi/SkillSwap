import { describe, it, expect } from 'vitest'
import { render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { App } from '../App'
import { AuthProvider } from '../context/AuthContext'

describe('SkillSwap Frontend Core Smoke Tests', () => {
  it('renders landing page with headline and calls to action', () => {
    render(
      <MemoryRouter initialEntries={['/']}>
        <AuthProvider>
          <App />
        </AuthProvider>
      </MemoryRouter>
    )

    expect(screen.getByText(/Pure Peer-to-Peer Learning/i)).toBeInTheDocument()
    expect(screen.getByText(/Learn any skill/i)).toBeInTheDocument()
    expect(screen.getByText(/How SkillSwap Works/i)).toBeInTheDocument()
  })

  it('renders register page with form fields', () => {
    render(
      <MemoryRouter initialEntries={['/register']}>
        <AuthProvider>
          <App />
        </AuthProvider>
      </MemoryRouter>
    )

    expect(screen.getByText(/Create your SkillSwap account/i)).toBeInTheDocument()
    expect(screen.getByPlaceholderText(/you@example.com/i)).toBeInTheDocument()
  })

  it('renders login page with form fields', () => {
    render(
      <MemoryRouter initialEntries={['/login']}>
        <AuthProvider>
          <App />
        </AuthProvider>
      </MemoryRouter>
    )

    expect(screen.getByText(/Welcome back/i)).toBeInTheDocument()
    expect(screen.getByPlaceholderText(/Your password/i)).toBeInTheDocument()
  })

  it('protects member-only routes when unauthenticated or unconfigured', () => {
    render(
      <MemoryRouter initialEntries={['/dashboard']}>
        <AuthProvider>
          <App />
        </AuthProvider>
      </MemoryRouter>
    )

    // Unauthenticated or unconfigured shows configuration requirement or login redirect
    const hasConfigNotice = screen.queryByText(/Supabase Configuration Required/i)
    const hasLoginHeading = screen.queryByText(/Welcome back/i)
    expect(hasConfigNotice || hasLoginHeading).toBeTruthy()
  })

  it('protects /explore route when unauthenticated', () => {
    render(
      <MemoryRouter initialEntries={['/explore']}>
        <AuthProvider>
          <App />
        </AuthProvider>
      </MemoryRouter>
    )

    const hasConfigNotice = screen.queryByText(/Supabase Configuration Required/i)
    const hasLoginHeading = screen.queryByText(/Welcome back/i)
    expect(hasConfigNotice || hasLoginHeading).toBeTruthy()
  })

  it('protects /members/:id route when unauthenticated', () => {
    render(
      <MemoryRouter initialEntries={['/members/usr-123']}>
        <AuthProvider>
          <App />
        </AuthProvider>
      </MemoryRouter>
    )

    const hasConfigNotice = screen.queryByText(/Supabase Configuration Required/i)
    const hasLoginHeading = screen.queryByText(/Welcome back/i)
    expect(hasConfigNotice || hasLoginHeading).toBeTruthy()
  })
})
