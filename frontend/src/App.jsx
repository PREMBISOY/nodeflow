import { useEffect, useRef, useState } from 'react'
import { api, ApiError } from './api'

const pages = ['Overview', 'Architecture', 'Agents', 'Tasks', 'Activity']
const errorText = e => e?.status === 401 ? 'Your session has expired. Please log in again.' : e?.status === 403 ? 'You do not have permission to access this resource.' : e?.status === 404 ? 'The requested team or project was not found.' : e?.message || 'Something went wrong.'
function dedupeTeams(items, preferredId) { const unique = new Map(); for (const item of items) { const key = `${item.created_by}:${item.name.trim().toLocaleLowerCase()}`; if (!unique.has(key) || item.id === preferredId) unique.set(key, item) } return [...unique.values()] }
function Panel({ title, children }) { return <section className="panel"><header><h2>{title}</h2></header>{children}</section> }
function Empty({ title, children }) { return <div className="empty"><b>∅</b><strong>{title}</strong><span>{children}</span></div> }
function ErrorBox({ error, retry }) { return <div className="error"><strong>Unable to continue</strong><p>{errorText(error)}</p><button onClick={retry}>Try again</button></div> }
function List({ title, items, render }) { return <Panel title={title}>{items.length ? <div className="list">{items.map(render)}</div> : <Empty title={`No ${title.toLowerCase()} yet`}>This project has no data to show.</Empty>}</Panel> }
function Auth({ done }) { const [register, setRegister] = useState(false); const [form, setForm] = useState({ name: '', email: '', password: '' }); const [error, setError] = useState(); async function submit(e) { e.preventDefault(); try { setError(); const data = await (register ? api.register(form) : api.login({ email: form.email, password: form.password })); localStorage.setItem('nodeflow.session', data.access_token); done() } catch (err) { setError(err) } } return <main className="auth"><div className="auth-card"><div className="brand"><b>n</b> nodeflow</div><h1>{register ? 'Create account' : 'Welcome back'}</h1><form onSubmit={submit}>{register && <label>Name<input required value={form.name} onChange={e => setForm({ ...form, name: e.target.value })} /></label>}<label>Email<input required type="email" value={form.email} onChange={e => setForm({ ...form, email: e.target.value })} /></label><label>Password<input required type="password" minLength="8" value={form.password} onChange={e => setForm({ ...form, password: e.target.value })} /></label><button>{register ? 'Register →' : 'Log in →'}</button>{error && <p className="form-error">{errorText(error)}</p>}</form><button onClick={api.githubLogin}>Continue with GitHub</button><button className="link" onClick={() => setRegister(!register)}>{register ? 'Already have an account? Log in' : 'Need an account? Register'}</button></div></main> }
function TeamForm({ finish, created }) { const [kind, setKind] = useState('join'); const [value, setValue] = useState(''); const [error, setError] = useState(); const [busy, setBusy] = useState(false); async function submit(e) { e.preventDefault(); if (busy) return; try { setBusy(true); setError(); const team = await (kind === 'join' ? api.joinTeam(value.trim()) : api.createTeam({ name: value.trim() })); if (kind === 'create') created(team); else await finish(team) } catch (err) { setError(err) } finally { setBusy(false) } } return <main className="setup"><form className="panel form" onSubmit={submit}><div className="tabs"><button disabled={busy} type="button" className={kind === 'join' ? 'selected' : ''} onClick={() => setKind('join')}>Join team</button><button disabled={busy} type="button" className={kind === 'create' ? 'selected' : ''} onClick={() => setKind('create')}>Create team</button></div><h1>{kind === 'join' ? 'Join your team' : 'Create a team'}</h1><label>{kind === 'join' ? 'Team join code' : 'Team name'}<input disabled={busy} required value={value} placeholder={kind === 'join' ? 'NF-HV-7K92Q' : 'HackVerse'} onChange={e => setValue(e.target.value)} /></label><button disabled={busy}>{busy ? 'Please wait…' : kind === 'join' ? 'Join Team →' : 'Create Team →'}</button>{error && <p className="form-error">{errorText(error)}</p>}</form></main> }
function TeamCode({ team, continueToProject }) { const [copied, setCopied] = useState(false); async function copy() { try { await navigator.clipboard.writeText(team.team_code); setCopied(true) } catch { setCopied(false) } } return <main className="setup"><section className="panel team-code"><small>TEAM CREATED</small><h1>Team join code</h1><p>Share this code with teammates so they can join.</p><strong>{team.team_code}</strong><button type="button" onClick={copy}>{copied ? 'Copied ✓' : 'Copy code'}</button><button type="button" className="continue" onClick={continueToProject}>Continue →</button></section></main> }
function ProjectForm({ team, done }) { const [form, setForm] = useState({ name: '', purpose: '', technology_stack: '' }); const [error, setError] = useState(); async function submit(e) { e.preventDefault(); try { done(await api.createProject(team.id, { name: form.name, purpose: form.purpose, technology_stack: form.technology_stack.split(',').map(x => x.trim()).filter(Boolean) })) } catch (err) { setError(err) } } return <main className="setup"><form className="panel form" onSubmit={submit}><h2>Create the first project</h2><p>Your team has no projects yet.</p><label>Project name<input required value={form.name} onChange={e => setForm({ ...form, name: e.target.value })} /></label><label>Purpose<input required value={form.purpose} onChange={e => setForm({ ...form, purpose: e.target.value })} /></label><label>Technology stack<input value={form.technology_stack} onChange={e => setForm({ ...form, technology_stack: e.target.value })} /></label><button>Create project →</button>{error && <p className="form-error">{errorText(error)}</p>}</form></main> }

