from fastapi.testclient import TestClient
from app.main import create_app
from tests.fixtures.demo_data import DEMO_IDS, seed_demo

def client(): return TestClient(create_app(load_demo_data=False))
def register(client, name, email): return client.post('/api/v1/auth/register', json={'name': name, 'email': email, 'password': 'secure-password'}).json()['data']['access_token']
def auth(token): return {'Authorization': f'Bearer {token}'}

def test_registration_team_join_and_active_team_switching():
    api=client(); owner=register(api, 'Prem', 'prem@example.com')
    created=api.post('/api/v1/teams', json={'name':'HackVerse'}, headers=auth(owner)); assert created.status_code == 201
    team=created.json()['data']; second=api.post('/api/v1/teams', json={'name':'Research'}, headers=auth(owner)).json()['data']
    switched=api.post('/api/v1/me/active-team', json={'team_id': team['id']}, headers=auth(owner)); assert switched.status_code == 200
    active=switched.json()['data']['access_token']; me=api.get('/api/v1/me', headers=auth(active)).json()['data']
    assert {item['id'] for item in me['teams']} == {team['id'], second['id']} and me['active_team_id'] == team['id']

def test_join_is_idempotent_and_non_members_cannot_read_members():
    api=client(); owner=register(api, 'Prem', 'prem@example.com'); team=api.post('/api/v1/teams', json={'name':'HackVerse'}, headers=auth(owner)).json()['data']
    guest=register(api, 'Aarya', 'aarya@example.com'); joined=api.post('/api/v1/teams/join', json={'team_code':team['team_code']}, headers=auth(guest)); assert joined.status_code == 200
    assert api.post('/api/v1/teams/join', json={'team_code':team['team_code']}, headers=auth(guest)).status_code == 200
    outsider=register(api, 'Sunal', 'sunal@example.com'); assert api.get(f"/api/v1/teams/{team['id']}/members", headers=auth(outsider)).status_code == 403

def test_member_can_create_and_list_only_their_team_projects():
    api=client(); owner=register(api, 'Prem', 'prem@example.com'); team=api.post('/api/v1/teams', json={'name':'HackVerse'}, headers=auth(owner)).json()['data']
    created=api.post(f"/api/v1/teams/{team['id']}/projects", json={'name':'NodeFlow','purpose':'Shared context','technology_stack':['FastAPI']}, headers=auth(owner))
    assert created.status_code == 201
    projects=api.get(f"/api/v1/teams/{team['id']}/projects", headers=auth(owner)).json()['data']
    assert [project['id'] for project in projects] == [created.json()['data']['id']]

def test_active_team_blocks_cross_tenant_project_agent_and_event_access():
    app=create_app(); seed_demo(app.state.container.repository); app.state.enforce_tenants=True
    api=TestClient(app); token=register(api, 'Prem', 'prem@example.com'); store=app.state.platform_store; user=store.login(type('Login', (), {'email':'prem@example.com','password':'secure-password'})())
    team_a=store.create_team(user, 'Team A'); team_b=store.create_team(user, 'Team B'); store.project_teams[DEMO_IDS['project']]=team_a.id
    team_a_token=app.state.session_codec.issue(user.id, team_a.id); team_b_token=app.state.session_codec.issue(user.id, team_b.id)
    assert api.get(f"/api/v1/projects/{DEMO_IDS['project']}", headers=auth(team_a_token)).status_code == 200
    assert api.get(f"/api/v1/agents/{DEMO_IDS['frontend_agent']}/updates", headers=auth(team_b_token)).status_code == 404
    assert api.post('/api/v1/events', headers=auth(team_b_token), json={'project_id':str(DEMO_IDS['project']),'event_type':'test','summary':'blocked'}).status_code == 404
    assert api.get(f"/api/v1/projects/{DEMO_IDS['project']}/context", headers=auth(team_b_token)).status_code == 404
    assert api.get(f"/api/v1/projects/{DEMO_IDS['project']}/collaboration", headers=auth(team_b_token)).status_code == 404
    assert api.get(f"/api/v1/projects/{DEMO_IDS['project']}/git/activity", headers=auth(team_b_token)).status_code == 404
    assert api.post('/api/v1/integrations/github/events', headers=auth(team_b_token), json={'project_id':str(DEMO_IDS['project']),'event_type':'commit','repository':'PREMBISOY/nodeflow','summary':'blocked'}).status_code == 404
    assert api.post(f"/api/v1/agents/{DEMO_IDS['frontend_agent']}/messages", headers=auth(team_b_token), json={'recipient_agent_id':str(DEMO_IDS['backend_agent']),'message_type':'notice','subject':'blocked','content':'blocked'}).status_code == 404
    assert api.post('/api/v1/onboarding', headers=auth(team_b_token), json={'project_id':str(DEMO_IDS['project']),'name':'Test','role':'Engineer'}).status_code == 404

def test_project_creation_and_listing_are_active_team_scoped():
    api=client(); token=register(api,'Prem','prem@example.com'); team=api.post('/api/v1/teams',json={'name':'Team A'},headers=auth(token)).json()['data']
    active=api.post('/api/v1/me/active-team',json={'team_id':team['id']},headers=auth(token)).json()['data']['access_token']
    created=api.post(f"/api/v1/teams/{team['id']}/projects",headers=auth(active),json={'name':'Platform','purpose':'Shared context'}); assert created.status_code == 201
    assert api.get(f"/api/v1/teams/{team['id']}/projects",headers=auth(active)).json()['data'][0]['id'] == created.json()['data']['id']
