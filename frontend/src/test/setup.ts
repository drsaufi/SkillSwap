import '@testing-library/jest-dom/vitest'
import { vi } from 'vitest'

window.confirm = vi.fn(() => true)
window.alert = vi.fn()