function RepoModal({ onClose, onSubmit }) {
    const [repo, setRepo] = useState('');
    return <div className="auth" style={{position:'fixed', top:0, left:0, width:'100%', height:'100%', zIndex:100}}>
      <div className="auth-card">
        <h2>Connect GitHub Repository</h2>
        <input value={repo} onChange={e=>setRepo(e.target.value)} placeholder="owner/repository" style={{width:'100%'}} />
        <div style={{display:'flex', gap:'10px', marginTop:'15px'}}>
            <button onClick={() => onSubmit(repo)}>Connect</button>
            <button onClick={onClose} style={{background:'#555'}}>Cancel</button>
        </div>
      </div>
    </div>
}

function TeamMembersModal({ team, onClose }) {
    const [members, setMembers] = useState([]);
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState();
    const [addEmail, setAddEmail] = useState('');
    
    useEffect(() => {
        api.teamMembers(team.id).then(setMembers).catch(setError).finally(()=>setLoading(false));
    }, [team.id]);

    const handleAdd = async () => {
        if(!addEmail) return;
        try {
            await api.addTeamMember(team.id, { email: addEmail, role: 'member' });
            const m = await api.teamMembers(team.id);
            setMembers(m);
            setAddEmail('');
        } catch(e) { setError(e); }
    };
    
    const handleRemove = async (id) => {
        try {
            await api.removeTeamMember(team.id, id);
            setMembers(members.filter(m => m.id !== id && m.user_id !== id));
        } catch(e) { setError(e); }
    };

    return <div className="auth" style={{position:'fixed', top:0, left:0, width:'100%', height:'100%', zIndex:100}}>
        <div className="auth-card" style={{width: '600px', maxHeight:'80vh', overflow:'auto'}}>
            <h2 style={{marginTop:0}}>Team Members</h2>
            {error && <p className="form-error">{errorText(error)}</p>}
            {loading ? <p>Loading...</p> : (
                <div style={{display:'flex', flexDirection:'column', gap:'10px', marginBottom: '20px'}}>
                    {members.map(m => (
                        <div key={m.id || m.user_id} style={{display:'flex', justifyContent:'space-between', padding:'10px', border:'1px solid #333', borderRadius:'8px'}}>
                            <div>
                                <strong style={{display:'block'}}>{m.name || m.email || m.user_id}</strong>
                                <small style={{color:'#888'}}>ID: {m.id || m.user_id}</small>
                            </div>
                            <div style={{display:'flex', alignItems:'center', gap:'15px'}}>
                                <span style={{textTransform:'uppercase', fontSize:'11px'}}>{m.role}</span>
                                <button onClick={() => handleRemove(m.id || m.user_id)} style={{background:'#a1162a', padding:'5px 10px', fontSize:'11px'}}>Remove</button>
                            </div>
                        </div>
                    ))}
                </div>
            )}
            <div style={{display:'flex', gap:'10px', borderTop:'1px solid #333', paddingTop:'20px'}}>
                <input value={addEmail} onChange={e=>setAddEmail(e.target.value)} placeholder="User Email" style={{flex:1}} />
                <button onClick={handleAdd}>Add Member</button>
            </div>
            <button onClick={onClose} style={{marginTop:'20px', width:'100%', background:'#333'}}>Close</button>
        </div>
    </div>
}

