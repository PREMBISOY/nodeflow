const API_URL = import.meta.env.VITE_NODEFLOW_API_URL || '/api/v1'

async function request(path, options) {
  const response = await fetch(`${API_URL}${path}`, {
    headers: { 'Content-Type': 'application/json', ...options?.headers }, ...options,
  })
  const body = await response.json().catch(() => null)
  if (!response.ok || !body?.success) throw new Error(body?.error?.message || `Request failed (${response.status})`)
  return body.data
}

export const api = {
  project: (id) => request(`/projects/${id}`),
  context: (id) => request(`/projects/${id}/context`),
  state: (id) => request(`/projects/${id}/state`),
  architecture: (id) => request(`/projects/${id}/architecture`),
  decisions: (id) => request(`/projects/${id}/decisions`),
  agentContext: (id, scope) => request(`/agents/${id}/context?scope=${scope}`),
  agentUpdates: (id) => request(`/agents/${id}/updates`),
  onboarding: (payload) => request('/onboarding', { method: 'POST', body: JSON.stringify(payload) }),
}
