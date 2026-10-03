import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'

import App from './App'

beforeEach(() => {
  window.history.replaceState({}, '', '/')
})

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
            email: 'ali@assistant.test',
            is_admin: false,
            is_active: true,
            capabilities: ['policy:read', 'inventory:read'],
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

    await user.type(screen.getByLabelText(/email/i), 'ali@assistant.test')
    await user.type(screen.getByLabelText(/password/i), 'secret')
    await user.click(screen.getByRole('button', { name: /sign in/i }))

    await waitFor(() => {
      expect(screen.getByText(/ali@assistant.test/i)).toBeInTheDocument()
    })

    expect(screen.getByText(/inventory:read/i)).toBeInTheDocument()
    expect(screen.getByText(/policy:read/i)).toBeInTheDocument()

    vi.unstubAllGlobals()
  })

  it('consumes streamed chat events and reuses the returned thread ID', async () => {
    const user = userEvent.setup()
    const chatRequests: Array<{ message: string; thread_id?: string }> = []
    const encoder = new TextEncoder()
    const fetchMock = vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input)
      if (url.endsWith('/auth/login')) {
        return Promise.resolve({ ok: true, json: async () => ({ access_token: 'demo-token', token_type: 'bearer' }) } as Response)
      }
      if (url.endsWith('/auth/me')) {
        return Promise.resolve({
          ok: true,
          json: async () => ({ id: 7, email: 'ali@assistant.test', is_admin: false, is_active: true, capabilities: ['inventory:read'] }),
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
            controller.enqueue(encoder.encode('event: routing\ndata: {"route":"knowledge","steps":[]}\n\n'))
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
    await user.type(screen.getByLabelText(/email/i), 'ali@assistant.test')
    await user.type(screen.getByLabelText(/password/i), 'secret')
    await user.click(screen.getByRole('button', { name: /sign in/i }))
    await screen.findByText(/ali@assistant.test/i)

    const chatInput = screen.getByLabelText(/new chat message/i)
    await user.type(chatInput, 'What does procurement policy say?')
    await user.click(screen.getByRole('button', { name: /send message/i }))
    expect(await screen.findByText('Grounded streamed response')).toBeInTheDocument()
    expect(
      screen.getByText(/Procurement Policy.*v1\.0.*Approval threshold.*repository-policy-library/),
    ).toBeInTheDocument()
    expect(screen.getByText('Response complete')).toBeInTheDocument()
    expect(screen.getByText('Routed to knowledge')).toBeInTheDocument()

    await user.clear(chatInput)
    await user.type(chatInput, 'Another question')
    await user.click(screen.getByRole('button', { name: /send message/i }))
    expect(await screen.findByText('Second streamed response')).toBeInTheDocument()
    await waitFor(() => expect(chatRequests).toHaveLength(2))
    expect(chatRequests[0].thread_id).toBeUndefined()
    expect(chatRequests[1].thread_id).toBe('persistent-thread-id')

    expect(localStorage.getItem('ai-ops-auth-token')).toBeNull()
    expect(sessionStorage.getItem('ai-ops-auth-token')).toBeNull()
    expect(fetchMock).toHaveBeenCalledWith(expect.anything(), expect.objectContaining({ credentials: 'include' }))
    vi.unstubAllGlobals()
  })

  it('appends assistant_delta chunks while the SSE response is still open', async () => {
    const user = userEvent.setup()
    const encoder = new TextEncoder()
    let releaseStream: (() => void) | null = null
    const streamGate = new Promise<void>((resolve) => { releaseStream = resolve })
    const finalResponse = {
      thread_id: 'delta-thread',
      user_id: 1,
      intent: 'knowledge',
      response: 'Partial answer',
      citations: [],
    }
    const fetchMock = vi.fn((input: RequestInfo | URL) => {
      const url = String(input)
      if (url.endsWith('/auth/login')) return Promise.resolve({ ok: true, json: async () => ({ access_token: 'ignored' }) } as Response)
      if (url.endsWith('/auth/me')) return Promise.resolve({ ok: true, json: async () => ({ id: 1, email: 'admin@assistant.test', is_admin: true, is_active: true, capabilities: ['policy:read'] }) } as Response)
      if (url.endsWith('/approvals/pending')) return Promise.resolve({ ok: true, json: async () => [] } as Response)
      if (url.endsWith('/chat/stream')) {
        const body = new ReadableStream<Uint8Array>({
          start(controller) {
            controller.enqueue(encoder.encode('event: status\ndata: {"message":"Classifying request","thread_id":"delta-thread"}\n\n'))
            controller.enqueue(encoder.encode('event: assistant_delta\ndata: {"content":"Partial ","thread_id":"delta-thread"}\n\n'))
            controller.enqueue(encoder.encode('event: assistant_delta\ndata: {"content":"answer","thread_id":"delta-thread"}\n\n'))
            void streamGate.then(() => {
              controller.enqueue(encoder.encode(`event: final\ndata: ${JSON.stringify(finalResponse)}\n\n`))
              controller.close()
            })
          },
        })
        return Promise.resolve({ ok: true, body } as Response)
      }
      return Promise.reject(new Error(`Unexpected fetch: ${url}`))
    })
    vi.stubGlobal('fetch', fetchMock)

    render(<App />)
    await user.type(screen.getByLabelText(/email/i), 'admin@assistant.test')
    await user.type(screen.getByLabelText(/password/i), 'secret')
    await user.click(screen.getByRole('button', { name: /sign in/i }))
    await screen.findByText(/admin@assistant.test/i)
    await user.type(screen.getByLabelText(/new chat message/i), 'What does policy say?')
    await user.click(screen.getByRole('button', { name: /send message/i }))

    expect(await screen.findByText('Partial answer')).toBeInTheDocument()
    expect(screen.queryByText('Response complete')).not.toBeInTheDocument()
    releaseStream?.()
    expect(await screen.findByText('Response complete')).toBeInTheDocument()
    vi.unstubAllGlobals()
  })

  it('edits pending purchase-order fields and resumes with the edited arguments', async () => {
    const user = userEvent.setup()
    const pendingApproval = {
      id: 31,
      user_id: 7,
      thread_id: 'thread-31',
      tool_name: 'purchase_order_create',
      action_args: { sku: 'SKU-1043', quantity: 80, supplier: 'Northstar Supply' },
      status: 'PENDING',
      created_at: '2026-10-03T10:00:00Z',
      updated_at: '2026-10-03T10:00:00Z',
    }
    let hasPending = true
    let submittedBody: Record<string, unknown> | null = null
    const fetchMock = vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input)
      if (url.endsWith('/auth/login')) {
        return Promise.resolve({ ok: true, json: async () => ({ access_token: 'ignored', token_type: 'bearer' }) } as Response)
      }
      if (url.endsWith('/auth/me')) {
        return Promise.resolve({ ok: true, json: async () => ({ id: 7, email: 'admin@assistant.test', is_admin: true, is_active: true, capabilities: [] }) } as Response)
      }
      if (url.endsWith('/approvals/pending')) {
        return Promise.resolve({ ok: true, json: async () => hasPending ? [pendingApproval] : [] } as Response)
      }
      if (url.endsWith('/approvals/31/approve')) {
        submittedBody = JSON.parse(String(init?.body)) as Record<string, unknown>
        hasPending = false
        return Promise.resolve({ ok: true, json: async () => ({ ...pendingApproval, status: 'EXECUTED' }) } as Response)
      }
      return Promise.reject(new Error(`Unexpected fetch: ${url}`))
    })
    vi.stubGlobal('fetch', fetchMock)

    render(<App />)
    await user.type(screen.getByLabelText(/email/i), 'admin@assistant.test')
    await user.type(screen.getByLabelText(/password/i), 'secret')
    await user.click(screen.getByRole('button', { name: /sign in/i }))

    const quantity = await screen.findByLabelText('quantity for approval 31')
    await user.clear(quantity)
    await user.type(quantity, '60')
    await user.click(screen.getByRole('button', { name: /edit and approve/i }))

    await waitFor(() => expect(submittedBody?.action_args).toEqual({
      sku: 'SKU-1043',
      quantity: 60,
      supplier: 'Northstar Supply',
    }))
    vi.unstubAllGlobals()
  })

  it('renders editable email approval fields and submits the edited body', async () => {
    const user = userEvent.setup()
    const pendingApproval = {
      id: 32,
      user_id: 1,
      thread_id: 'thread-32',
      tool_name: 'email_send',
      action_args: { recipient: 'admin@assistant.test', subject: 'Original', body: 'Original body' },
      status: 'PENDING',
      created_at: '2026-10-03T10:00:00Z',
      updated_at: '2026-10-03T10:00:00Z',
    }
    let submittedBody: Record<string, unknown> | null = null
    const fetchMock = vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input)
      if (url.endsWith('/auth/login')) return Promise.resolve({ ok: true, json: async () => ({ access_token: 'ignored' }) } as Response)
      if (url.endsWith('/auth/me')) return Promise.resolve({ ok: true, json: async () => ({ id: 1, email: 'admin@assistant.test', is_admin: true, is_active: true, capabilities: [] }) } as Response)
      if (url.endsWith('/approvals/pending')) return Promise.resolve({ ok: true, json: async () => [pendingApproval] } as Response)
      if (url.endsWith('/approvals/32/approve')) {
        submittedBody = JSON.parse(String(init?.body)) as Record<string, unknown>
        return Promise.resolve({ ok: true, json: async () => ({ ...pendingApproval, status: 'EXECUTED' }) } as Response)
      }
      return Promise.reject(new Error(`Unexpected fetch: ${url}`))
    })
    vi.stubGlobal('fetch', fetchMock)

    render(<App />)
    await user.type(screen.getByLabelText(/email/i), 'admin@assistant.test')
    await user.type(screen.getByLabelText(/password/i), 'secret')
    await user.click(screen.getByRole('button', { name: /sign in/i }))
    const body = await screen.findByLabelText('body for approval 32')
    await user.clear(body)
    await user.type(body, 'Edited confirmation')
    await user.click(screen.getByRole('button', { name: /edit and approve/i }))

    await waitFor(() => expect(submittedBody?.action_args).toEqual({
      recipient: 'admin@assistant.test',
      subject: 'Original',
      body: 'Edited confirmation',
    }))
    vi.unstubAllGlobals()
  })

  it('shows the graph rejection acknowledgment after rejecting an approval', async () => {
    const user = userEvent.setup()
    let hasPending = true
    const pendingApproval = {
      id: 44,
      user_id: 1,
      thread_id: 'thread-44',
      tool_name: 'purchase_order_create',
      action_args: { sku: 'SKU-1043', quantity: 80, supplier: 'Northstar Supply' },
      status: 'PENDING',
      created_at: '2026-10-03T10:00:00Z',
      updated_at: '2026-10-03T10:00:00Z',
    }
    const fetchMock = vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input)
      if (url.endsWith('/auth/login')) return Promise.resolve({ ok: true, json: async () => ({ access_token: 'ignored' }) } as Response)
      if (url.endsWith('/auth/me')) return Promise.resolve({ ok: true, json: async () => ({ id: 1, email: 'admin@assistant.test', is_admin: true, is_active: true, capabilities: [] }) } as Response)
      if (url.endsWith('/approvals/pending')) return Promise.resolve({ ok: true, json: async () => hasPending ? [pendingApproval] : [] } as Response)
      if (url.endsWith('/approvals/44/reject')) {
        hasPending = false
        return Promise.resolve({
          ok: true,
          json: async () => ({ ...pendingApproval, status: 'REJECTED', result: { assistant_message: 'Purchase order rejected. No order was created.' } }),
        } as Response)
      }
      return Promise.reject(new Error(`Unexpected fetch: ${url}`))
    })
    vi.stubGlobal('fetch', fetchMock)

    render(<App />)
    await user.type(screen.getByLabelText(/email/i), 'admin@assistant.test')
    await user.type(screen.getByLabelText(/password/i), 'secret')
    await user.click(screen.getByRole('button', { name: /sign in/i }))
    await user.click(await screen.findByRole('button', { name: 'Reject' }))

    expect(await screen.findByText('Purchase order rejected. No order was created.')).toBeInTheDocument()
    vi.unstubAllGlobals()
  })

  it('performs user lifecycle and capability actions through admin APIs', async () => {
    const user = userEvent.setup()
    const calls: Array<{ url: string; method: string; body?: unknown }> = []
    let createdPayload: Record<string, unknown> | null = null
    const fetchMock = vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input)
      const method = init?.method ?? 'GET'
      calls.push({ url, method, ...(init?.body ? { body: JSON.parse(String(init.body)) } : {}) })
      if (url.endsWith('/auth/login')) return Promise.resolve({ ok: true, json: async () => ({ access_token: 'ignored' }) } as Response)
      if (url.endsWith('/auth/me')) return Promise.resolve({ ok: true, json: async () => ({ id: 1, email: 'admin@assistant.test', is_admin: true, is_active: true, capabilities: [] }) } as Response)
      if (url.endsWith('/approvals/pending')) return Promise.resolve({ ok: true, json: async () => [] } as Response)
      if (url.endsWith('/admin/users') && method === 'GET') {
        return Promise.resolve({ ok: true, json: async () => [{ id: 2, email: 'ali@assistant.test', is_admin: false, is_active: true, capabilities: ['policy:read'] }] } as Response)
      }
      if (url.endsWith('/admin/users') && method === 'POST') {
        createdPayload = JSON.parse(String(init?.body)) as Record<string, unknown>
        return Promise.resolve({ ok: true, json: async () => ({}) } as Response)
      }
      if (url.includes('/admin/users/2/')) return Promise.resolve({ ok: true, json: async () => ({}) } as Response)
      return Promise.reject(new Error(`Unexpected fetch: ${url}`))
    })
    vi.stubGlobal('fetch', fetchMock)
    window.history.replaceState({}, '', '/admin/users')

    render(<App />)
    await user.type(screen.getByLabelText(/email/i), 'admin@assistant.test')
    await user.type(screen.getByLabelText(/password/i), 'secret')
    await user.click(screen.getByRole('button', { name: /sign in/i }))
    await screen.findByText('ali@assistant.test')
    await user.click(screen.getByRole('button', { name: 'Deactivate' }))
    await user.selectOptions(screen.getByLabelText('Capability to grant to ali@assistant.test'), 'email:send')
    await user.click(screen.getByRole('button', { name: 'Grant' }))
    await user.click(screen.getByRole('button', { name: 'Revoke policy:read from ali@assistant.test' }))
    await user.type(screen.getByLabelText('Email'), 'new.operator@assistant.test')
    await user.type(screen.getByLabelText('Initial password'), 'InitialPass123!')
    await user.click(screen.getByLabelText('order:create'))
    await user.click(screen.getByRole('button', { name: 'Create user' }))

    await waitFor(() => {
      expect(calls).toContainEqual(expect.objectContaining({ url: expect.stringMatching('/admin/users/2/deactivate'), method: 'POST' }))
      expect(calls).toContainEqual(expect.objectContaining({ url: expect.stringMatching('/admin/users/2/capabilities'), method: 'POST' }))
      expect(calls).toContainEqual(expect.objectContaining({ url: expect.stringMatching('/admin/users/2/capabilities'), method: 'DELETE' }))
      expect(createdPayload).toMatchObject({
        email: 'new.operator@assistant.test',
        password: 'InitialPass123!',
        capabilities: ['order:create'],
      })
    })
    vi.unstubAllGlobals()
  })

  it('uploads and removes policy documents through admin APIs', async () => {
    const user = userEvent.setup()
    let documents: Array<Record<string, unknown>> = []
    let uploadedPayload: Record<string, unknown> | null = null
    const fetchMock = vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input)
      const method = init?.method ?? 'GET'
      if (url.endsWith('/auth/login')) return Promise.resolve({ ok: true, json: async () => ({ access_token: 'ignored' }) } as Response)
      if (url.endsWith('/auth/me')) return Promise.resolve({ ok: true, json: async () => ({ id: 1, email: 'admin@assistant.test', is_admin: true, is_active: true, capabilities: [] }) } as Response)
      if (url.endsWith('/approvals/pending')) return Promise.resolve({ ok: true, json: async () => [] } as Response)
      if (url.endsWith('/admin/documents/indexing-status')) return Promise.resolve({ ok: true, json: async () => ({ statuses: { indexed: documents.length } }) } as Response)
      if (url.endsWith('/admin/documents') && method === 'GET') return Promise.resolve({ ok: true, json: async () => documents } as Response)
      if (url.endsWith('/admin/documents') && method === 'POST') {
        uploadedPayload = JSON.parse(String(init?.body)) as Record<string, unknown>
        documents = [{ id: 9, title: uploadedPayload.title, filename: uploadedPayload.filename, document_identifier: 'admin-testdoc', source: 'admin-upload', version: '1.0', uploaded_by: 1, uploaded_at: '2026-10-03T10:00:00Z', index_status: 'indexed' }]
        return Promise.resolve({ ok: true, json: async () => ({ id: 9, index_status: 'indexed' }) } as Response)
      }
      if (url.endsWith('/admin/documents/9') && method === 'DELETE') {
        documents = []
        return Promise.resolve({ ok: true, json: async () => ({ id: 9, status: 'deleted' }) } as Response)
      }
      return Promise.reject(new Error(`Unexpected fetch: ${url}`))
    })
    vi.stubGlobal('fetch', fetchMock)
    window.history.replaceState({}, '', '/admin/documents')

    render(<App />)
    await user.type(screen.getByLabelText(/email/i), 'admin@assistant.test')
    await user.type(screen.getByLabelText(/password/i), 'secret')
    await user.click(screen.getByRole('button', { name: /sign in/i }))
    await screen.findByRole('heading', { name: 'Documents' })
    await user.type(screen.getByLabelText('Title'), 'Vendor policy')
    await user.type(screen.getByLabelText('Filename'), 'vendor.md')
    await user.type(screen.getByLabelText('Content'), 'Quotes need delivery dates.')
    await user.click(screen.getByRole('button', { name: 'Upload and index' }))
    expect(await screen.findByText('Vendor policy')).toBeInTheDocument()
    expect(uploadedPayload).toMatchObject({ title: 'Vendor policy', filename: 'vendor.md', content: 'Quotes need delivery dates.' })
    await user.click(screen.getByRole('button', { name: 'Remove from retrieval' }))
    await waitFor(() => expect(fetchMock).toHaveBeenCalledWith(expect.stringContaining('/admin/documents/9'), expect.objectContaining({ method: 'DELETE' })))
    vi.unstubAllGlobals()
  })

  it('displays admin audit, order, and email activity', async () => {
    const user = userEvent.setup()
    const fetchMock = vi.fn((input: RequestInfo | URL) => {
      const url = String(input)
      if (url.endsWith('/auth/login')) return Promise.resolve({ ok: true, json: async () => ({ access_token: 'ignored' }) } as Response)
      if (url.endsWith('/auth/me')) return Promise.resolve({ ok: true, json: async () => ({ id: 1, email: 'admin@assistant.test', is_admin: true, is_active: true, capabilities: [] }) } as Response)
      if (url.endsWith('/approvals/pending')) return Promise.resolve({ ok: true, json: async () => [] } as Response)
      if (url.endsWith('/admin/activity')) {
        return Promise.resolve({
          ok: true,
          json: async () => ({
            audit_trail: [{ id: 1, tool: 'purchase_order_create', outcome: 'executed', user_id: 1, created_at: '2026-10-03', thread_id: 'thread-1', arguments: { sku: 'SKU-1043' } }],
            orders: [{ id: 2, order_reference: 'PO-EXAMPLE', sku: 'SKU-1043', quantity: 80, supplier: 'Northstar', requested_by: 1, created_at: '2026-10-03' }],
            email_messages: [{ id: 3, recipient: 'admin@assistant.test', subject: 'Confirmation', body: 'PO-EXAMPLE', sent_by: 1, sent_at: '2026-10-03' }],
          }),
        } as Response)
      }
      return Promise.reject(new Error(`Unexpected fetch: ${url}`))
    })
    vi.stubGlobal('fetch', fetchMock)
    window.history.replaceState({}, '', '/admin/activity')

    render(<App />)
    await user.type(screen.getByLabelText(/email/i), 'admin@assistant.test')
    await user.type(screen.getByLabelText(/password/i), 'secret')
    await user.click(screen.getByRole('button', { name: /sign in/i }))

    expect(await screen.findAllByText('PO-EXAMPLE')).toHaveLength(2)
    expect(screen.getByText('Confirmation')).toBeInTheDocument()
    expect(screen.getByText(/purchase_order_create · executed/i)).toBeInTheDocument()
    vi.unstubAllGlobals()
  })
})
