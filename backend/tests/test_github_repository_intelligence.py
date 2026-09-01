from datetime import datetime, timezone

from app.core.container import build_container
from app.models import Project
from app.services.repository import InMemoryProjectRepository


class Response:
    def __init__(self, status_code=200, text="", data=None):
        self.status_code = status_code
        self.text = text
        self._data = data
        self.headers = {}

    def json(self): return self._data


def test_repository_sync_imports_history_and_derives_living_architecture(monkeypatch):
    repository = InMemoryProjectRepository()
    project = Project(name="NodeFlow", purpose="Project intelligence")
    repository.seed(project)
    sync = build_container(repository).github_sync
    commits = [
        {"sha": "a" * 40, "commit": {"message": "Initial commit", "author": {"date": "2025-01-02T03:04:05Z", "name": "Prem"}}, "author": {"login": "prem"}},
        {"sha": "b" * 40, "commit": {"message": "Add dashboard", "author": {"date": "2025-01-03T03:04:05Z", "name": "Prem"}}, "author": {"login": "prem"}},
    ]
    tree = {"truncated": False, "tree": [
        {"type": "blob", "path": "frontend/src/App.jsx"},
        {"type": "blob", "path": "backend/app/main.py"},
        {"type": "blob", "path": "migrate/001_schema.sql"},
    ]}

    def fake_json(url):
        if "/git/trees/" in url: return tree
        return commits if "page=1" in url else []

    def fake_get(url, **_kwargs):
        text = ""
        if "frontend/" in url: text = "fetch('/api/v1/me')"
        if "backend/" in url: text = "DATABASE_URL = 'postgresql://'"
        return Response(text=text)

    monkeypatch.setattr(sync, "_json", fake_json)
    monkeypatch.setattr("app.services.github_repository_intelligence.httpx.get", fake_get)
    result = sync.sync(project.id, "prem/nodeflow", "main")

    components = {item.name: item for item in repository.list_components(project.id)}
    assert result["commits_imported"] == 2
    assert set(components) == {"Backend", "Frontend", "Migrate"}
    pairs = {(components_by_id.source_component_id, components_by_id.target_component_id) for components_by_id in repository.list_relationships(project.id)}
    assert (components["Frontend"].id, components["Backend"].id) in pairs
    assert (components["Backend"].id, components["Migrate"].id) in pairs
    history = repository.list_events(project.id, limit=10)
    assert len(history) == 2 and min(item.created_at for item in history) == datetime(2025, 1, 2, 3, 4, 5, tzinfo=timezone.utc)
    assert sync.sync(project.id, "prem/nodeflow", "main")["commits_imported"] == 0
