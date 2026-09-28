# Local validation — 2026-09-28

Environment: Linux containers on Docker Desktop, Python 3.12.14.

- Certbot 5.8.0: 55 tests passed; 91% statement coverage.
- Certbot 4.0.0 with ACME 4.0.0: 55 tests passed.
- Ruff formatting and lint checks passed.
- `certbot plugins` discovers the installed `dns-webhuset` entry point.
- Wheel and source distribution build successfully; `twine check --strict` passes.
- Wheel includes the MIT license and SPDX license metadata.
- GitHub Actions workflows pass actionlint, including embedded shell checks.
- Snap payload build script runs on Linux; Certbot discovers its plugin modules.
  The payload contains the plugin and dnspython, without duplicate Certbot/ACME.

Tests cover JSON/SSE MCP transport, API errors and credential redaction, SOA
zone discovery, IDNs, multi-zone certificates, apex/wildcard coexistence,
pre-existing values, exact-value cleanup, partial failures, lost write responses,
read-only preflight and package discovery. HTTP/DNS responses are simulated.

Certbot 3.3 was investigated but is not supported: its older dependency set
conflicts with current PyOpenSSL. The declared support range starts at Certbot 4.

Not yet verified:

- Authentication and response formats against a live Webhuset account.
- Real DNS propagation and Let's Encrypt staging issuance/renewal.
- Nginx Proxy Manager UI/provider integration and reload behavior.
- Full Snapcraft build and installation/content connection under snapd. The
  manual Snap workflow performs these checks on Ubuntu when dispatched.
- Python 3.10 and 3.14 CI matrix jobs (local checks above used Python 3.12).
- GitHub-hosted workflows and PyPI/TestPyPI Trusted Publisher configuration.

These checks need a user-configured API key and a disposable test domain or
an explicitly selected production domain for staging DNS validation. No live DNS
changes, certificate requests or publishing were performed during development.
