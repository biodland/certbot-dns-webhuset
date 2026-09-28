#!/usr/bin/env bash
set -euo pipefail
export PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin:/snap/bin
BASE=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
exec 9>/run/lock/communitynord-certbot.lock
flock -n 9 || exit 0

MODE=${1:-renew}
case "$MODE" in
  renew|test|configure) ;;
  *) echo "Bruk: $0 [renew|test|configure]" >&2; exit 2 ;;
esac

COMMON=(--cert-name communitynord.com --non-interactive
  --manual --preferred-challenges dns
  --manual-auth-hook "$BASE/auth.sh"
  --manual-cleanup-hook "$BASE/cleanup.sh"
  --deploy-hook "$BASE/copytonpm.sh")

case "$MODE" in
  configure)
    # Certbot >= 2.3: tester mot staging og lagrer fornyelsesinnstillingene.
    certbot reconfigure "${COMMON[@]}"
    ;;
  test)
    # Ingen --run-deploy-hooks: staging-sertifikater sendes ikke til NPM.
    certbot renew "${COMMON[@]}" --dry-run
    ;;
  renew)
    certbot renew "${COMMON[@]}" --quiet
    # Ogsaa ved ingen fornyelse: proev igjen hvis forrige NPM-opplasting feilet.
    "$BASE/copytonpm.sh"
    ;;
esac
