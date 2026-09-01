# Team-Aware Product Workflow Contract

NodeFlow is multi-tenant: the product flow is always **current user → active team → project**. This document defines the integration boundary for collaboration/product workflows; it does not define authentication, user management, team persistence, or tenant isolation.

## Upstream integration required

Aayush's authentication/team middleware must attach a callable `team_project_resolver` to `app.state`. For each request it returns:

```python
ActiveTeamProjectAccess(
    user_id="authenticated-user-id",
    active_team_id=UUID("..."),
    authorized_project_ids=frozenset({UUID("project-in-active-team")}),
)
```

Railway production must set `app.state.require_team_scope = True`. If the resolver is unavailable, product workflow routes fail with `503`; if the project is not authorized for the active team, they fail with `403`. The in-memory demo deliberately allows unscoped access and must not be used as a deployment authorization mode.

## Enforced product routes

- Collaboration state and approval decisions
- GitHub event ingestion and Git activity
- Role-aware onboarding and agent context/update/message workflows
- Git or approval-shaped events submitted through the generic event API

This ensures a GitHub event is accepted only for a project selected within the caller's active team. The event remains project-scoped; NodeFlow does not create global Git events.

For non-human GitHub deliveries, the integration service identity must resolve to the project/team that owns the connected repository. It cannot use a global webhook identity with unrestricted project access.

## Shared-team demo story

1. Prem, Aarya, Sunal, Aayush, and Namish sign in to the deployed instance.
2. Each selects **HackVerse Team** as the active team and opens the same NodeFlow project.
3. A backend GitHub event is ingested for that project; impact reaches only that project's related agents.
4. A human reviews the resulting approval from the collaboration workflow.
5. Every laptop reads the same project intelligence and collaboration result from the shared backend.

Team switching must clear project-specific UI state and require a newly authorized project selection before any product API call.
