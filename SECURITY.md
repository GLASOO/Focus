# Security Policy

## Supported Versions

| Version | Supported |
|---|---|
| 2.0.x | ✅ |

## Reporting a Vulnerability

Please do **not** open a public issue for security problems.

- Report privately via GitHub **Security → Advisories → New draft advisory**
  on this repository, or by opening an issue titled `[security]` with no
  reproduction details in the body and asking for a private channel.
- You should receive an acknowledgment within 72 hours.
- Scope note: the tool layer executes model-proposed commands by design;
  the safety boundary is the directory allowlist (`FOCUS_TOOL_DIRS`) plus the
  forbidden-command list in `focus/tools.py`. Bypasses of that boundary are
  security issues and are treated as high priority.

## Safe defaults

- Tools are confined to the repository directory and `/tmp` unless you
  explicitly widen `FOCUS_TOOL_DIRS`.
- The HTTP UI binds to `127.0.0.1` only.
