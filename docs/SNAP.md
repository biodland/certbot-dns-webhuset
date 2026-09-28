# Certbot plugin snap

`snap/snapcraft.yaml` describes a strict content snap based on `core24`, with
Python modules exposed through the `certbot-1` content interface at
`$SNAP/lib/python3.12/site-packages`. This follows Certbot's current plugin snap
contract. The host Certbot snap supplies Certbot, ACME, and requests; the plugin
bundles itself and dnspython without installing another Certbot. There is no
standalone application in this snap.

## Build and discover

On an Ubuntu Linux host with Snapcraft and its supported build backend:

```sh
snapcraft
sudo snap install --classic certbot
sudo snap set certbot trust-plugin-with-root=ok
sudo snap install --dangerous ./certbot-dns-webhuset_0.1.0a1_amd64.snap
sudo snap connect certbot:plugin certbot-dns-webhuset:certbot
sudo /snap/bin/certbot plugins
```

Use the actual filename produced by Snapcraft. `--dangerous` permits installing
a locally built snap without Store assertions. Certbot's trust setting authorizes
plugin code to execute with Certbot's root privileges: review the source first.

The manual **Build and test Snap** GitHub workflow builds on Ubuntu, installs the
result, connects the content interface, checks plugin discovery, and retains the
snap as an artifact. It does not publish to the Store or perform DNS challenges.
After discovery, follow the README's staging issuance and renewal checks using
`/snap/bin/certbot` and a credentials file readable by root.

## Distribution

The recipe uses `grade: devel` while the plugin is alpha. Register the snap name
with the maintainer's Snap Store account, review the built artifact, and test an
edge-channel release before considering stable. Store registration, uploads, and
interface approval/automatic connections are separate external steps. This repo
does not claim the Store name is registered or that automatic connection is
approved. A stable release requires changing the grade after validation.

A pip installation does not install a plugin into the Certbot snap. Use either
a shared Python environment for pip Certbot plus plugin, or this content snap
for snap Certbot. NPM uses its own Python environment; it does not use this snap.

The snap payload can be inspected with `unsquashfs -l <file.snap>`. Verify it
contains the plugin, its distribution metadata/entry point, and dnspython, and
does not contain credentials or a duplicate Certbot. Recheck the base, Python
path, and dependency compatibility whenever Certbot changes its snap contract.

Reference: [Writing your own Certbot plugin snap](https://eff-certbot.readthedocs.io/en/stable/contributing.html#writing-your-own-plugin-snap).
