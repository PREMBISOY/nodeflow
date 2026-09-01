const base = import.meta.env.VITE_NODEFLOW_API_URL || '/api/v1'
async function request(path, options = {}) {
  const response = await fetch(`${base}${path}`, { ...options, headers: { 'Content-Type': 'application/json', ...options.headers } })
  const body = await response.json().catch(() => null)
  if (!response.ok || !body?.success) throw new Error(body?.error?.message || `Request failed (${response.status})`)
  return body.data
}
export const api = { context: id => request(`/projects/${id}/context`), onboarding: data => request('/onboarding', { method: 'POST', body: JSON.stringify(data) }) }