function GitHubRepository({ team, project, synced }) {
    const [repositories, setRepositories] = useState([]);
    const [error, setError] = useState();
    const [busy, setBusy] = useState(false);
    const [showRepoModal, setShowRepoModal] = useState(false);

    const refresh = () => api.repositories(team.id).then(setRepositories).catch(setError);
    useEffect(() => { refresh() }, [team.id]);
    
    if (!project) return null;
    const linked = repositories.find(item => item.project_id === project.id);
    
    async function connect(repository) {
        setShowRepoModal(false);
        if (!repository) return;
        try {
            setBusy(true); setError();
            await api.connectRepository(team.id, { project_id: project.id, repository });
            await refresh();
            await synced();
        } catch (err) { setError(err) } finally { setBusy(false) }
    }
    
    async function sync() {
        try {
            setBusy(true); setError();
            await api.syncRepository(team.id, project.id);
            await refresh();
            await synced();
        } catch (err) { setError(err) } finally { setBusy(false) }
    }
    
    return <div className="github-repository">
        <small>GITHUB REPOSITORY</small>
        {linked ? <><a href={linked.html_url} target="_blank" rel="noreferrer">{linked.full_name} ↗</a><button disabled={busy} onClick={sync}>{busy ? 'Syncing...' : 'Sync repository intelligence'}</button></> : <button disabled={busy} onClick={() => setShowRepoModal(true)}>{busy ? 'Connecting...' : 'Connect public repository'}</button>}
        <span>Imports complete commit history and derives architecture. Main-branch pushes refresh it through the GitHub webhook.</span>
        {error && <small className="form-error">{errorText(error)}</small>}
        {showRepoModal && <RepoModal onClose={() => setShowRepoModal(false)} onSubmit={connect} />}
    </div>
}

