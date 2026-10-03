import { FormEvent, useEffect, useState } from 'react'

type LoginResponse = {
  access_token: string
  token_type: string
}

type UserSummary = {
  id: number
  email: string
  is_admin: boolean
  is_active: boolean
  capabilities: string[]
}

type ApprovalSummary = {
  id: number
  user_id: number
  thread_id: string
  tool_name: string
  action_args: Record<string, unknown>
  status: string
  created_at: string
  updated_at: string
  decision_made_by?: number | null
  decision_made_at?: string | null
  decision_reason?: string | null
  result?: Record<string, unknown> | null
  expires_at?: string | null
}

type ChatResponse = {
  thread_id: string
  user_id: number
  intent: string
  response: string
  citations: string[]
  citation_metadata?: Array<{
    document_title: string
    document_identifier?: string
    filename?: string
    source?: string
    version?: string
    section?: string | null
  }>
  action_request?: Record<string, unknown> | null
  approval_request?: Record<string, unknown> | null
  error?: string | null
}

type StreamEventPayload = Partial<ChatResponse> & {
  message?: string
}

type AdminUser = UserSummary

type AdminDocument = {
  id: number
  title: string
  filename: string
  document_identifier: string
  source: string
  version: string
  uploaded_by: number
  uploaded_at: string
  index_status: string
}

type AdminActivity = {
  audit_trail: Array<Record<string, unknown>>
  orders: Array<Record<string, unknown>>
  email_messages: Array<Record<string, unknown>>
}

const API_BASE = (import.meta.env.VITE_API_BASE_URL ?? 'http://localhost:8000').replace(/\/$/, '')

async function apiRequest<T>(path: string, options: RequestInit = {}): Promise<T> {
  const headers = new Headers(options.headers ?? {})
  if (!(options.body instanceof FormData)) {
    headers.set('Content-Type', 'application/json')
  }

  const response = await fetch(`${API_BASE}${path}`, {
    ...options,
    headers,
    credentials: 'include',
  })

  if (!response.ok) {
    const detail = await response.text()
    throw new Error(detail || 'Request failed')
  }

  return (await response.json()) as T
}

async function consumeChatStream(
  response: Response,
  onEvent: (name: string, payload: StreamEventPayload) => void,
): Promise<ChatResponse> {
  if (!response.ok) {
    throw new Error((await response.text()) || 'Chat request failed')
  }
  if (!response.body) {
    throw new Error('Streaming response body is unavailable')
  }

  const reader = response.body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''
  let finalResponse: ChatResponse | null = null

  function consumeBlock(block: string) {
    let eventName = 'message'
    const dataLines: string[] = []
    for (const line of block.split('\n')) {
      if (line.startsWith('event:')) {
        eventName = line.slice(6).trim()
      } else if (line.startsWith('data:')) {
        dataLines.push(line.slice(5).trimStart())
      }
    }
    if (dataLines.length === 0) {
      return
    }

    const payload = JSON.parse(dataLines.join('\n')) as StreamEventPayload
    onEvent(eventName, payload)
    if (eventName === 'final') {
      finalResponse = payload as ChatResponse
    }
  }

  while (true) {
    const { value, done } = await reader.read()
    buffer += decoder.decode(value, { stream: !done }).replace(/\r\n/g, '\n')
    let boundary = buffer.indexOf('\n\n')
    while (boundary >= 0) {
      consumeBlock(buffer.slice(0, boundary))
      buffer = buffer.slice(boundary + 2)
      boundary = buffer.indexOf('\n\n')
    }
    if (done) {
      if (buffer.trim()) {
        consumeBlock(buffer)
      }
      break
    }
  }

  if (!finalResponse) {
    throw new Error('Streaming response ended before the final event')
  }
  return finalResponse
}

