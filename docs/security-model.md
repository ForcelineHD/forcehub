# Security Model

ForceHub is designed for local-first operation. Public documentation and examples should be safe to review without exposing private infrastructure details.

## Local-Only Default Posture

ForceHub should bind to loopback by default. Local services should not be exposed to a LAN, VPN, tunnel, or public network unless the operator intentionally changes the configuration and understands the risk.

Default example binding:

```dotenv
FORCEHUB_BIND_HOST=127.0.0.1
FORCEHUB_BIND_PORT=8001
```

## API Access

API routes that read sensitive local state or trigger actions should require token-based access. Example values use placeholders only:

```dotenv
FORCEHUB_API_TOKEN=change-me
```

Do not reuse example tokens. Generate a local value for private development and keep it in an untracked `.env` file.

## Secret Hygiene

Never commit:

- Secrets, tokens, passwords, or API keys.
- Real `.env` files.
- Private IP addresses, hostnames, usernames, or machine-specific paths.
- Tunnel configuration, VPN details, or provider-specific connection data.
- Screenshots, logs, diagnostics, or generated output containing sensitive context.

## Logs and Runtime Data

Logs, databases, runtime output, generated reports, and local state are excluded from Git. Public examples should use synthetic or placeholder data only.

Ignored runtime categories include:

- `data/`
- `logs/`
- `runtime/`
- database files
- local virtual environments
- build output

## Safe Public Examples

Public examples should demonstrate structure and intent, not private environment details. Use generic hostnames, placeholder tokens, and loopback addresses when examples require configuration.
