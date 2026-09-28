#!/usr/bin/env bash
set -euo pipefail
BASE=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
# ID styres i automation.json; ingen interaktiv innlogging eller nye oppfoeringer.
exec python3 "$BASE/automation.py" deploy