export default function App() {
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [user, setUser] = useState<UserSummary | null>(null)
  const [capabilities, setCapabilities] = useState<string[]>([])
  const [pendingApprovals, setPendingApprovals] = useState<ApprovalSummary[]>([])
  const [chatInput, setChatInput] = useState('')
  const [threadId, setThreadId] = useState<string | null>(null)
  const [chatResponse, setChatResponse] = useState<ChatResponse | null>(null)
  const [streamingStatus, setStreamingStatus] = useState('')
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(false)
  const [route, setRoute] = useState<string>(() => window.location.pathname)
  const [users, setUsers] = useState<AdminUser[]>([])
  const [documents, setDocuments] = useState<AdminDocument[]>([])
  const [indexingStatus, setIndexingStatus] = useState<Record<string, number>>({})
  const [activity, setActivity] = useState<AdminActivity | null>(null)

  const isAuthenticated = Boolean(user)
  const isAdmin = Boolean(user?.is_admin)

  useEffect(() => {
    const syncRoute = () => setRoute(window.location.pathname)
    window.addEventListener('popstate', syncRoute)
    syncRoute()
    return () => window.removeEventListener('popstate', syncRoute)
  }, [])

  useEffect(() => {
    if (!isAuthenticated) {
      setCapabilities([])
      setPendingApprovals([])
      setUser(null)
      return
    }

    void loadSession()
    void loadPendingApprovals()
  }, [isAuthenticated])

  useEffect(() => {
    if (!isAuthenticated || !isAdmin) {
      return
    }
    if (route.startsWith('/admin/users')) {
      void loadUsers()
    }
    if (route.startsWith('/admin/documents')) {
      void loadDocuments()
    }
    if (route.startsWith('/admin/activity')) {
      void loadActivity()
    }
  }, [route, isAuthenticated, isAdmin])

  async function loadSession() {
    try {
      const currentUser = await apiRequest<UserSummary>('/auth/me')
      setUser(currentUser)
      setCapabilities(currentUser.capabilities ?? [])
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Unable to load user session.')
      setUser(null)
    }
  }

  async function loadPendingApprovals() {
    if (!isAuthenticated) {
      return
    }

    try {
      const approvals = await apiRequest<ApprovalSummary[]>('/approvals/pending')
      setPendingApprovals(approvals)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Unable to load pending approvals.')
    }
  }

  async function loadUsers() {
    try {
      const nextUsers = await apiRequest<AdminUser[]>('/admin/users')
      setUsers(nextUsers)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Unable to load users.')
    }
  }

  async function loadDocuments() {
    try {
      const nextDocuments = await apiRequest<AdminDocument[]>('/admin/documents')
      setDocuments(nextDocuments)
      const status = await apiRequest<{ statuses: Record<string, number> }>('/admin/documents/indexing-status')
      setIndexingStatus(status.statuses ?? {})
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Unable to load documents.')
    }
  }

  async function loadActivity() {
    try {
      const nextActivity = await apiRequest<AdminActivity>('/admin/activity')
      setActivity(nextActivity)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Unable to load activity.')
    }
  }

  function navigate(path: string) {
    window.history.pushState({}, '', path)
    setRoute(window.location.pathname)
  }

  async function handleLogin(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    setLoading(true)
    setError('')

    try {
      await apiRequest<LoginResponse>('/auth/login', {
        method: 'POST',
        body: JSON.stringify({ email, password }),
      })
      setPassword('')
      const currentUser = await apiRequest<UserSummary>('/auth/me')
      setUser(currentUser)
      setCapabilities(currentUser.capabilities ?? [])
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Login failed.')
    } finally {
      setLoading(false)
    }
  }

  async function handleChatSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (!isAuthenticated || !chatInput.trim()) {
      return
    }

    setLoading(true)
    setError('')
    setStreamingStatus('Connecting to chat...')

    try {
      const response = await fetch(`${API_BASE}/chat/stream`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          Accept: 'text/event-stream',
        },
        body: JSON.stringify({ message: chatInput.trim(), thread_id: threadId ?? undefined }),
        credentials: 'include',
      })
      const result = await consumeChatStream(response, (eventName, payload) => {
        if (eventName === 'status') {
          setStreamingStatus(payload.message ?? 'Processing request...')
          if (payload.thread_id) {
            setThreadId(payload.thread_id)
          }
        } else if (eventName === 'approval') {
          setStreamingStatus('Approval request saved')
        } else if (eventName === 'error') {
          throw new Error(payload.message ?? 'The chat request could not be completed.')
        }
      })

      setThreadId(result.thread_id)
      setChatResponse(result)
      setStreamingStatus('Response complete')
      setChatInput('')
      await loadPendingApprovals()
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Unable to send chat message.')
    } finally {
      setLoading(false)
    }
  }

  async function decideApproval(approvalId: number, decision: 'approve' | 'reject') {
    if (!isAuthenticated) {
      return
    }

    setLoading(true)
    setError('')

    try {
      await apiRequest(`/approvals/${approvalId}/${decision}`, {
        method: 'POST',
        body: JSON.stringify({ reason: decision === 'approve' ? 'Approved from UI' : 'Rejected from UI' }),
      })
      await loadPendingApprovals()
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Unable to update approval.')
    } finally {
      setLoading(false)
    }
  }

  async function logout() {
    try {
      await apiRequest('/auth/logout', { method: 'POST' })
    } catch {
      // Safe to ignore; the browser-side session should still end.
    }
    setUser(null)
    setCapabilities([])
    setPendingApprovals([])
    setChatResponse(null)
    setError('')
    setThreadId(null)
    setStreamingStatus('')
    navigate('/')
  }

  function renderAdminRoute() {
    if (!isAuthenticated) {
      return <p className="error-text">Please sign in to access the administration area.</p>
    }
    if (!isAdmin) {
      return <p className="error-text">Access denied. Admin authorization is required.</p>
    }

    if (route.startsWith('/admin/users')) {
      return (
        <div className="admin-panel">
          <h2>Users</h2>
          <ul>
            {users.map((nextUser) => (
              <li key={nextUser.id}>
                {nextUser.email} ({nextUser.is_admin ? 'admin' : 'user'}) — {nextUser.capabilities.join(', ') || 'no capabilities'}
              </li>
            ))}
          </ul>
        </div>
      )
    }

    if (route.startsWith('/admin/documents')) {
      return (
        <div className="admin-panel">
          <h2>Documents</h2>
          <div className="tag-list">
            {Object.entries(indexingStatus).map(([status, count]) => (
              <span className="tag" key={status}>{status}: {count}</span>
            ))}
          </div>
          <ul>
            {documents.map((document) => (
              <li key={document.id}>
                {document.title} ({document.index_status})
              </li>
            ))}
          </ul>
        </div>
      )
    }

    if (route.startsWith('/admin/activity')) {
      return (
        <div className="admin-panel">
          <h2>Activity</h2>
          {activity ? (
            <>
              <h3>Audit trail</h3>
              <ul>
                {activity.audit_trail.map((entry, index) => (
                  <li key={`${String(entry.tool ?? 'audit')}-${index}`}>{String(entry.tool ?? 'audit')} — {String(entry.outcome ?? '')}</li>
                ))}
              </ul>
              <h3>Orders</h3>
              <ul>
                {activity.orders.map((order, index) => (
                  <li key={`order-${index}`}>{String(order.order_reference ?? 'Order')} — {String(order.quantity ?? '')} units</li>
                ))}
              </ul>
              <h3>Email</h3>
              <ul>
                {activity.email_messages.map((message, index) => (
                  <li key={`email-${index}`}>{String(message.recipient ?? 'Email')} — {String(message.subject ?? '')}</li>
                ))}
              </ul>
            </>
          ) : (
            <p>Loading activity…</p>
          )}
        </div>
      )
    }

    return <p className="error-text">Select an admin screen.</p>
  }

  return (
    <main className="app-shell">
      <section className="panel">
        <div className="panel-header">
          <div>
            <p className="eyebrow">Operations console</p>
            <h1>AI Operations Assistant</h1>
          </div>
          {isAuthenticated ? (
            <button type="button" className="secondary-button" onClick={logout}>
              Sign out
            </button>
          ) : null}
        </div>

        {!isAuthenticated ? (
          <form className="auth-card" onSubmit={handleLogin}>
            <div className="field-row">
              <label htmlFor="email">Email</label>
              <input
                id="email"
                type="email"
                value={email}
                onChange={(event) => setEmail(event.target.value)}
                placeholder="admin@assistant.test"
                autoComplete="email"
                required
              />
            </div>

            <div className="field-row">
              <label htmlFor="password">Password</label>
              <input
                id="password"
                type="password"
                value={password}
                onChange={(event) => setPassword(event.target.value)}
                placeholder="Enter your password"
                autoComplete="current-password"
                required
              />
            </div>

            {error ? <p className="error-text">{error}</p> : null}

            <button type="submit" className="primary-button" disabled={loading}>
              {loading ? 'Signing in…' : 'Sign in'}
            </button>
          </form>
        ) : route.startsWith('/admin') ? (
          <div className="workspace-grid">
            <div className="info-panel">
              <div className="mini-card">
                <h2>Session</h2>
                <p>{user?.email}</p>
                <p>{user?.is_admin ? 'Administrator' : 'Operator'}</p>
              </div>
              {isAdmin ? (
                <div className="mini-card">
                  <h2>Admin</h2>
                  <button type="button" className="secondary-button" onClick={() => navigate('/admin/users')}>
                    Users
                  </button>
                  <button type="button" className="secondary-button" onClick={() => navigate('/admin/documents')}>
                    Documents
                  </button>
                  <button type="button" className="secondary-button" onClick={() => navigate('/admin/activity')}>
                    Activity
                  </button>
                </div>
              ) : null}
            </div>
            <div className="conversation-panel">{renderAdminRoute()}</div>
          </div>
        ) : (
          <div className="workspace-grid">
            <div className="info-panel">
              <div className="mini-card">
                <h2>Session</h2>
                <p>{user?.email}</p>
                <p>{user?.is_admin ? 'Administrator' : 'Operator'}</p>
              </div>

              <div className="mini-card">
                <h2>Capabilities</h2>
                <div className="tag-list">
                  {capabilities.length > 0 ? (
                    capabilities.map((capability) => (
                      <span className="tag" key={capability}>
                        {capability}
                      </span>
                    ))
                  ) : (
                    <p>No capabilities loaded.</p>
                  )}
                </div>
              </div>

              {isAdmin ? (
                <div className="mini-card">
                  <h2>Admin</h2>
                  <button type="button" className="secondary-button" onClick={() => navigate('/admin/users')}>
                    Users
                  </button>
                  <button type="button" className="secondary-button" onClick={() => navigate('/admin/documents')}>
                    Documents
                  </button>
                  <button type="button" className="secondary-button" onClick={() => navigate('/admin/activity')}>
                    Activity
                  </button>
                </div>
              ) : null}
            </div>

            <div className="conversation-panel">
              <form onSubmit={handleChatSubmit} className="chat-form">
                <label htmlFor="chat-input">New chat message</label>
                <textarea
                  id="chat-input"
                  value={chatInput}
                  onChange={(event) => setChatInput(event.target.value)}
                  rows={4}
                  placeholder="Ask about inventory, orders, or policy questions..."
                />
                <button type="submit" className="primary-button" disabled={loading || !chatInput.trim()}>
                  Send message
                </button>
              </form>
              {streamingStatus ? <p className="response-intent" aria-live="polite">{streamingStatus}</p> : null}

              {chatResponse ? (
                <article className="message-card">
                  <h3>Latest response</h3>
                  <p className="response-intent">Intent: {chatResponse.intent}</p>
                  <p>{chatResponse.response}</p>

                  {chatResponse.citations.length > 0 ? (
                    <div className="citation-list">
                      <strong>Citations</strong>
                      <ul>
                        {chatResponse.citation_metadata?.length
                          ? chatResponse.citation_metadata.map((citation) => (
                              <li key={`${citation.document_identifier ?? citation.document_title}-${citation.section ?? ''}`}>
                                {citation.document_title}
                                {citation.version ? `, v${citation.version}` : ''}
                                {citation.section ? `, ${citation.section}` : ''}
                                {citation.source ? ` (${citation.source})` : ''}
                                {citation.filename ? ` - ${citation.filename}` : ''}
                              </li>
                            ))
                          : chatResponse.citations.map((citation) => <li key={citation}>{citation}</li>)}
                      </ul>
                    </div>
                  ) : null}

                  {chatResponse.approval_request ? (
                    <div className="approval-banner">
                      <strong>Approval required:</strong> {String(chatResponse.approval_request.tool_name ?? 'protected action')}
                    </div>
                  ) : null}
                </article>
              ) : null}
            </div>

            <div className="approvals-panel">
              <h2>Pending approvals</h2>
              {pendingApprovals.length > 0 ? (
                pendingApprovals.map((approval) => (
                  <div className="approval-card" key={approval.id}>
                    <div>
                      <strong>{approval.tool_name}</strong>
                      <p>{approval.thread_id}</p>
                    </div>
                    <pre>{JSON.stringify(approval.action_args, null, 2)}</pre>
                    <div className="approval-actions">
                      <button type="button" className="primary-button" onClick={() => decideApproval(approval.id, 'approve')}>
                        Approve
                      </button>
                      <button type="button" className="secondary-button" onClick={() => decideApproval(approval.id, 'reject')}>
                        Reject
                      </button>
                    </div>
                  </div>
                ))
              ) : (
                <p className="empty-state">No pending approvals.</p>
              )}
            </div>
          </div>
        )}
      </section>
    </main>
  )
}
