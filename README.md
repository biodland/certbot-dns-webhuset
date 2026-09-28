# certbot-dns-webhuset

A general DNS-01 plugin for Certbot, with support for common domains, wildcards,
subdomains, and certificates covering multiple DNS zones at Webhuset.

**Status: 0.1.0a1, local alpha release.** The package is not published on PyPI and is
not included in the standard Nginx Proxy Manager. Tests with simulated API responses
do not replace a successful staging issuance against a real Webhuset account.

The plugin uses Webhuset's documented MCP endpoint directly. No AI model,
web browser, HAR file, or session cookie is used. Domains are selected with Certbot's
standard `-d` arguments; no domain names, account numbers, or NPM IDs are hardcoded in the package.

## Install on Linux

Install Python 3.10 or newer with venv support. From this directory:

```bash
python3 -m venv /opt/certbot-webhuset
/opt/certbot-webhuset/bin/pip install .
/opt/certbot-webhuset/bin/certbot plugins
```

The list should show `dns-webhuset`. Install the plugin in the same Python environment as
Certbot. Installing with pip outside an existing snap-based Certbot does not make the plugin available in the snap installation. The examples therefore use a dedicated venv and absolute paths. Installed Certbot versions are supported in the range `>=4,<6`.

Create an API key in the Webhuset customer center with **DNS → Manage**.
The plugin does not use `list_domains` and does not require read access to the domain overview.

```bash
install -d -m 700 /etc/letsencrypt/credentials
install -m 600 examples/webhuset.ini.example /etc/letsencrypt/credentials/webhuset.ini
nano /etc/letsencrypt/credentials/webhuset.ini
```

Set the key in the file:

```ini
dns_webhuset_api_key = YOUR_API_KEY
```

## Check access without changing DNS

```bash
/opt/certbot-webhuset/bin/certbot-dns-webhuset-check \
  --credentials /etc/letsencrypt/credentials/webhuset.ini \
  --domain example.com \
  --domain other.no
```

The command checks the available API tools, finds the DNS zones, and reads them.
It shows no API key or DNS values. If Webhuset returns an undocumented data structure that is not supported, the plugin stops with a clear error.
Keep the key local; during troubleshooting, the error message and possibly the structure from an anonymized response are needed, not the credential itself.

## Test against Let's Encrypt staging

Replace the sample names and email address with your own. A dry run creates and deletes real TXT validation records, but does not retain a new production certificate.

```bash
/opt/certbot-webhuset/bin/certbot certonly \
  --authenticator dns-webhuset \
  --dns-webhuset-credentials /etc/letsencrypt/credentials/webhuset.ini \
  --non-interactive --agree-tos --email admin@example.com \
  --cert-name example.com \
  -d example.com -d '*.example.com' -d '*.admin.example.com' \
  --dry-run
```

When the test succeeds, run the same command without `--dry-run` for production.
For another domain, you only need to change the `--cert-name` and `-d` arguments. One key can be used for multiple domains it is allowed to access. Certificates from different Webhuset accounts can each use their own credentials file.

A certificate across zones:

```bash
/opt/certbot-webhuset/bin/certbot certonly \
  --authenticator dns-webhuset \
  --dns-webhuset-credentials /etc/letsencrypt/credentials/webhuset.ini \
  --non-interactive --agree-tos --email admin@example.com \
  --cert-name shared-services \
  -d app.example.com -d '*.other.no' --dry-run
```

## Renewal

Certbot stores the plugin choice and credentials path in the certificate renewal configuration.
Use the same Certbot installation when renewing:

```bash
/opt/certbot-webhuset/bin/certbot renew --dry-run
/opt/certbot-webhuset/bin/certbot renew --quiet
```

Use an existing timer that runs this Certbot installation, or install
`examples/certbot-webhuset.cron` as `/etc/cron.d/certbot-webhuset` with root as owner and mode 0644. It checks twice a day; Certbot decides when renewal is needed.
Do not add an extra job if the correct Certbot is already running automatically.
You may also add a custom `--deploy-hook` for the service that should use the certificate.
This DNS plugin does not install certificates in NPM or other web servers.