function Brain({ context, page }) { const active = context.tasks.filter(t => t.status === 'in_progress'); const commits = context.recent_events.filter(e => e.event_type === 'github_commit'); if (page === 'Architecture') return <><h1>Living architecture</h1><p className="architecture-note">Derived from the connected repository’s current source tree.</p>{context.components.length ? <div className="map">{context.components.map(c => <div className="node" key={c.id}><b>◫</b><strong>{c.name}</strong><small>{c.description || c.owner_role || c.kind}</small></div>)}</div> : <Empty title="No repository architecture yet">Connect a public GitHub repository, then sync its intelligence.</Empty>}<List title="Dependencies" items={context.relationships} render={r => <div className="task" key={r.id}><div><strong>{context.components.find(c => c.id === r.source_component_id)?.name || 'Unknown'} → {context.components.find(c => c.id === r.target_component_id)?.name || 'Unknown'}</strong><small>{r.description}</small></div></div>} /></>; if (page === 'Agents') return <List title="Agents" items={context.agents} render={a => <div className="agent" key={a.id}><b className="avatar">{a.name?.[0]}</b><div><strong>{a.name}</strong><small>{a.role} · {a.model_provider}</small></div></div>} />; if (page === 'Tasks') return <List title="Tasks" items={context.tasks} render={t => <div className="task" key={t.id}><b>✓</b><div><strong>{t.title}</strong><small>{t.status}</small></div></div>} />; if (page === 'Activity') return <List title="Repository and project history" items={context.recent_events} render={e => <div className="event" key={e.id}><i /><div><strong>{e.summary}</strong><small>{e.created_at ? new Date(e.created_at).toLocaleString() : e.event_type.replaceAll('_', ' ')}</small></div></div>} />; return <><div className="headline"><div><small>PROJECT COMMAND CENTER</small><h1>State of the world</h1><p>Live repository context plus authorized project data.</p></div></div><div className="metrics">{[['Repository commits', commits.length], ['Architecture components', context.components.length], ['Active agents', context.agents.filter(a => a.active).length], ['Work in progress', active.length]].map(([name, value]) => <div className="metric" key={name}><small>{name}</small><strong>{value}</strong><span>{name === 'Repository commits' ? 'Full imported history' : 'Project Brain'}</span></div>)}</div><div className="grid two"><List title="Latest repository history" items={commits.slice(0, 5)} render={e => <div className="event" key={e.id}><i /><div><strong>{e.summary}</strong><small>{new Date(e.created_at).toLocaleDateString()}</small></div></div>} /><List title="Recent collaboration" items={context.recent_events.filter(e => e.event_type !== 'github_commit').slice(0, 5)} render={e => <div className="event" key={e.id}><i /><div><strong>{e.summary}</strong><small>{e.event_type}</small></div></div>} /></div></> }
function Onboarding({ context }) { const [form, setForm] = useState({ name: '', role: 'Frontend Engineer', scope: 'related', question: 'Explain this project to me.' }); const [result, setResult] = useState(); const [error, setError] = useState(); const [busy, setBusy] = useState(false); async function submit(e) { e.preventDefault(); if (busy) return; try { setBusy(true); setError(); setResult(await api.onboarding({ ...form, project_id: context.project.id })) } catch (err) { setError(err) } finally { setBusy(false) } } return <div className="onboarding"><form className="panel form" onSubmit={submit}><h2>New member briefing</h2><label>Name<input disabled={busy} required value={form.name} onChange={e => setForm({ ...form, name: e.target.value })} /></label><label>Role<input disabled={busy} required value={form.role} onChange={e => setForm({ ...form, role: e.target.value })} /></label><button disabled={busy}>{busy ? 'Generating…' : 'Generate briefing →'}</button>{error && <p className="form-error">{errorText(error)}</p>}</form><Panel title="Personalized briefing">{result ? <p className="briefing">{result.briefing}</p> : <Empty title="Your briefing will appear here">It is generated for the selected authorized project.</Empty>}</Panel></div> }

