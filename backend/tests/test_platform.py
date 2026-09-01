from fastapi.testclient import TestClient
from app.main import create_app

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