An existing certificate with manual DNS hooks can be migrated with:

```bash
/opt/certbot-webhuset/bin/certbot reconfigure \
  --cert-name YOUR_EXISTING_CERTIFICATE_NAME \
  --authenticator dns-webhuset \
  --dns-webhuset-credentials /etc/letsencrypt/credentials/webhuset.ini
```

`reconfigure` tests against staging before saving the new settings. An existing deploy hook may still be active; check it before production renewal.
The scripts from the previous solution are kept under `legacy/` when preserved in the repository. They are not part of the Python package or Docker image.

## Zone selection, wait time, and limitations

- Automatic zone selection uses DNS SOA lookups, not "the last two labels of the domain".
  This also works with zones like `example.co.uk` and delegated subzones, provided the Webhuset API grants the key access to exactly that zone.
- For special DNS setups, `dns_webhuset_zone = example.com` can be set in the credentials file. This limits the file to that zone; omit it for multiple zones.
- CNAME delegation on `_acme-challenge` is not supported in this version. The plugin stops instead of writing a TXT record in the wrong zone.
- All challenge values are created before a single shared wait period, default **600 seconds**.
  Change this with `--dns-webhuset-propagation-seconds 900` for slower DNS propagation.
  The wait time is not a guarantee of global propagation; the ACME server performs the validation.
- API and DNS lookups use a default 30-second timeout, adjustable with `--dns-webhuset-http-timeout`. There are no automatic retries for write operations.
- Cleanup only deletes the exact name/value that this run attempted to add. Existing identical values are preserved. Apex and wildcard entries may have multiple concurrent TXT values on the same name. Other DNS records are not changed.
- Errors after partial creation trigger cleanup. If the server becomes unavailable or the process is terminated abruptly, a TXT value may remain. Cleanup errors are logged without API keys or challenge values; this should be monitored.
- Webhuset documents tool names and parameters, but not all response formats.
  Parsing supports structured MCP responses or JSON in text content, with DNS data under keys such as `all` (observed in HAR) or a `records` list. Unknown responses are rejected.

## Docker

```bash
docker build -t certbot-webhuset:local .
docker run --rm certbot-webhuset:local plugins
```

For issuance/renewal, `/etc/letsencrypt` and the credentials file must be mounted from the server so that both certificates and renewal configuration are preserved. Example:

```bash
docker run --rm \
  -v /etc/letsencrypt:/etc/letsencrypt \
  certbot-webhuset:local renew --dry-run
```

This is a standalone Certbot image. The NPM integration is described in [`integrations/npm/README.md`](integrations/npm/README.md).

## Development and packaging

```bash
python3 -m venv .venv
. .venv/bin/activate
pip install -e '.[test]'
ruff check .
pytest --cov=certbot_dns_webhuset
python -m build
twine check dist/*
```

Or test with Linux/Docker:

```bash
docker build --target test -t certbot-webhuset:test .
docker run --rm certbot-webhuset:test
```

The tests use simulated HTTP/DNS responses and real Certbot plugin loading. No production DNS or ACME account is changed. Before public publication, staging issuance and renewal against Webhuset, license choice, project owner/publishing account, and verified NPM integration still remain. No automatic publication is configured.

## References

- [Webhuset MCP tools](https://www.webhuset.no/mcp/docs)
- [Webhuset API keys](https://www.webhuset.no/hjelp/min-konto/api-n-kler-koble-ai-assistenter-og-automatisering-til-webhuset-mcp)
- [Certbot DNSAuthenticator](https://eff-certbot.readthedocs.io/en/stable/api/certbot.plugins.dns_common.html)
- [Certbot renewal](https://eff-certbot.readthedocs.io/en/stable/using.html#renewing-certificates)
