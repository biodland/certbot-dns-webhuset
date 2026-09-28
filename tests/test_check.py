from unittest.mock import Mock

from certbot_dns_webhuset import check
from certbot_dns_webhuset.mcp import APIError


def test_read_only_check_multiple_domains(tmp_path, monkeypatch, capsys):
    credentials = tmp_path / "credentials.ini"
    credentials.write_text("dns_webhuset_api_key = SECRET\n")
    credentials.chmod(0o600)
    monkeypatch.setattr(
        "sys.argv",
        [
            "check",
            "--credentials",
            str(credentials),
            "--domain",
            "*.example.com",
            "--domain",
            "other.no",
        ],
    )
    client = Mock()
    client.discover_zone.side_effect = ["example.com", "other.no"]
    client.records.return_value = [{"type": "TXT", "txt": "secret-data"}]
    monkeypatch.setattr(check, "DNSClient", Mock(return_value=client))
    api = Mock()
    monkeypatch.setattr(check, "MCPClient", Mock(return_value=api))
    assert check.main() == 0
    output = capsys.readouterr().out
    assert "example.com" in output and "other.no" in output
    assert "SECRET" not in output and "secret-data" not in output
    client.create.assert_not_called()
    client.delete.assert_not_called()
    api.check_tools.assert_called_once()
    client.close.assert_called_once()


def test_read_only_check_reports_sanitized_api_error(tmp_path, monkeypatch, capsys):
    credentials = tmp_path / "credentials.ini"
    credentials.write_text("dns_webhuset_api_key = SECRET\n")
    credentials.chmod(0o600)
    monkeypatch.setattr(
        "sys.argv", ["check", "--credentials", str(credentials), "--domain", "example.com"]
    )
    api = Mock()
    api.check_tools.side_effect = APIError("DNS permission required")
    monkeypatch.setattr(check, "MCPClient", Mock(return_value=api))
    assert check.main() == 1
    assert "DNS permission required" in capsys.readouterr().err
    api.close.assert_called_once()
