from unittest.mock import Mock

import dns.name
import dns.resolver
import pytest
from certbot import errors

from certbot_dns_webhuset.dns_api import (
    DNSClient,
    Record,
    normalize_name,
    record_name,
    zone_records,
)
from certbot_dns_webhuset.mcp import APIError


def client(zone=None):
    resolver = Mock()
    resolver.resolve.return_value.rrset = None
    return DNSClient(Mock(), zone_override=zone, resolver=resolver)


@pytest.mark.parametrize(
    "name,zone",
    [
        ("_acme-challenge.example.com", "example.com"),
        ("_acme-challenge.admin.example.com", "example.com"),
        ("_acme-challenge.example.co.uk", "example.co.uk"),
        ("_acme-challenge.sub.example.com", "sub.example.com"),
    ],
)
def test_soa_discovery_does_not_guess_last_two_labels(monkeypatch, name, zone):
    lookup = Mock(return_value=dns.name.from_text(zone))
    monkeypatch.setattr(dns.resolver, "zone_for_name", lookup)
    api = client()
    assert api.discover_zone(name) == zone
    assert api.discover_zone(name) == zone
    lookup.assert_called_once()


def test_zone_discovery_multiple_domains(monkeypatch):
    monkeypatch.setattr(
        dns.resolver,
        "zone_for_name",
        Mock(side_effect=[dns.name.from_text("example.com"), dns.name.from_text("other.no")]),
    )
    api = client()
    assert api.discover_zone("_acme-challenge.example.com") == "example.com"
    assert api.discover_zone("_acme-challenge.other.no") == "other.no"


def test_override_cannot_escape_zone():
    api = client("example.com")
    with pytest.raises(errors.PluginError, match="outside"):
        api.discover_zone("_acme-challenge.notexample.com")


def test_cname_delegation_rejected():
    api = client("example.com")
    api.resolver.resolve.return_value.rrset = ["elsewhere.test"]
    with pytest.raises(errors.PluginError, match="CNAME"):
        api.discover_zone("_acme-challenge.example.com")
    api.api.call.assert_not_called()


def test_dns_lookup_failure_is_not_treated_as_missing_zone():
    api = client()
    api.resolver.resolve.side_effect = dns.resolver.LifetimeTimeout()
    with pytest.raises(errors.PluginError, match="DNS lookup failed"):
        api.discover_zone("_acme-challenge.example.com")


def test_idn_and_trailing_dot():
    assert normalize_name("BØ.no.") == "xn--b-5ga.no"


def test_parse_har_style_and_wrapped_records():
    record = {"fqdn": "_acme-challenge.example.com", "txt": "token"}
    parsed = zone_records({"status": 1, "all": {"txt": [record], "a": []}})
    assert parsed == [{**record, "type": "TXT"}]
    assert zone_records({"data": {"records": parsed}}) == parsed


@pytest.mark.parametrize(
    "payload", [{"status": 1}, {"all": None}, ["not a record"], {"all": {"txt": "not a list"}}]
)
def test_unknown_zone_shape_fails_closed(payload):
    with pytest.raises(APIError):
        zone_records(payload)


def test_record_names_can_be_relative_or_absolute():
    assert record_name({"name": "_acme-challenge"}, "example.com") == "_acme-challenge.example.com"
    assert record_name({"name": "@"}, "example.com") == "example.com"


def test_create_checks_api_readback_and_uses_fqdn():
    api = client("example.com")
    record = Record("example.com", "_acme-challenge.example.com", "token")
    api.api.call.side_effect = [
        {"status": 1},
        {"all": {"txt": [{"fqdn": record.name, "txt": record.value}]}},
    ]
    api.create(record)
    assert api.api.call.call_args_list[0].args == (
        "create_dns_record",
        {**record.arguments(), "ttl": 600},
    )


def test_delete_preserves_other_values_and_skips_already_absent():
    api = client("example.com")
    record = Record("example.com", "_acme-challenge.example.com", "ours")
    ours = {"fqdn": record.name, "txt": "ours"}
    theirs = {"fqdn": record.name, "txt": "theirs"}
    api.api.call.side_effect = [
        {"all": {"txt": [ours, theirs]}},
        {"status": 1},
        {"all": {"txt": [theirs]}},
        {"all": {"txt": [theirs]}},
    ]
    api.delete(record)
    api.delete(record)
    deletes = [c for c in api.api.call.call_args_list if c.args[0] == "delete_dns_record"]
    assert len(deletes) == 1
    assert deletes[0].args[1] == record.arguments()


def test_unknown_txt_value_does_not_trigger_create():
    api = client("example.com")
    record = Record("example.com", "_acme-challenge.example.com", "ours")
    with pytest.raises(APIError, match="no readable value"):
        api.contains(record, [{"fqdn": record.name, "type": "TXT"}])


def test_only_acme_names_can_be_prepared():
    api = client("example.com")
    with pytest.raises(errors.PluginError, match="_acme-challenge"):
        api.prepare("_dmarc.example.com", "token")
