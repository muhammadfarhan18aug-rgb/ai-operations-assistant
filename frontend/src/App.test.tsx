import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'

import App from './App'

describe('AI Operations Assistant app', () => {
  it('renders the login form before authentication', () => {
    render(<App />)

    expect(screen.getByRole('heading', { name: /ai operations assistant/i })).toBeInTheDocument()
    expect(screen.getByLabelText(/email/i)).toBeInTheDocument()
    expect(screen.getByLabelText(/password/i)).toBeInTheDocument()
  })

  it('logs in and shows user capabilities', async () => {
    const user = userEvent.setup()
    const fetchMock = vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input)
      if (url.endsWith('/auth/login')) {
        return Promise.resolve({
          ok: true,
          json: async () => ({ access_token: 'demo-token', token_type: 'bearer' }),
        } as Response)
      }

      if (url.endsWith('/auth/me')) {
        return Promise.resolve({
          ok: true,
          json: async () => ({
            id: 7,
            email: 'ops@cellutech.com',
            is_admin: false,
            is_active: true,
            capabilities: ['inventory:read', 'order:create', 'email:send'],
          }),
        } as Response)
      }

      if (url.endsWith('/approvals/pending')) {
        return Promise.resolve({
          ok: true,
          json: async () => [],
        } as Response)
      }

      return Promise.reject(new Error(`Unexpected fetch: ${url}`))
    })

    vi.stubGlobal('fetch', fetchMock)

    render(<App />)

    await user.type(screen.getByLabelText(/email/i), 'ops@cellutech.com')
    await user.type(screen.getByLabelText(/password/i), 'secret')
    await user.click(screen.getByRole('button', { name: /sign in/i }))

    await waitFor(() => {
      expect(screen.getByText(/ops@cellutech.com/i)).toBeInTheDocument()
    })

    expect(screen.getByText(/inventory:read/i)).toBeInTheDocument()
    expect(screen.getByText(/order:create/i)).toBeInTheDocument()
    expect(screen.getByText(/email:send/i)).toBeInTheDocument()

    vi.unstubAllGlobals()
  })
})
