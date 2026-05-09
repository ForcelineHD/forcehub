# Architecture

ForceHub is planned as a local-first dashboard for IT infrastructure workflows, diagnostics, automation, and local AI tooling.

The public architecture is intentionally high-level. It describes the project shape without exposing private systems, local network details, machine names, or runtime data.

## Components

| Component | Responsibility |
|---|---|
| FastAPI backend | Provides local API routes, health checks, configuration loading, dashboard data, and controlled automation endpoints. |
| Go agent | Runs local diagnostics and system checks through explicit allowlists and safe execution boundaries. |
| Dashboard | Presents system state, workflow shortcuts, notes, and diagnostic output in a local browser interface. |
| Local AI layer | Uses local model tooling such as Ollama for workflow assistance, note summarization, and command drafting. |
| Configuration | Uses example-based configuration with placeholder values and local-only defaults. |
| Future modules | Windows checks, Linux checks, networking diagnostics, service health views, and documentation helpers. |

## Data Flow

1. The dashboard sends requests to the local FastAPI backend.
2. The backend validates configuration and API access.
3. The backend calls approved local workflows or communicates with the Go agent.
4. The Go agent runs allowed diagnostics and returns sanitized results.
5. Local AI helpers may process user-provided notes or command drafts without requiring cloud services.

## Design Principles

- Local-first operation by default.
- Explicit authentication for API routes that perform actions.
- No committed runtime data or private configuration.
- Clear separation between examples, local configuration, and generated output.
- Public-safe documentation before public code release.
