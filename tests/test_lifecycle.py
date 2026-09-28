"""Exercise Certbot's lifecycle through the real DNS and MCP adapters."""

import json
from argparse import Namespace
from unittest.mock import Mock

import dns.name
import dns.resolver
import pytest
from certbot import errors

from certbot_dns_webhuset.dns_api import DNSClient
from certbot_dns_webhuset.dns_webhuset import Authenticator
from certbot_dns_webhuset.mcp import MCPClient

from .test_mcp import Response


class FakeWebhuset:
    def __init__(self, fail_after_create=False):
        self.zones = {
            "example.com": [{"fqdn": "_acme-challenge.example.com", "txt": "existing"}],
            "other.no": [],
        }
        self.operations = []
        self.fail_after_create = fail_after_create

    def post(self, url, json=None, **kwargs):
        message = json
        params = message["params"]
        args = params["arguments"]
        name = params["name"]
        self.operations.append(name)
        records = self.zones[args["domain"]]
        if name == "check_dns":
            data = {"status": 1, "all": {"txt": records}}
        elif name == "create_dns_record":
            records.append({"fqdn": args["fqdn"], "txt": args["value"]})
            if self.fail_after_create:
                import requests

                raise requests.Timeout("SECRET never returned to caller")
            data = {"status": 1}
        elif name == "delete_dns_record":
            records[:] = [
                r for r in records if (r["fqdn"], r["txt"]) != (args["fqdn"], args["value"])
            ]
            data = {"status": 1}
        else:
            raise AssertionError(name)
        # Serialize immediately: future fake mutations must not change earlier replies.
        return Response(
            {
                "jsonrpc": "2.0",
                "id": message["id"],
                "result": {"content": [{"type": "text", "text": json_module_dumps(data)}]},
            }
        )

    def close(self):
        pass


json_module_dumps = json.dumps


def make_auth(monkeypatch, fail=False):
    auth = Authenticator(Namespace(dns_webhuset_propagation_seconds=0), "dns-webhuset")
    service = FakeWebhuset(fail_after_create=fail)
    api = MCPClient("SECRET", session=service)
    api.initialized = True
    resolver = Mock()
    resolver.resolve.side_effect = dns.resolver.NXDOMAIN()
    auth.client = DNSClient(api, resolver=resolver)
    monkeypatch.setattr(
        dns.resolver,
        "zone_for_name",
        lambda name, **kwargs: dns.name.from_text(
            "other.no" if "other.no" in str(name) else "example.com"
        ),
    )
    monkeypatch.setattr(auth, "_setup_credentials", lambda: None)
    monkeypatch.setattr("certbot.plugins.dns_common.display_util.notify", Mock())
    monkeypatch.setattr("certbot.plugins.dns_common.sleep", lambda seconds: None)
    return auth, service


def achall(domain, value):
    result = Mock()
    result.domain = domain
    result.identifier.value = domain
    result.validation_domain_name.return_value = "_acme-challenge." + domain
    result.validation.return_value = value
    return result


def test_complete_multizone_lifecycle_preserves_existing_values(monkeypatch):
    auth, service = make_auth(monkeypatch)
    challenges = [
        achall("example.com", "apex"),
        achall("example.com", "wildcard"),
        achall("other.no", "other"),
    ]
    assert len(auth.perform(challenges)) == 3
    assert len(service.zones["example.com"]) == 3
    assert len(service.zones["other.no"]) == 1
    auth.cleanup(challenges)
    assert service.zones == {
        "example.com": [{"fqdn": "_acme-challenge.example.com", "txt": "existing"}],
        "other.no": [],
    }


def test_lost_create_response_is_cleaned_without_repeating_write(monkeypatch):
    auth, service = make_auth(monkeypatch, fail=True)
    with pytest.raises(errors.PluginError, match="no automatic retry"):
        auth.perform([achall("example.com", "new")])
    assert service.operations.count("create_dns_record") == 1
    assert service.operations.count("delete_dns_record") == 1
    assert service.zones["example.com"] == [
        {"fqdn": "_acme-challenge.example.com", "txt": "existing"}
    ]
