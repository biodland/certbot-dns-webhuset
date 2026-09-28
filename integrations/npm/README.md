# Nginx Proxy Manager integration

`provider.json` is a provider-registration **draft**, matching NPM's documented
source registry structure. It is not a drop-in extension for the stock image.
The plugin package is not published on PyPI yet, so NPM cannot currently install
it from the default package index.

For upstream integration:

1. Verify the plugin against a real Webhuset account using Let's Encrypt staging.
2. Build/publish a tested Python package, or make its wheel available in a custom image.
3. Add the `webhuset` entry to `backend/certbot/dns-plugins.json` in an NPM checkout.
4. Follow the pinned NPM version's build process so the frontend, API schema and
   backend all recognize the new provider. Changing only a running container's
   backend JSON may leave the provider absent from the UI or rejected by validation.
5. Verify compatibility with the image's Certbot version, install the package in
   `/opt/certbot`, and test create/renew/reload through NPM in a disposable instance.

The provider has the conventional `--dns-webhuset-credentials` and
`--dns-webhuset-propagation-seconds` flags. When fully integrated, NPM manages
the certificate lifecycle; a separate cron job and upload script are unnecessary.

Until then, use standalone Certbot with a deployment hook if certificates must
be sent to an existing NPM installation. The previous domain-specific approach,
when present under `legacy/`, is kept as a migration reference only.

References:

- https://github.com/NginxProxyManager/nginx-proxy-manager/blob/develop/backend/certbot/dns-plugins.json
- https://github.com/NginxProxyManager/nginx-proxy-manager/blob/develop/backend/lib/certbot.js
