"""Read-only credential/zone check, independent of certificate issuance."""

import argparse
import sys

from certbot import errors
from certbot.plugins.dns_common import CredentialsConfiguration

from .dns_api import DNSClient, normalize_name
from .mcp import MCPClient


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--credentials", required=True)
    parser.add_argument("--domain", required=True, action="append", help="May be repeated.")
    args = parser.parse_args()
    client = None
    try:
        credentials = CredentialsConfiguration(args.credentials, lambda key: "dns_webhuset_" + key)
        credentials.require({"api_key": "a Webhuset API key"})
        key = credentials.conf("api_key")
        if not isinstance(key, str) or "\n" in key or "\r" in key:
            raise errors.PluginError("The API key must be a single line.")
        api = MCPClient(key)
        client = DNSClient(api, zone_override=credentials.conf("zone"))
        api.check_tools()
        for domain in args.domain:
            name = "_acme-challenge." + normalize_name(domain.removeprefix("*."))
            zone = client.discover_zone(name)
            records = client.records(zone)
            print(
                f"OK: {domain} -> zone {zone}; {len(records)} DNS records readable. "
                "No changes made."
            )
        return 0
    except errors.PluginError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    finally:
        if client:
            client.close()


if __name__ == "__main__":
    sys.exit(main())