export default function App() { 
  const [me, setMe] = useState(); 
  const [teams, setTeams] = useState([]); 
  const [team, setTeam] = useState(); 
  const [pendingTeam, setPendingTeam] = useState(); 
  const [projects, setProjects] = useState([]); 
  const [project, setProject] = useState(); 
  const [context, setContext] = useState(); 
  const [page, setPage] = useState('Overview'); 
  const [error, setError] = useState(); 
  const [showMembers, setShowMembers] = useState(false); 
  const [teamCode, setTeamCode] = useState(''); 
  
  const logout = () => { localStorage.removeItem('nodeflow.session'); setMe(); setTeams([]); setTeam(); setProjects([]); setProject(); setContext() }; 
  const reloadContext = async () => { if (!project) return; try { setError(); setContext(await api.context(project.id)) } catch (err) { setError(err) } }; 
  const start = async () => { try { setError(); const current = await api.me(); const visibleTeams = dedupeTeams(current.teams, current.active_team_id); setMe(current.user); setTeams(visibleTeams); setTeam(visibleTeams.find(t => t.id === current.active_team_id) || null) } catch (err) { if (err instanceof ApiError && err.status === 401) logout(); else setError(err) } }; 
  const selectTeam = async chosen => { if (!chosen) return; try { setError(); const switched = await api.switchTeam(chosen.id); localStorage.setItem('nodeflow.session', switched.access_token); setTeam(chosen); setProjects([]); setProject(); setContext() } catch (err) { setError(err) } }; 
  const completeTeam = async created => { try { const all = await api.teams(); const updated = dedupeTeams(all.some(t => t.id === created.id) ? all : [...all, created], created.id); setTeams(updated); await selectTeam(updated.find(t => t.id === created.id) || created) } catch (err) { setError(err) } }; 
  
  useEffect(() => { const token = new URLSearchParams(window.location.hash.slice(1)).get('access_token'); if (token) { localStorage.setItem('nodeflow.session', token); window.history.replaceState({}, '', window.location.pathname) } if (localStorage.getItem('nodeflow.session')) start() }, []); 
  useEffect(() => { if (team) { api.projects(team.id).then(items => { setError(); setProjects(items); setProject(items[0] || null) }).catch(setError); api.teamJoinCode(team.id).then(res => setTeamCode(res.join_code || res.team_code)).catch(() => setTeamCode('')); } }, [team?.id]); 
  useEffect(() => { if (project) api.context(project.id).then(value => { setError(); setContext(value) }).catch(setError) }, [project?.id]); 
  
  if (!me) return <Auth done={start} />; 
  if (pendingTeam) return <TeamCode team={pendingTeam} continueToProject={async () => { const created = pendingTeam; setPendingTeam(); await completeTeam(created) }} />; 
  if (!teams.length || !team) return <TeamForm finish={completeTeam} created={setPendingTeam} />; 
  if (!project && projects.length === 0) return <ProjectForm team={team} done={created => { setProjects([created]); setProject(created) }} />; 
  
  return <div className="app">
    <aside>
      <div className="brand"><b>n</b> nodeflow</div>
      <label className="team-label">ACTIVE TEAM<select value={team.id} onChange={e => selectTeam(teams.find(t => t.id === e.target.value))}>{teams.map(t => <option key={t.id} value={t.id}>{t.name}</option>)}</select></label>
      <label className="team-label">TEAM CODE<div className="team-code-display">{teamCode || 'Hidden'}</div></label>
      <label className="team-label">PROJECT<select value={project?.id || ''} onChange={e => { setContext(); setProject(projects.find(p => p.id === e.target.value)) }}>{projects.map(p => <option key={p.id} value={p.id}>{p.name}</option>)}</select></label>
      
      <GitHubRepository team={team} project={project} synced={reloadContext} />
      
      <div className="team-actions"><button onClick={() => setTeam(null)}>+ Create / Join team</button></div>
      <div style={{padding:'0 9px 10px'}}><button className="link" style={{width:'100%', textAlign:'left', padding:'10px', background:'#292a2f', borderRadius:'8px', color:'#fff'}} onClick={() => setShowMembers(true)}>+ Team Members</button></div>
      
      <nav>{pages.map(item => <button key={item} className={item === page ? 'active' : ''} onClick={() => setPage(item)}>{item}</button>)}</nav>
      <footer><button className="link" onClick={logout}>Log out</button><small>{me.email}</small></footer>
    </aside>
    <main>
      <header><span>{team.name} / <b>{project?.name}</b></span></header>
      <article>{error ? <ErrorBox error={error} retry={start} /> : context ? <Brain context={context} page={page} /> : <div className="loading">Loading authorized project context.</div>}</article>
    </main>
    {showMembers && <TeamMembersModal team={team} onClose={() => setShowMembers(false)} />}
  </div> 
}
