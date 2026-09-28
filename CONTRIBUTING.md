# Contributing

Use Python 3.10 or newer on Linux. Install in a virtual environment:

```sh
python3 -m venv .venv
. .venv/bin/activate
pip install -e '.[test]'
ruff check .
pytest --cov=certbot_dns_webhuset
python -m build
twine check --strict dist/*
```

Tests must use simulated DNS/HTTP responses. Never commit credentials, private
keys, certificate storage, or HAR captures. Include regression tests for changes
to record selection, cleanup, response parsing, and error handling. Preserve
unrelated DNS records and sanitize API errors. Live checks use a dedicated test
zone and Let's Encrypt staging; see [validation](docs/VALIDATION.md).

The distribution name is `certbot-dns-webhuset`; the Certbot entry point is
`dns-webhuset`, and Python imports use `certbot_dns_webhuset`. Keep the version
in `pyproject.toml` and the NPM provider draft synchronized. Contributions are
provided under the repository's MIT license.

See [release instructions](docs/RELEASING.md) and [Snap packaging](docs/SNAP.md).
