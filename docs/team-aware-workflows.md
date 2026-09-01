# Team-Aware Product Workflows

NodeFlow's shared cloud flow is **authenticated user → active team → project**. The signed session supplies the active team; routes never accept a team ID as an authority override.

Creating a team makes that user its leader (`OWNER`). The dashboard may show
the team's members to every member. Only the creator can add an existing
NodeFlow account by email or remove a participant; the creator cannot be
removed. This leaves every team with a durable leader while keeping ordinary
participants out of membership administration.

Collaboration timelines and approvals, GitHub ingestion and activity, generic events, agent context/updates/messages, and onboarding must all target a project belonging to the caller's active team. A project outside that boundary is returned as not found, preventing cross-tenant discovery.

For the demo, every team member signs in, chooses **HackVerse Team**, and opens the same authorized project. A GitHub event affects only agents and collaboration state inside that project. Switching teams clears the project selection and obtains a fresh authorized context.

For the dashboard's **Team Members** view, read
`GET /api/v1/teams/{teamId}/members` and render `id`, `name`, and `role`.
Show add/remove controls only for the team creator; the server remains the
authority and returns `403` for non-leaders.
