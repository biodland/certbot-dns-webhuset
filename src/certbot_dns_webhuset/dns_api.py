"""Zone discovery and value-specific TXT operations."""

from dataclasses import dataclass

import dns.exception
import dns.name
import dns.resolver
from certbot import errors

from .mcp import APIError


def normalize_name(value):
    try:
        name = dns.name.from_text(value.rstrip(".")).canonicalize()
    except (dns.exception.DNSException, UnicodeError, ValueError):
        raise errors.PluginError("Invalid DNS name.") from None
    if len(name.labels) < 3:  # A single-label zone/TLD is never a customer zone.
        raise errors.PluginError("Expected a fully qualified DNS name below a top-level domain.")
    return name.to_text(omit_final_dot=True)


def within(name, zone):
    return name == zone or name.endswith("." + zone)


@dataclass(frozen=True)
class Record:
    zone: str
    name: str
    value: str

    def arguments(self):
        return {"domain": self.zone, "fqdn": self.name, "type": "TXT", "value": self.value}


def zone_records(payload):
    """Parse known Webhuset zone shapes, never treat an unknown reply as empty DNS."""
    for _ in range(4):
        if isinstance(payload, dict) and "all" in payload:
            groups = payload["all"]
            if not isinstance(groups, dict) or not all(
                isinstance(v, list) for v in groups.values()
            ):
                break
            result = []
            for kind, entries in groups.items():
                for entry in entries:
                    if not isinstance(entry, dict):
                        raise APIError("Invalid record in Webhuset DNS response.")
                    result.append({**entry, "type": str(entry.get("type", kind)).upper()})
            return result
        if isinstance(payload, dict) and isinstance(payload.get("records"), list):
            payload = payload["records"]
        elif isinstance(payload, dict) and "data" in payload:
            payload = payload["data"]
        elif isinstance(payload, dict) and "result" in payload:
            payload = payload["result"]
        elif isinstance(payload, list):
            if all(isinstance(r, dict) and "type" in r for r in payload):
                return payload
            break
        else:
            break
    raise APIError("Unsupported Webhuset check_dns response shape. No DNS changes were inferred.")


def record_name(entry, zone):
    value = entry.get("fqdn")
    if value:
        return normalize_name(value)
    if "name" in entry:
        relative = entry["name"]
        if relative in ("", "@"):
            return zone
        if isinstance(relative, str):
            absolute = relative.rstrip(".").lower()
            return normalize_name(absolute if within(absolute, zone) else absolute + "." + zone)
    raise APIError("A Webhuset DNS record has no usable name.")


class DNSClient:
    def __init__(self, api, zone_override=None, timeout=30, resolver=None):
        self.api = api
        self.zone_override = normalize_name(zone_override) if zone_override else None
        self.timeout = timeout
        self.resolver = resolver or dns.resolver.Resolver()
        self.zones = {}

    def discover_zone(self, validation_name):
        name = normalize_name(validation_name)
        if name in self.zones:
            return self.zones[name]
        # Do not accidentally write in a parent zone when the challenge is delegated.
        try:
            cname = self.resolver.resolve(
                name + ".", "CNAME", lifetime=self.timeout, raise_on_no_answer=False
            )
            if cname.rrset:
                raise errors.PluginError(
                    f"{name} is a CNAME. Challenge delegation is not supported in this release."
                )
        except (dns.resolver.NXDOMAIN, dns.resolver.NoAnswer):
            pass
        except dns.exception.DNSException:
            raise errors.PluginError(f"DNS lookup failed for {name}; check the resolver.") from None
        if self.zone_override:
            zone = self.zone_override
        else:
            try:
                discovered = dns.resolver.zone_for_name(
                    dns.name.from_text(name + "."),
                    resolver=self.resolver,
                    lifetime=self.timeout,
                )
                zone = normalize_name(discovered.to_text())
            except dns.exception.DNSException:
                raise errors.PluginError(
                    f"Could not discover the authoritative zone for {name}. "
                    "Check DNS or set dns_webhuset_zone in the credentials file."
                ) from None
        if not within(name, zone):
            raise errors.PluginError(f"{name} is outside the configured Webhuset zone {zone}.")
        self.zones[name] = zone
        return zone

    def records(self, zone):
        return zone_records(self.api.call("check_dns", {"domain": zone}))

    def contains(self, record, entries=None):
        entries = self.records(record.zone) if entries is None else entries
        for entry in entries:
            if str(entry.get("type", "")).upper() != "TXT":
                continue
            if record_name(entry, record.zone) != record.name:
                continue
            if "txt" not in entry and "value" not in entry:
                raise APIError("A Webhuset TXT record has no readable value; refusing to guess.")
            # Values are raw strings in the HAR; do not strip user data or quotes.
            if entry.get("txt", entry.get("value")) == record.value:
                return True
        return False

    def prepare(self, validation_name, validation):
        name = normalize_name(validation_name)
        if not name.startswith("_acme-challenge."):
            raise errors.PluginError("Refusing to manage a record outside _acme-challenge.")
        zone = self.discover_zone(name)
        record = Record(zone, name, validation)
        entries = self.records(zone)  # Verify access before recording a mutation attempt.
        for entry in entries:
            if str(entry.get("type", "")).upper() == "CNAME" and record_name(entry, zone) == name:
                raise errors.PluginError("A CNAME exists at the challenge name; no changes made.")
        return record, self.contains(record, entries)

    def create(self, record):
        # Never retry a write automatically: a lost response may mean it succeeded.
        self.api.call("create_dns_record", {**record.arguments(), "ttl": 600})
        if not self.contains(record):
            raise APIError("Webhuset did not report the new TXT value after creation.")

    def delete(self, record):
        if self.contains(record):
            self.api.call("delete_dns_record", record.arguments())
            if self.contains(record):
                raise APIError("Webhuset still reports the TXT value after deletion.")

    def close(self):
        self.api.close()
