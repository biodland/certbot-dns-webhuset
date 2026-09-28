from argparse import Namespace
from importlib.metadata import entry_points
from unittest.mock import Mock

import pytest
from certbot import errors

from certbot_dns_webhuset.dns_api import Record
from certbot_dns_webhuset.dns_webhuset import Authenticator


@pytest.fixture
def auth(tmp_path):
    creds = tmp_path / "webhuset.ini"
    creds.write_text("dns_webhuset_api_key = test-key\n")
    creds.chmod(0o600)
    config = Namespace(
        dns_webhuset_credentials=str(creds),
        dns_webhuset_propagation_seconds=0,
        dns_webhuset_http_timeout=30,
    )
    return Authenticator(config, "dns-webhuset")


def challenge(domain, token):
    achall = Mock()
    achall.domain = domain
    achall.identifier.value = domain
    achall.validation_domain_name.return_value = "_acme-challenge." + domain.removeprefix("*.")
    achall.validation.return_value = token
    return achall


def test_entry_point_loads_actual_certbot_plugin():
    entry = list(entry_points(group="certbot.plugins", name="dns-webhuset"))
    assert len(entry) == 1
    assert entry[0].load() is Authenticator


def test_credentials_use_standard_certbot_mapping(auth, monkeypatch):
    api = Mock()
    factory = Mock(return_value=api)
    monkeypatch.setattr("certbot_dns_webhuset.dns_webhuset.MCPClient", factory)
    auth._setup_credentials()
    assert factory.call_args.args == ("test-key", 30)
    api.check_tools.assert_called_once()
    auth.cleanup([])


def test_negative_wait_rejected(auth):
    auth.config.dns_webhuset_propagation_seconds = -1
    with pytest.raises(errors.PluginError):
        auth._setup_credentials()


def test_preserves_preexisting_value(auth):
    record = Record("example.com", "_acme-challenge.example.com", "existing")
    client = auth.client = Mock()
    client.prepare.return_value = (record, True)
    auth._perform("example.com", record.name, record.value)
    auth.cleanup([])
    client.create.assert_not_called()
    client.delete.assert_not_called()


def test_apex_wildcard_and_second_zone_created_before_single_wait(auth, monkeypatch):
    client = auth.client = Mock()
    achalls = [
        challenge("example.com", "apex"),
        challenge("example.com", "wildcard"),
        challenge("service.other.no", "second-zone"),
    ]
    client.prepare.side_effect = [
        (Record("example.com", "_acme-challenge.example.com", "apex"), False),
        (Record("example.com", "_acme-challenge.example.com", "wildcard"), False),
        (Record("other.no", "_acme-challenge.service.other.no", "second-zone"), False),
    ]
    monkeypatch.setattr(auth, "_setup_credentials", lambda: None)
    sleep = Mock()
    monkeypatch.setattr("certbot.plugins.dns_common.sleep", sleep)
    monkeypatch.setattr("certbot.plugins.dns_common.display_util.notify", Mock())
    assert len(auth.perform(achalls)) == 3
    assert client.create.call_count == 3
    sleep.assert_called_once_with(0)
    auth.cleanup(achalls)
    assert client.delete.call_count == 3
    assert not auth.pending


def test_partial_create_failure_cleans_all_attempted_records(auth, monkeypatch):
    client = auth.client = Mock()
    records = [
        Record("example.com", "_acme-challenge.example.com", "first"),
        Record("other.no", "_acme-challenge.other.no", "second"),
    ]
    client.prepare.side_effect = [(r, False) for r in records]
    client.create.side_effect = [None, errors.PluginError("API timeout")]
    monkeypatch.setattr(auth, "_setup_credentials", lambda: None)
    with pytest.raises(errors.PluginError):
        auth.perform([challenge("example.com", "first"), challenge("other.no", "second")])
    assert [c.args[0] for c in client.delete.call_args_list] == records
    client.close.assert_called_once()
    # Certbot may call cleanup again after perform raised.
    auth.cleanup([])
    assert client.delete.call_count == 2


def test_cleanup_continues_after_one_failure(auth, caplog):
    client = auth.client = Mock()
    records = [
        Record("example.com", "_acme-challenge.example.com", "first-secret"),
        Record("other.no", "_acme-challenge.other.no", "second-secret"),
    ]
    auth.pending = dict.fromkeys(records)
    client.delete.side_effect = [errors.PluginError("API unavailable"), None]
    auth.cleanup([])
    assert client.delete.call_count == 2
    assert "Could not clean up" in caplog.text
    assert "first-secret" not in caplog.text
    assert list(auth.pending) == records[:1]


def test_duplicate_challenge_created_once(auth):
    record = Record("example.com", "_acme-challenge.example.com", "same")
    client = auth.client = Mock()
    client.prepare.return_value = (record, False)
    auth._perform("example.com", record.name, record.value)
    auth._perform("example.com", record.name, record.value)
    client.create.assert_called_once_with(record)
    auth.cleanup([])
    client.delete.assert_called_once_with(record)
