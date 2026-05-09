# Security Policy

ForceHub is a local-first IT, automation, and local-AI dashboard project. The public repository is designed to contain sanitized examples, documentation, and code that can be reviewed without exposing private infrastructure details.

## Supported Status

ForceHub is in active development. Public security expectations apply to all files committed to this repository, including examples, documentation, workflows, and future implementation modules.

## Public Repository Safety

Do not commit:

- Secrets, tokens, passwords, or API keys.
- Real `.env` files or machine-specific configuration.
- Private IP addresses, internal hostnames, private file paths, or tunnel details.
- Runtime data, logs, database files, screenshots, or sensitive diagnostics.
- Notes that identify private infrastructure or operational environments.

Public examples must use placeholder values only. The committed `.env.example` file is intentionally non-sensitive and should not contain real credentials.

## Local-First Design

ForceHub should bind to local interfaces by default and require explicit configuration before any broader network exposure. API access should use token-based controls for local development and avoid unauthenticated privileged actions.

## Reporting Security Issues

If you find a public-safety issue in this repository, open a GitHub issue with a high-level description. Do not include secrets, private infrastructure details, logs, or screenshots containing sensitive data.
