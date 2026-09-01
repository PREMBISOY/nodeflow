# Team-Aware Product Workflows

NodeFlow's shared cloud flow is **authenticated user → active team → project**. The signed session supplies the active team; routes never accept a team ID as an authority override.

Collaboration timelines and approvals, GitHub ingestion and activity, generic events, agent context/updates/messages, and onboarding must all target a project belonging to the caller's active team. A project outside that boundary is returned as not found, preventing cross-tenant discovery.

For the demo, every team member signs in, chooses **HackVerse Team**, and opens the same authorized project. A GitHub event affects only agents and collaboration state inside that project. Switching teams clears the project selection and obtains a fresh authorized context.
