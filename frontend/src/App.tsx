import { FormEvent, useEffect, useMemo, useState } from 'react'

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
  action_request?: Record<string, unknown> | null
  approval_request?: Record<string, unknown> | null
  error?: string | null
}

const API_BASE = (import.meta.env.VITE_API_BASE_URL ?? 'http://localhost:8000').replace(/\/$/, '')
const AUTH_TOKEN_STORAGE_KEY = 'ai-ops-auth-token'

async function apiRequest<T>(path: string, token?: string, options: RequestInit = {}): Promise<T> {
  const headers = new Headers(options.headers ?? {})
  headers.set('Content-Type', 'application/json')

  if (token) {
    headers.set('Authorization', `Bearer ${token}`)
  }

  const response = await fetch(`${API_BASE}${path}`, {
    ...options,
    headers,
  })

  if (!response.ok) {
    const detail = await response.text()
    throw new Error(detail || 'Request failed')
  }

  return (await response.json()) as T
}

export default function App() {
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [token, setToken] = useState<string | null>(() => localStorage.getItem(AUTH_TOKEN_STORAGE_KEY))
  const [user, setUser] = useState<UserSummary | null>(null)
  const [capabilities, setCapabilities] = useState<string[]>([])
  const [pendingApprovals, setPendingApprovals] = useState<ApprovalSummary[]>([])
  const [chatInput, setChatInput] = useState('')
  const [threadId, setThreadId] = useState<string | null>(null)
  const [chatResponse, setChatResponse] = useState<ChatResponse | null>(null)
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(false)

  const hasToken = useMemo(() => Boolean(token), [token])

  useEffect(() => {
    if (!token) {
      setUser(null)
      setCapabilities([])
      setPendingApprovals([])
      return
    }

    void loadSession()
    void loadPendingApprovals()
  }, [token])

  async function loadSession() {
    if (!token) {
      return
    }

    try {
      const currentUser = await apiRequest<UserSummary>('/auth/me', token)
      setUser(currentUser)
      setCapabilities(currentUser.capabilities ?? [])
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Unable to load user session.')
      setToken(null)
      localStorage.removeItem(AUTH_TOKEN_STORAGE_KEY)
    }
  }

  async function loadPendingApprovals() {
    if (!token) {
      return
    }

    try {
      const approvals = await apiRequest<ApprovalSummary[]>('/approvals/pending', token)
      setPendingApprovals(approvals)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Unable to load pending approvals.')
    }
  }

  async function handleLogin(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    setLoading(true)
    setError('')

    try {
      const loginResponse = await apiRequest<LoginResponse>('/auth/login', undefined, {
        method: 'POST',
        body: JSON.stringify({ email, password }),
      })

      const accessToken = loginResponse.access_token
      localStorage.setItem(AUTH_TOKEN_STORAGE_KEY, accessToken)
      setToken(accessToken)
      setPassword('')
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Login failed.')
    } finally {
      setLoading(false)
    }
  }

  async function handleChatSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (!token || !chatInput.trim()) {
      return
    }

    setLoading(true)
    setError('')

    try {
      const response = await apiRequest<ChatResponse>('/chat', token, {
        method: 'POST',
        body: JSON.stringify({
          message: chatInput.trim(),
          thread_id: threadId ?? undefined,
        }),
      })

      setThreadId(response.thread_id)
      setChatResponse(response)
      setChatInput('')
      await loadPendingApprovals()
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Unable to send chat message.')
    } finally {
      setLoading(false)
    }
  }

  async function decideApproval(approvalId: number, decision: 'approve' | 'reject') {
    if (!token) {
      return
    }

    setLoading(true)
    setError('')

    try {
      await apiRequest(`/approvals/${approvalId}/${decision}`, token, {
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

  function logout() {
    localStorage.removeItem(AUTH_TOKEN_STORAGE_KEY)
    setToken(null)
    setUser(null)
    setChatResponse(null)
    setPendingApprovals([])
    setCapabilities([])
    setError('')
  }

  return (
    <main className="app-shell">
      <section className="panel">
        <div className="panel-header">
          <div>
            <p className="eyebrow">Operations console</p>
            <h1>AI Operations Assistant</h1>
          </div>
          {hasToken && user ? (
            <button type="button" className="secondary-button" onClick={logout}>
              Sign out
            </button>
          ) : null}
        </div>

        {!hasToken ? (
          <form className="auth-card" onSubmit={handleLogin}>
            <div className="field-row">
              <label htmlFor="email">Email</label>
              <input
                id="email"
                type="email"
                value={email}
                onChange={(event) => setEmail(event.target.value)}
                placeholder="ops@cellutech.com"
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

              {chatResponse ? (
                <article className="message-card">
                  <h3>Latest response</h3>
                  <p className="response-intent">Intent: {chatResponse.intent}</p>
                  <p>{chatResponse.response}</p>

                  {chatResponse.citations.length > 0 ? (
                    <div className="citation-list">
                      <strong>Citations</strong>
                      <ul>
                        {chatResponse.citations.map((citation) => (
                          <li key={citation}>{citation}</li>
                        ))}
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
