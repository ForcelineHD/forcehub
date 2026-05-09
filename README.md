# ForceHub

**Local-first IT / automation / local-AI dashboard**

ForceHub is an active development project for organizing local infrastructure workflows, diagnostics, automation, and local AI tooling in one dashboard-oriented workspace.

The public version of this repository is designed as a clean portfolio-safe foundation. It documents the project direction, expected modules, safe configuration patterns, and security model without exposing private infrastructure, runtime data, credentials, or local environment details.

## Project Status

**Active development**

This repository currently provides the public-safe foundation for ForceHub. Implementation modules will be added only after they are reviewed, sanitized, and documented for public release.

## Planned Architecture

| Component | Direction |
|---|---|
| FastAPI backend | Local API service for dashboard data, automation endpoints, diagnostics, and local workflow orchestration. |
| Go agent | Lightweight local agent for system checks, command execution wrappers, and host diagnostics using explicit allowlists. |
| Local dashboard | Browser-based interface for viewing system state, running safe workflows, and organizing infrastructure notes. |
| Local AI tooling | Ollama-backed helpers for summarizing notes, generating command drafts, and supporting developer workflows. |
| Configuration examples | Public-safe `.env.example` values and documented placeholder configuration. |
| Automation and diagnostics | Repeatable scripts and workflows for IT support, Linux labs, networking checks, and troubleshooting. |

## Core Goals

- Keep ForceHub local-first by default.
- Support practical IT infrastructure and troubleshooting workflows.
- Provide safe examples for FastAPI services, Go agents, local dashboards, and local AI integrations.
- Use clear documentation for setup, architecture, and security boundaries.
- Avoid committing private data, runtime artifacts, logs, secrets, or infrastructure-specific details.

## Planned Features

- FastAPI service with health checks and authenticated local API routes.
- Go-based local agent for controlled diagnostics.
- Dashboard views for systems, services, workflows, and notes.
- Safe example configuration for local development.
- Automation examples for Windows, Linux, networking, and lab environments.
- Local AI workflow helpers using Ollama.
- Future CI checks for repository hygiene and expected file structure.

## Repository Structure

```text
forcehub/
├─ README.md
├─ LICENSE
├─ SECURITY.md
├─ .gitignore
├─ .env.example
└─ docs/
   ├─ architecture.md
   ├─ setup.md
   └─ security-model.md
```

## Safe Setup

These instructions use placeholders only. Review configuration before running any future ForceHub service locally.

```bash
cd forcehub
cp .env.example .env
```

Example local configuration:

```dotenv
FORCEHUB_API_TOKEN=change-me
FORCEHUB_BIND_HOST=127.0.0.1
FORCEHUB_BIND_PORT=8001
FORCEHUB_LOG_LEVEL=info
FORCEHUB_OLLAMA_BASE_URL=http://127.0.0.1:11434
```

Do not commit the generated `.env` file. Keep local tokens, host details, logs, databases, and runtime output outside Git.

## Security & Privacy

ForceHub is intended to run locally by default. Public examples use sanitized placeholder values and avoid private infrastructure details.

Public repository content must not include:

- Secrets, tokens, passwords, or API keys.
- Private IP addresses, local hostnames, tunnel details, or private file paths.
- Runtime data, logs, databases, screenshots, or sensitive diagnostics.
- Real infrastructure notes that identify private systems or environments.

See [SECURITY.md](SECURITY.md) and [docs/security-model.md](docs/security-model.md) for the public-safe security model.

## Documentation

- [Architecture](docs/architecture.md)
- [Setup](docs/setup.md)
- [Security Model](docs/security-model.md)

## License

This project is licensed under the MIT License. See [LICENSE](LICENSE).
