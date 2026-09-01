"""Public GitHub repository importer for the living Project Brain."""

from __future__ import annotations

import os
import re
from datetime import datetime
from urllib.parse import quote
from uuid import NAMESPACE_URL, UUID, uuid5

import httpx

from app.models import Component, Relationship
from app.schemas.intelligence import GitHubEventCreate
from app.services.git_intelligence import GitIntelligenceService
from app.services.repository import ProjectKnowledgeRepository


class RepositorySyncError(RuntimeError):
    pass


class GitHubRepositoryIntelligence:
    """Imports public commit history and derives a small, inspectable architecture.

    GitHub remains authoritative: NodeFlow stores only structured summaries needed
    by the project context. The importer is intentionally bounded so a large public
    repository cannot monopolize a web request.
    """

    SOURCE_EXTENSIONS = {".py", ".js", ".jsx", ".ts", ".tsx", ".go", ".java", ".rb", ".rs", ".cs", ".php", ".sql"}
    MAX_HISTORY_PAGES = 50
    MAX_SOURCE_FILES = 120
    MAX_SOURCE_BYTES = 1_500_000

    def __init__(self, repository: ProjectKnowledgeRepository, git: GitIntelligenceService):
        self.repository = repository
        self.git = git

    def sync(self, project_id: UUID, full_name: str, default_branch: str) -> dict:
        self.repository.get_project(project_id)
        files = self._files(full_name, default_branch)
        components, relationships = self._architecture(project_id, full_name, default_branch, files)
        self.repository.sync_github_architecture(project_id, components, relationships)

        imported = 0
        for commit in self._commits(full_name, default_branch):
            sha = commit.get("sha")
            if not sha or self.repository.has_github_commit(project_id, full_name, sha):
                continue
            detail = commit.get("commit", {})
            message = (detail.get("message") or "Commit").splitlines()[0][:1_800]
            author = (commit.get("author") or {}).get("login") or detail.get("author", {}).get("name")
            timestamp = self._timestamp(detail.get("author", {}).get("date"))
            self.git.ingest(GitHubEventCreate(
                project_id=project_id, event_type="commit", action="created", repository=full_name,
                summary=f"Commit {sha[:7]}: {message}", commit_sha=sha, actor_name=author,
                ref=f"refs/heads/{default_branch}", occurred_at=timestamp,
            ))
            imported += 1
        return {"repository": full_name, "branch": default_branch, "files_scanned": len(files), "components": len(components), "relationships": len(relationships), "commits_imported": imported}

    def _files(self, repository: str, branch: str) -> list[str]:
        try:
            tree = self._json(f"https://api.github.com/repos/{repository}/git/trees/{branch}?recursive=1")
            if not tree.get("truncated"):
                return [item["path"] for item in tree.get("tree", []) if item.get("type") == "blob"]
        except RepositorySyncError:
            pass
        # GitHub occasionally times out recursive tree generation for healthy
        # repositories. Walk the Contents API instead; it is slower but bounded
        # and makes repository import reliable without a local clone.
        files: list[str] = []
        directories = [""]
        while directories:
            directory = directories.pop()
            suffix = quote(directory) if directory else ""
            data = self._json(f"https://api.github.com/repos/{repository}/contents/{suffix}?ref={branch}")
            entries = data if isinstance(data, list) else [data]
            for item in entries:
                if item.get("type") == "file":
                    files.append(item["path"])
                elif item.get("type") == "dir":
                    directories.append(item["path"])
                if len(files) > 5_000:
                    raise RepositorySyncError("Repository contains too many files to analyse safely")
        return files

    def _architecture(self, project_id: UUID, repository: str, branch: str, files: list[str]) -> tuple[list[Component], list[Relationship]]:
        source_files = [path for path in files if self._extension(path) in self.SOURCE_EXTENSIONS]
        grouped: dict[str, list[str]] = {}
        for path in source_files:
            root = self._root(path)
            if root:
                grouped.setdefault(root, []).append(path)
        existing = {
            self._path_tag(component.tags): component.id
            for component in self.repository.list_components(project_id)
            if "source:github" in component.tags and self._path_tag(component.tags)
        }
        components = [
            Component(
                id=existing.get(root) or uuid5(NAMESPACE_URL, f"nodeflow:{project_id}:github:{repository.casefold()}:{root}"),
                project_id=project_id,
                name=self._label(root),
                description=f"GitHub-derived {self._kind(root)} component at {root}/ ({len(paths)} source file{'s' if len(paths) != 1 else ''}).",
                kind=self._kind(root),
                tags=["source:github", f"repository:{repository.casefold()}", f"path:{root}"],
            )
            for root, paths in sorted(grouped.items())
        ]
        content = self._source_text(repository, branch, [path for paths in grouped.values() for path in paths])
        by_root = {self._path_tag(component.tags): component for component in components}
        relationships: list[Relationship] = []
        self._add_relation(project_id, relationships, by_root, "frontend", "backend", content.get("frontend", ""), "frontend source calls the backend API")
        database_root = next((root for root in by_root if root in {"migrate", "supabase", "database", "db"} or "migration" in root), None)
        if database_root:
            for root, text in content.items():
                if root != database_root and re.search(r"DATABASE_URL|sqlalchemy|postgres|supabase", text, re.I):
                    self._add_relation(project_id, relationships, by_root, root, database_root, text, "source configures or queries the repository database")
        for source, text in content.items():
            for target in by_root:
                if source == target:
                    continue
                if re.search(rf"(?:\.\./|/){re.escape(target)}(?:/|['\"])|from\s+{re.escape(target)}(?:\.|/)", text):
                    self._add_relation(project_id, relationships, by_root, source, target, text, "source imports or references this repository component")
        return components, relationships

    def _add_relation(self, project_id: UUID, relationships: list[Relationship], components: dict[str, Component], source: str, target: str, text: str, reason: str) -> None:
        if source not in components or target not in components or source == target or not text:
            return
        if any(item.source_component_id == components[source].id and item.target_component_id == components[target].id for item in relationships):
            return
        relationships.append(Relationship(
            id=uuid5(NAMESPACE_URL, f"nodeflow:{project_id}:github:{source}:{target}:depends_on"), project_id=project_id,
            source_component_id=components[source].id, target_component_id=components[target].id,
            relationship_type="depends_on", description=f"GitHub-derived: {reason}.",
        ))

    def _commits(self, repository: str, branch: str):
        for page in range(1, self.MAX_HISTORY_PAGES + 1):
            commits = self._json(f"https://api.github.com/repos/{repository}/commits?sha={branch}&per_page=100&page={page}")
            if not isinstance(commits, list):
                raise RepositorySyncError("GitHub returned an invalid commit history")
            yield from commits
            if len(commits) < 100:
                return
        raise RepositorySyncError("Repository history exceeds the current import safety limit")

    def _source_text(self, repository: str, branch: str, paths: list[str]) -> dict[str, str]:
        collected: dict[str, list[str]] = {}
        used = 0
        for path in paths[:self.MAX_SOURCE_FILES]:
            try:
                response = httpx.get(f"https://raw.githubusercontent.com/{repository}/{branch}/{path}", timeout=10)
            except httpx.HTTPError:
                continue
            if response.status_code != 200:
                continue
            text = response.text[:40_000]
            used += len(text.encode())
            if used > self.MAX_SOURCE_BYTES:
                break
            root = self._root(path)
            if root:
                collected.setdefault(root, []).append(text)
        return {root: "\n".join(parts) for root, parts in collected.items()}

    def _json(self, url: str):
        headers = {"Accept": "application/vnd.github+json", "User-Agent": "NodeFlow-Project-Brain"}
        token = os.getenv("GITHUB_API_TOKEN")
        if token:
            headers["Authorization"] = f"Bearer {token}"
        try:
            response = httpx.get(url, headers=headers, timeout=20)
        except httpx.HTTPError as exc:
            raise RepositorySyncError("GitHub is temporarily unavailable") from exc
        if response.status_code == 403 and response.headers.get("x-ratelimit-remaining") == "0":
            raise RepositorySyncError("GitHub API rate limit reached; configure GITHUB_API_TOKEN and try again")
        if response.status_code != 200:
            raise RepositorySyncError(f"GitHub could not read the repository (HTTP {response.status_code})")
        return response.json()

    @staticmethod
    def _root(path: str) -> str | None:
        parts = path.split("/")
        if len(parts) < 2 or parts[0].startswith("."):
            return None
        return parts[0]

    @staticmethod
    def _extension(path: str) -> str:
        return "." + path.rsplit(".", 1)[-1].lower() if "." in path else ""

    @staticmethod
    def _label(root: str) -> str:
        return root.replace("-", " ").replace("_", " ").title()

    @staticmethod
    def _kind(root: str) -> str:
        lowered = root.casefold()
        if any(value in lowered for value in ("front", "web", "ui", "client")): return "frontend"
        if any(value in lowered for value in ("migrat", "supabase", "database", "schema", "db")): return "data"
        if any(value in lowered for value in ("cli", "script", "tool")): return "tool"
        if any(value in lowered for value in ("sdk", "lib", "package")): return "library"
        return "service"

    @staticmethod
    def _path_tag(tags: list[str]) -> str | None:
        return next((tag.removeprefix("path:") for tag in tags if tag.startswith("path:")), None)

    @staticmethod
    def _timestamp(value: str | None) -> datetime | None:
        if not value:
            return None
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
