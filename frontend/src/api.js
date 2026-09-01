const base = (import.meta.env.VITE_API_BASE_URL || '/api/v1').replace(/\/$/, '')
export class ApiError extends Error { constructor(message, status) { super(message); this.status = status } }
async function request(path, options = {}) {
  const token = localStorage.getItem('nodeflow.session')
  const response = await fetch(`${base}${path}`, { ...options, headers: { 'Content-Type': 'application/json', ...(token ? { Authorization: `Bearer ${token}` } : {}), ...options.headers } })
  const body = await response.json().catch(() => null)
  if (!response.ok || body?.success === false) throw new ApiError(body?.error?.message || `Request failed (${response.status})`, response.status)
  return body?.data ?? body
}
export const api = {
  register: data => request('/auth/register', { method: 'POST', body: JSON.stringify(data) }), login: data => request('/auth/login', { method: 'POST', body: JSON.stringify(data) }), me: () => request('/me'), switchTeam: team_id => request('/me/active-team', { method: 'POST', body: JSON.stringify({ team_id }) }), teams: () => request('/teams'), createTeam: data => request('/teams', { method: 'POST', body: JSON.stringify(data) }), joinTeam: team_code => request('/teams/join', { method: 'POST', body: JSON.stringify({ team_code }) }), members: teamId => request(`/teams/${teamId}/members`), addMember: (teamId, email) => request(`/teams/${teamId}/members`, { method: 'POST', body: JSON.stringify({ email }) }), removeMember: (teamId, userId) => request(`/teams/${teamId}/members/${userId}`, { method: 'DELETE' }), projects: id => request(`/teams/${id}/projects`), createProject: (teamId, data) => request(`/teams/${teamId}/projects`, { method: 'POST', body: JSON.stringify(data) }), context: id => request(`/projects/${id}/context`), onboarding: data => request('/onboarding', { method: 'POST', body: JSON.stringify(data) }), githubLogin: () => { window.location.assign(`${base}/auth/github`) }, repositories: teamId => request(`/teams/${teamId}/github/repositories`), connectRepository: (teamId, data) => request(`/teams/${teamId}/github/repositories`, { method: 'POST', body: JSON.stringify(data) }), syncRepository: (teamId, projectId) => request(`/teams/${teamId}/github/repositories/${projectId}/sync`, { method: 'POST' }),
}
