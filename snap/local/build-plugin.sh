#!/bin/sh
set -eu
# Certbot and requests come from the host Certbot snap. Only bundle this
# plugin and its additional DNS dependency in the documented content path.
: "${CRAFT_PART_INSTALL:?Snapcraft install directory is required}"
python3 -m venv .snap-build-venv
.snap-build-venv/bin/python -m pip install --disable-pip-version-check \
    --no-compile --no-deps \
    --target "$CRAFT_PART_INSTALL/lib/python3.12/site-packages" \
    . 'dnspython>=2.6,<3'
