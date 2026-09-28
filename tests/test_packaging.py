import json
from importlib.metadata import metadata, version
from pathlib import Path
from subprocess import run


def test_certbot_cli_discovers_plugin(tmp_path):
    result = run(
        [
            "certbot",
            "plugins",
            "--config-dir",
            str(tmp_path / "config"),
            "--work-dir",
            str(tmp_path / "work"),
            "--logs-dir",
            str(tmp_path / "logs"),
        ],
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, result.stderr
    assert "dns-webhuset" in result.stdout


def test_npm_fragment_matches_plugin():
    path = Path(__file__).resolve().parents[1] / "integrations/npm/provider.json"
    entry = json.loads(path.read_text())["webhuset"]
    assert entry["full_plugin_name"] == "dns-webhuset"
    assert entry["package_name"] == "certbot-dns-webhuset"
    assert "dns_webhuset_api_key" in entry["credentials"]
    assert entry["version"] == "==" + version("certbot-dns-webhuset")


def test_distribution_declares_mit_license():
    package = metadata("certbot-dns-webhuset")
    assert package["License-Expression"] == "MIT"
    assert "LICENSE" in package.get_all("License-File", [])
