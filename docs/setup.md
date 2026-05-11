# Setup

This document describes a safe local setup flow for the public ForceHub foundation. It uses placeholders only and avoids private machine names, private addresses, local usernames, integration details, and environment-specific paths.

## Prerequisites

Planned implementation modules may use:

- Python 3.12 or newer for the FastAPI backend.
- Go 1.22 or newer for the local agent.
- Node.js or another frontend toolchain for the dashboard if needed.
- Ollama for optional local AI workflows.

## Configuration

Create a local configuration file from the example:

```bash
cp .env.example .env
```

Example values:

```dotenv
FORCEHUB_API_TOKEN=change-me
FORCEHUB_BIND_HOST=127.0.0.1
FORCEHUB_BIND_PORT=8001
FORCEHUB_LOG_LEVEL=info
FORCEHUB_OLLAMA_BASE_URL=http://127.0.0.1:11434
```

Replace placeholder values only in your local `.env` file. Do not commit local configuration.

## Future Backend Workflow

When the FastAPI backend is published, the expected local flow will be:

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --host 127.0.0.1 --port 8001
```

On Windows PowerShell, activate the virtual environment with the platform-specific activation script from `.venv`.

## Future Go Agent Workflow

When the Go agent is published, it should run locally with explicit configuration and safe defaults:

```bash
go test ./...
go run ./cmd/forcehub-agent
```

The agent should not run privileged commands unless the command is documented, allowlisted, and intentionally enabled by the operator.

## Runtime Files

Runtime output belongs outside Git. The repository ignore rules exclude local data, logs, databases, runtime directories, virtual environments, build output, and dependency folders.
