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
  content?: string
  route?: string
  steps?: string[]
  tool?: string
  tool_name?: string
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
  const [progressEvents, setProgressEvents] = useState<string[]>([])
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(false)
  const [route, setRoute] = useState<string>(() => window.location.pathname)
  const [users, setUsers] = useState<AdminUser[]>([])
  const [documents, setDocuments] = useState<AdminDocument[]>([])
  const [indexingStatus, setIndexingStatus] = useState<Record<string, number>>({})
  const [activity, setActivity] = useState<AdminActivity | null>(null)
  const [approvalDrafts, setApprovalDrafts] = useState<Record<number, Record<string, string>>>({})
  const [approvalFeedback, setApprovalFeedback] = useState('')
  const [newUserEmail, setNewUserEmail] = useState('')
  const [newUserPassword, setNewUserPassword] = useState('')
  const [newUserAdmin, setNewUserAdmin] = useState(false)
  const [newUserCapabilities, setNewUserCapabilities] = useState<string[]>([])
  const [capabilitySelections, setCapabilitySelections] = useState<Record<number, string>>({})
  const [documentTitle, setDocumentTitle] = useState('')
  const [documentFilename, setDocumentFilename] = useState('')
  const [documentContent, setDocumentContent] = useState('')

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
      setApprovalDrafts((current) => ({
        ...current,
        ...Object.fromEntries(
          approvals.map((approval) => [
            approval.id,
            Object.fromEntries(Object.entries(approval.action_args).map(([key, value]) => [key, String(value ?? '')])),
          ]),
        ),
      }))
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
    setProgressEvents([])
    setChatResponse(null)

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
          setProgressEvents((events) => [...events, payload.message ?? 'Processing request...'])
          if (payload.thread_id) {
            setThreadId(payload.thread_id)
          }
        } else if (eventName === 'routing') {
          const steps = Array.isArray(payload.steps) ? payload.steps.join(' → ') : ''
          const message = steps ? `Planned steps: ${steps}` : `Routed to ${String(payload.route ?? 'assistant')}`
          setStreamingStatus(message)
          setProgressEvents((events) => [...events, message])
        } else if (eventName === 'tool_started') {
          const message = `Started ${String(payload.tool ?? 'tool')}`
          setStreamingStatus(message)
          setProgressEvents((events) => [...events, message])
        } else if (eventName === 'tool_result') {
          const message = `Completed ${String(payload.tool ?? 'tool')}`
          setStreamingStatus(message)
          setProgressEvents((events) => [...events, message])
        } else if (eventName === 'assistant_delta') {
          const content = payload.content ?? ''
          setChatResponse((current) => ({
            thread_id: payload.thread_id ?? current?.thread_id ?? threadId ?? '',
            user_id: current?.user_id ?? user?.id ?? 0,
            intent: current?.intent ?? 'knowledge',
            response: `${current?.response ?? ''}${content}`,
            citations: current?.citations ?? [],
            citation_metadata: current?.citation_metadata ?? [],
          }))
        } else if (eventName === 'approval_required') {
          const message = `Paused for approval: ${String(payload.tool_name ?? 'write action')}`
          setStreamingStatus(message)
          setProgressEvents((events) => [...events, message])
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

  async function decideApproval(
    approvalId: number,
    decision: 'approve' | 'reject',
    actionArgs?: Record<string, unknown>,
  ) {
    if (!isAuthenticated) {
      return
    }

    setLoading(true)
    setError('')

    try {
      const decisionResult = await apiRequest<ApprovalSummary>(`/approvals/${approvalId}/${decision}`, {
        method: 'POST',
        body: JSON.stringify({
          reason: decision === 'approve' ? 'Approved from UI' : 'Rejected from UI',
          ...(actionArgs ? { action_args: actionArgs } : {}),
        }),
      })
      const message = decisionResult.result?.assistant_message
      setApprovalFeedback(typeof message === 'string' ? message : '')
      await loadPendingApprovals()
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Unable to update approval.')
    } finally {
      setLoading(false)
    }
  }

  async function createAdminUser(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    setLoading(true)
    setError('')
    try {
      await apiRequest('/admin/users', {
        method: 'POST',
        body: JSON.stringify({
          email: newUserEmail,
          password: newUserPassword,
          is_admin: newUserAdmin,
          capabilities: newUserCapabilities,
        }),
      })
      setNewUserEmail('')
      setNewUserPassword('')
      setNewUserAdmin(false)
      setNewUserCapabilities([])
      await loadUsers()
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Unable to create user.')
    } finally {
      setLoading(false)
    }
  }

  async function setUserActive(userId: number, active: boolean) {
    try {
      await apiRequest(`/admin/users/${userId}/${active ? 'reactivate' : 'deactivate'}`, { method: 'POST' })
      await loadUsers()
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Unable to update user status.')
    }
  }

  async function changeCapability(userId: number, capability: string, grant: boolean) {
    try {
      await apiRequest(`/admin/users/${userId}/capabilities`, {
        method: grant ? 'POST' : 'DELETE',
        ...(grant ? { body: JSON.stringify({ capability }) } : { body: JSON.stringify({ capability }) }),
      })
      await loadUsers()
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Unable to update capability.')
    }
  }

  async function uploadDocument(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    setLoading(true)
    setError('')
    try {
      await apiRequest('/admin/documents', {
        method: 'POST',
        body: JSON.stringify({ title: documentTitle, filename: documentFilename, content: documentContent }),
      })
      setDocumentTitle('')
      setDocumentFilename('')
      setDocumentContent('')
      await loadDocuments()
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Unable to upload document.')
    } finally {
      setLoading(false)
    }
  }

  async function removeDocument(documentId: number) {
    try {
      await apiRequest(`/admin/documents/${documentId}`, { method: 'DELETE' })
      await loadDocuments()
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Unable to remove document.')
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
    setApprovalFeedback('')
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
          <form className="admin-form" onSubmit={createAdminUser}>
            <h3>Create user</h3>
            <label htmlFor="new-user-email">Email</label>
            <input id="new-user-email" type="email" value={newUserEmail} onChange={(event) => setNewUserEmail(event.target.value)} required />
            <label htmlFor="new-user-password">Initial password</label>
            <input id="new-user-password" type="password" value={newUserPassword} onChange={(event) => setNewUserPassword(event.target.value)} minLength={8} required />
            <label className="check-row">
              <input type="checkbox" checked={newUserAdmin} onChange={(event) => setNewUserAdmin(event.target.checked)} />
              Administrator
            </label>
            <fieldset className="capability-options">
              <legend>Capabilities</legend>
              {['policy:read', 'inventory:read', 'order:create', 'email:send'].map((capability) => (
                <label className="check-row" key={capability}>
                  <input
                    type="checkbox"
                    checked={newUserCapabilities.includes(capability)}
                    onChange={(event) => setNewUserCapabilities((current) => (
                      event.target.checked ? [...current, capability] : current.filter((item) => item !== capability)
                    ))}
                  />
                  {capability}
                </label>
              ))}
            </fieldset>
            <button type="submit" className="primary-button" disabled={loading}>Create user</button>
          </form>
          <ul className="admin-record-list">
            {users.map((nextUser) => (
              <li className="admin-record" key={nextUser.id}>
                <div className="admin-record-heading">
                  <div>
                    <strong>{nextUser.email}</strong>
                    <p>{nextUser.is_admin ? 'Administrator' : 'Operator'} · {nextUser.is_active ? 'Active' : 'Inactive'}</p>
                  </div>
                  <button type="button" className="secondary-button" onClick={() => void setUserActive(nextUser.id, !nextUser.is_active)}>
                    {nextUser.is_active ? 'Deactivate' : 'Reactivate'}
                  </button>
                </div>
                <div className="tag-list">
                  {nextUser.capabilities.length ? nextUser.capabilities.map((capability) => (
                    <span className="tag capability-tag" key={capability}>
                      {capability}
                      <button type="button" aria-label={`Revoke ${capability} from ${nextUser.email}`} onClick={() => void changeCapability(nextUser.id, capability, false)}>×</button>
                    </span>
                  )) : <span>No capabilities</span>}
                </div>
                <div className="capability-grant">
                  <select
                    aria-label={`Capability to grant to ${nextUser.email}`}
                    value={capabilitySelections[nextUser.id] ?? 'policy:read'}
                    onChange={(event) => setCapabilitySelections((current) => ({ ...current, [nextUser.id]: event.target.value }))}
                  >
                    {['policy:read', 'inventory:read', 'order:create', 'email:send'].map((capability) => <option key={capability}>{capability}</option>)}
                  </select>
                  <button type="button" className="secondary-button" onClick={() => void changeCapability(nextUser.id, capabilitySelections[nextUser.id] ?? 'policy:read', true)}>Grant</button>
                </div>
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
          <form className="admin-form" onSubmit={uploadDocument}>
            <h3>Upload policy document</h3>
            <label htmlFor="document-title">Title</label>
            <input id="document-title" value={documentTitle} onChange={(event) => setDocumentTitle(event.target.value)} required />
            <label htmlFor="document-filename">Filename</label>
            <input id="document-filename" value={documentFilename} onChange={(event) => setDocumentFilename(event.target.value)} placeholder="Optional" />
            <label htmlFor="document-content">Content</label>
            <textarea id="document-content" value={documentContent} onChange={(event) => setDocumentContent(event.target.value)} rows={8} required />
            <button type="submit" className="primary-button" disabled={loading}>Upload and index</button>
          </form>
          <h3>Indexing status</h3>
          <div className="tag-list">
            {Object.entries(indexingStatus).map(([status, count]) => (
              <span className="tag" key={status}>{status}: {count}</span>
            ))}
          </div>
          <ul className="admin-record-list">
            {documents.map((document) => (
              <li className="admin-record" key={document.id}>
                <div className="admin-record-heading">
                  <div>
                    <strong>{document.title}</strong>
                    <p>{document.filename} · {document.document_identifier}</p>
                  </div>
                  <span className="tag">{document.index_status}</span>
                </div>
                <p>{document.source} · v{document.version}</p>
                <button type="button" className="secondary-button" onClick={() => void removeDocument(document.id)}>Remove from retrieval</button>
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
                {activity.audit_trail.map((entry) => (
                  <li key={String(entry.id)}>
                    <strong>{String(entry.tool ?? 'audit')} · {String(entry.outcome ?? '')}</strong>
                    <p>User {String(entry.user_id ?? '')} · {String(entry.created_at ?? '')} · Thread {String(entry.thread_id ?? '')}</p>
                    <pre>{JSON.stringify(entry.arguments ?? {}, null, 2)}</pre>
                  </li>
                ))}
              </ul>
              <h3>Orders</h3>
              <ul>
                {activity.orders.map((order) => (
                  <li key={String(order.id)}>
                    <strong>{String(order.order_reference ?? 'Order')}</strong>
                    <p>{String(order.quantity ?? '')} × {String(order.sku ?? '')} · {String(order.supplier ?? '')} · Requested by {String(order.requested_by ?? '')}</p>
                    <p>{String(order.created_at ?? '')}</p>
                  </li>
                ))}
              </ul>
              <h3>Email</h3>
              <ul>
                {activity.email_messages.map((message) => (
                  <li key={String(message.id)}>
                    <strong>{String(message.subject ?? 'Email')}</strong>
                    <p>To {String(message.recipient ?? '')} · Sent by {String(message.sent_by ?? '')} · {String(message.sent_at ?? '')}</p>
                    <p>{String(message.body ?? '')}</p>
                  </li>
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
        {isAuthenticated && error ? <p className="error-text" role="alert">{error}</p> : null}

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
              {progressEvents.length > 0 ? (
                <ol className="progress-list" aria-live="polite">
                  {progressEvents.map((event, index) => <li key={`${event}-${index}`}>{event}</li>)}
                </ol>
              ) : null}

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
              {approvalFeedback ? <p className="response-intent" role="status">{approvalFeedback}</p> : null}
              {pendingApprovals.length > 0 ? (
                pendingApprovals.map((approval) => {
                  const fields = approval.tool_name === 'purchase_order_create'
                    ? ['sku', 'quantity', 'supplier']
                    : ['recipient', 'subject', 'body']
                  const draft = approvalDrafts[approval.id] ?? {}
                  const editedArgs = Object.fromEntries(fields.map((field) => [
                    field,
                    field === 'quantity' ? Number(draft[field]) : (draft[field] ?? String(approval.action_args[field] ?? '')),
                  ]))
                  return (
                    <div className="approval-card" key={approval.id}>
                      <div>
                        <strong>{approval.tool_name === 'purchase_order_create' ? 'Purchase order' : 'Email'}</strong>
                        <p>{approval.thread_id}</p>
                      </div>
                      <div className="approval-fields">
                        {fields.map((field) => (
                          <label className="field-row" key={field}>
                            {field === 'sku' ? 'SKU' : field.charAt(0).toUpperCase() + field.slice(1)}
                            {field === 'body' ? (
                              <textarea
                                aria-label={`${field} for approval ${approval.id}`}
                                value={draft[field] ?? String(approval.action_args[field] ?? '')}
                                onChange={(event) => setApprovalDrafts((current) => ({
                                  ...current,
                                  [approval.id]: { ...current[approval.id], [field]: event.target.value },
                                }))}
                                rows={4}
                              />
                            ) : (
                              <input
                                aria-label={`${field} for approval ${approval.id}`}
                                type={field === 'quantity' ? 'number' : field === 'recipient' ? 'email' : 'text'}
                                min={field === 'quantity' ? 1 : undefined}
                                value={draft[field] ?? String(approval.action_args[field] ?? '')}
                                onChange={(event) => setApprovalDrafts((current) => ({
                                  ...current,
                                  [approval.id]: { ...current[approval.id], [field]: event.target.value },
                                }))}
                                required
                              />
                            )}
                          </label>
                        ))}
                      </div>
                      <div className="approval-actions">
                        <button type="button" className="primary-button" disabled={loading} onClick={() => void decideApproval(approval.id, 'approve')}>
                          Approve
                        </button>
                        <button type="button" className="secondary-button" disabled={loading} onClick={() => void decideApproval(approval.id, 'approve', editedArgs)}>
                          Edit and Approve
                        </button>
                        <button type="button" className="secondary-button" disabled={loading} onClick={() => void decideApproval(approval.id, 'reject')}>
                          Reject
                        </button>
                      </div>
                    </div>
                  )
                })
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
