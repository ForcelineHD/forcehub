# Contributing

Thanks for considering a contribution to ForceHub.

ForceHub is a public, local-first IT automation and AI tooling project. Contributions should stay clear, focused, and safe for public review.

## Workflow

1. Fork the repository.
2. Create a focused branch for your change.
3. Keep commits and pull requests small enough to review.
4. Open a pull request with a clear summary of what changed and why.

Use GitHub issues and pull requests for project discussions, bug reports, feature ideas, and review comments.

## Public-Safety Rules

Do not commit:

- Secrets, tokens, passwords, API keys, or credentials.
- Real `.env` files or private configuration values.
- Logs, runtime data, databases, generated reports, or build output.
- Screenshots containing sensitive information.
- Private IP addresses, private file paths, hostnames, or environment-specific details.

Use placeholder values in examples and documentation.

## Checks

Before opening a pull request, run relevant checks when available:

```bash
python -m pytest
go test ./...
cargo test --manifest-path rust/forcehub-secscan/Cargo.toml
```

If a check is not available in your environment, mention that in the pull request.

## Scope

Keep each pull request focused on one change. Separate unrelated code, documentation, formatting, and cleanup work into different pull requests when practical.
