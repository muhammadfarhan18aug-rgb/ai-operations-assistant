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

  it('consumes streamed chat events and reuses the returned thread ID', async () => {
    const user = userEvent.setup()
    const chatRequests: Array<{ message: string; thread_id?: string }> = []
    const encoder = new TextEncoder()
    localStorage.removeItem('ai-ops-auth-token')
    const fetchMock = vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input)
      if (url.endsWith('/auth/login')) {
        return Promise.resolve({ ok: true, json: async () => ({ access_token: 'demo-token', token_type: 'bearer' }) } as Response)
      }
      if (url.endsWith('/auth/me')) {
        return Promise.resolve({
          ok: true,
          json: async () => ({ id: 7, email: 'ops@cellutech.com', is_admin: false, is_active: true, capabilities: ['inventory:read'] }),
        } as Response)
      }
      if (url.endsWith('/approvals/pending')) {
        return Promise.resolve({ ok: true, json: async () => [] } as Response)
      }
      if (url.endsWith('/chat/stream')) {
        chatRequests.push(JSON.parse(String(init?.body)) as { message: string; thread_id?: string })
        const finalResponse = {
          thread_id: 'persistent-thread-id',
          user_id: 7,
          intent: 'knowledge',
          response: chatRequests.length === 1 ? 'Grounded streamed response' : 'Second streamed response',
          citations: ['Procurement Policy'],
          citation_metadata: [
            {
              document_title: 'Procurement Policy',
              document_identifier: 'policy-procurement-policy',
              filename: 'procurement_policy.md',
              source: 'repository-policy-library',
              version: '1.0',
              section: 'Approval threshold',
            },
          ],
        }
        const body = new ReadableStream<Uint8Array>({
          start(controller) {
            controller.enqueue(encoder.encode('event: status\ndata: {"message":"Classifying request","thread_id":"persistent-thread-id"}\n\n'))
            controller.enqueue(encoder.encode(`event: final\ndata: ${JSON.stringify(finalResponse)}\n\n`))
            controller.close()
          },
        })
        return Promise.resolve({ ok: true, body } as Response)
      }
      return Promise.reject(new Error(`Unexpected fetch: ${url}`))
    })
    vi.stubGlobal('fetch', fetchMock)

    render(<App />)
    await user.type(screen.getByLabelText(/email/i), 'ops@cellutech.com')
    await user.type(screen.getByLabelText(/password/i), 'secret')
    await user.click(screen.getByRole('button', { name: /sign in/i }))
    await screen.findByText(/ops@cellutech.com/i)

    const chatInput = screen.getByLabelText(/new chat message/i)
    await user.type(chatInput, 'What does procurement policy say?')
    await user.click(screen.getByRole('button', { name: /send message/i }))
    expect(await screen.findByText('Grounded streamed response')).toBeInTheDocument()
    expect(
      screen.getByText(/Procurement Policy.*v1\.0.*Approval threshold.*repository-policy-library/),
    ).toBeInTheDocument()
    expect(screen.getByText('Response complete')).toBeInTheDocument()

    await user.clear(chatInput)
    await user.type(chatInput, 'Another question')
    await user.click(screen.getByRole('button', { name: /send message/i }))
    expect(await screen.findByText('Second streamed response')).toBeInTheDocument()
    await waitFor(() => expect(chatRequests).toHaveLength(2))
    expect(chatRequests[0].thread_id).toBeUndefined()
    expect(chatRequests[1].thread_id).toBe('persistent-thread-id')

  localStorage.removeItem('ai-ops-auth-token')
    vi.unstubAllGlobals()
  })
})
