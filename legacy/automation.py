#!/usr/bin/env python3
"""Certbot DNS hooks for Webhuset MCP and deployment to an existing NPM ID.

Python 3.9+, standard library only. External commands: dig and openssl.
Never logs HTTP bodies, API keys, passwords, tokens or private keys.
"""
import contextlib
import hashlib
import json
import os
from pathlib import Path
import re
import shlex
import subprocess
import sys
import time
import urllib.error
import urllib.request
import uuid

MCP_URL = "https://mcp.webhuset.no/mcp/v1"


def log(message):
    print(message, file=sys.stderr, flush=True)


def config():
    path = Path(os.environ.get("COMMUNITYNORD_CONFIG", Path(__file__).with_name("automation.json")))
    if os.name == "posix" and path.stat().st_mode & 0o077:
        raise RuntimeError("automation.json maa ha modus 0600 (chmod 600).")
    return json.loads(path.read_text(encoding="utf-8"))


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def request(url, data=None, headers=None, method="POST"):
    req = urllib.request.Request(url, data=data, headers=headers or {}, method=method)
    try:
        return urllib.request.build_opener(NoRedirect()).open(req, timeout=60)
    except urllib.error.HTTPError as exc:
        # Response bodies can contain credentials or certificate material.
        raise RuntimeError(f"HTTP {exc.code}; kontroller URL, API-tilgang og legitimasjon.") from None
    except urllib.error.URLError:
        raise RuntimeError("Kunne ikke koble til API-et; kontroller nettverk/TLS.") from None


def rpc_response(response, request_id):
    if "text/event-stream" in response.headers.get("Content-Type", ""):
        parts = []
        for raw in response:
            line = raw.decode("utf-8").rstrip("\r\n")
            if line.startswith("data:"):
                parts.append(line[5:].lstrip(" "))
            elif not line and parts:
                item = json.loads("\n".join(parts))
                parts = []
                if item.get("id") == request_id:
                    return item
        raise RuntimeError("MCP-stroem sluttet uten forventet svar.")
    item = json.load(response)
    if item.get("id") != request_id:
        raise RuntimeError("MCP svarte med feil forespoersels-ID.")
    return item


class Webhuset:
    def __init__(self, key):
        if not key or key.startswith("SETT_INN"):
            raise RuntimeError("Sett webhuset_api_key i automation.json.")
        self.headers = {
            "Authorization": "Bearer " + key,
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
        }
        self.sequence = 0
        result = self.rpc("initialize", {
            "protocolVersion": "2025-03-26", "capabilities": {},
            "clientInfo": {"name": "communitynord-certbot", "version": "1.0"},
        })
        version = result.get("protocolVersion")
        if version not in ("2025-03-26", "2025-06-18", "2025-11-25"):
            raise RuntimeError("Ustoettet MCP-protokollversjon.")
        self.headers["MCP-Protocol-Version"] = version
        self.rpc("notifications/initialized", notification=True)

    def rpc(self, method, params=None, notification=False):
        payload = {"jsonrpc": "2.0", "method": method}
        if params is not None:
            payload["params"] = params
        if not notification:
            self.sequence += 1
            payload["id"] = self.sequence
        with request(MCP_URL, json.dumps(payload).encode(), self.headers) as response:
            session = response.headers.get("Mcp-Session-Id")
            if session:
                self.headers["Mcp-Session-Id"] = session
            if notification:
                return None
            message = rpc_response(response, self.sequence)
        if "error" in message:
            raise RuntimeError(f"MCP avviste {method}; kontroller API-rettighetene.")
        return message["result"]

    def tool(self, name, arguments):
        result = self.rpc("tools/call", {"name": name, "arguments": arguments})
        if result.get("isError"):
            raise RuntimeError(f"Webhuset-kommandoen {name} feilet.")
        # Some APIs encode application errors in JSON text instead of isError.
        objects = [result.get("structuredContent")]
        for block in result.get("content", []):
            if block.get("type") == "text":
                try:
                    objects.append(json.loads(block["text"]))
                except (ValueError, KeyError):
                    pass
        for obj in objects:
            if isinstance(obj, dict) and (
                obj.get("error") or obj.get("success") is False or obj.get("status") == 0
            ):
                raise RuntimeError(f"Webhuset rapporterte feil for {name}.")
        return result

    def close(self):
        if "Mcp-Session-Id" in self.headers:
            with contextlib.suppress(Exception):
                with request(MCP_URL, headers=self.headers, method="DELETE"):
                    pass


def challenge(cfg, environ):
    domain = environ["CERTBOT_DOMAIN"].removeprefix("*.").lower().rstrip(".")
    allowed = {d.removeprefix("*.").lower().rstrip(".") for d in cfg["domains"]}
    zone = cfg["zone"].lower().rstrip(".")
    if domain not in allowed or not (domain == zone or domain.endswith("." + zone)):
        raise RuntimeError("Certbot-domenet ligger utenfor konfigurert omfang.")
    value = environ["CERTBOT_VALIDATION"]
    if not re.fullmatch(r"[A-Za-z0-9_-]{20,200}", value):
        raise RuntimeError("Ugyldig DNS-01-verdi.")
    return {"domain": zone, "fqdn": "_acme-challenge." + domain,
            "type": "TXT", "value": value}


def dig(name, record_type, server=None):
    command = ["dig", "+short", "+time=3", "+tries=1"]
    if server:
        command.append("@" + server)
    command += [name, record_type]
    result = subprocess.run(command, capture_output=True, text=True, timeout=10)
    if result.returncode:
        return []
    return result.stdout.splitlines()


def txt_values(lines):
    values = set()
    for line in lines:
        if line.startswith('"'):
            values.add("".join(shlex.split(line)))
    return values


def wait_dns(cfg, record):
    nameservers = [s.rstrip(".") for s in dig(cfg["zone"], "NS") if s.strip()]
    if not nameservers:
        raise RuntimeError("Fant ingen autoritative navnetjenere.")
    servers = nameservers + cfg.get("dns_resolvers", ["1.1.1.1", "8.8.8.8"])
    deadline = time.monotonic() + int(cfg.get("dns_timeout_seconds", 1200))
    log("Venter paa DNS-propagasjon for " + record["fqdn"])
    while time.monotonic() < deadline:
        if all(record["value"] in txt_values(dig(record["fqdn"], "TXT", server))
               for server in servers):
            return
        time.sleep(max(1, int(cfg.get("dns_poll_seconds", 20))))
    raise RuntimeError("DNS-propagasjon tok for lang tid; fornyelse avbrutt.")


def dns_hook(cfg, action):
    record = challenge(cfg, os.environ)
    api = Webhuset(cfg["webhuset_api_key"])
    try:
        if action == "auth":
            # Keep all other values, including another challenge at the same name.
            # No automatic mutation retries: a lost response may mean it succeeded.
            try:
                api.tool("create_dns_record", dict(record, ttl=600))
                wait_dns(cfg, record)
            except Exception:
                try:
                    api.tool("delete_dns_record", record)
                except Exception:
                    log("Opprydding feilet; kontroller TXT-posten " + record["fqdn"])
                raise
            log("DNS-valideringspost klar.")
        else:
            api.tool("delete_dns_record", record)
            log("Fjernet den aktuelle DNS-valideringsverdien.")
    finally:
        api.close()


def openssl(*args, data=None):
    result = subprocess.run(["openssl", *args], input=data, capture_output=True, timeout=30)
    if result.returncode:
        raise RuntimeError("OpenSSL-validering feilet; kontroller sertifikat og privatnoekkel.")
    return result.stdout


def certificate_files(cfg):
    directory = Path(cfg["certificate_dir"])
    files = {"certificate": ("cert.pem", (directory / "cert.pem").read_bytes()),
             "certificate_key": ("privkey.pem", (directory / "privkey.pem").read_bytes()),
             "intermediate_certificate": ("chain.pem", (directory / "chain.pem").read_bytes())}
    cert = files["certificate"][1]
    key = files["certificate_key"][1]
    openssl("x509", "-noout", "-checkend", "0", data=cert)
    if openssl("x509", "-pubkey", "-noout", data=cert) != openssl("pkey", "-pubout", data=key):
        raise RuntimeError("Sertifikatet og privatnoekkelen passer ikke sammen.")
    sans = openssl("x509", "-noout", "-ext", "subjectAltName", data=cert).decode()
    actual = set(re.findall(r"DNS:([^,\s]+)", sans))
    if not set(cfg["domains"]).issubset(actual):
        raise RuntimeError("Sertifikatet mangler ett eller flere konfigurerte domener.")
    issuer = openssl("x509", "-noout", "-issuer", data=cert).decode().lower()
    if "staging" in issuer or "fake" in issuer:
        raise RuntimeError("Nekter aa laste opp et staging-sertifikat.")
    return files


def multipart(files):
    boundary = "----communitynord" + uuid.uuid4().hex
    chunks = []
    for field, (filename, content) in files.items():
        chunks.append((f'--{boundary}\r\nContent-Disposition: form-data; name="{field}"; '
                       f'filename="{filename}"\r\nContent-Type: application/octet-stream\r\n\r\n').encode())
        chunks.extend([content, b"\r\n"])
    chunks.append(f"--{boundary}--\r\n".encode())
    return b"".join(chunks), "multipart/form-data; boundary=" + boundary


def json_request(url, payload=None, headers=None, method="POST"):
    all_headers = {"Content-Type": "application/json", **(headers or {})}
    data = None if payload is None else json.dumps(payload).encode()
    with request(url, data, all_headers, method) as response:
        result = json.load(response)
    if isinstance(result, dict) and result.get("error"):
        raise RuntimeError("NPM rapporterte en API-feil.")
    return result


def reload_commands(cfg):
    commands = [cfg.get("npm_test_command"), cfg.get("npm_reload_command")]
    for command in commands:
        if not isinstance(command, list) or not command or any(
            not isinstance(arg, str) or not arg or "SETT_INN" in arg for arg in command
        ):
            raise RuntimeError("Konfigurer npm_test_command og npm_reload_command foerst.")
    return commands


def reload_npm(cfg):
    for command in reload_commands(cfg):
        result = subprocess.run(command, capture_output=True, timeout=60)
        if result.returncode:
            raise RuntimeError("NPM nginx-test/reload feilet. Kontroller container og nginx-konfigurasjon.")


def deploy_locked(cfg, state):
    files = certificate_files(cfg)
    cert_id = int(cfg["npm_certificate_id"])
    if cert_id <= 0:
        raise RuntimeError("NPM-sertifikat-ID maa vaere positiv.")
    base = cfg["npm_url"].rstrip("/")
    digest = hashlib.sha256()
    digest.update((base + "/" + str(cert_id)).encode())
    for _, content in files.values():
        digest.update(content)
    fingerprint = digest.hexdigest()
    marker = state / "last-upload.sha256"
    if marker.exists() and marker.read_text().strip() == fingerprint:
        return
    reload_commands(cfg)
    if not cfg["npm_password"] or cfg["npm_password"].startswith("SETT_INN"):
        raise RuntimeError("Sett npm_password i automation.json.")
    token = json_request(base + "/api/tokens", {
        "identity": cfg["npm_identity"], "secret": cfg["npm_password"]}).get("token")
    if not isinstance(token, str) or not token:
        raise RuntimeError("NPM returnerte ingen innloggingstoken.")
    headers = {"Authorization": "Bearer " + token}
    endpoint = base + "/api/nginx/certificates/" + str(cert_id)
    current = json_request(endpoint, headers=headers, method="GET")
    if current.get("provider") != "other" or current.get("nice_name") != cfg["npm_certificate_name"]:
        raise RuntimeError("NPM-ID peker ikke paa forventet egendefinert sertifikat.")
    body, content_type = multipart(files)
    with request(endpoint + "/upload", body, {**headers, "Content-Type": content_type}) as response:
        result = json.load(response)
    if result.get("error") or not result.get("certificate") or not result.get("certificate_key"):
        raise RuntimeError("NPM bekreftet ikke sertifikatopplastingen.")
    # Uploading a custom certificate does not guarantee nginx loads it.
    reload_npm(cfg)
    # Save only after successful upload AND reload. Failure is retried next run.
    temporary = marker.with_suffix(".tmp")
    temporary.write_text(fingerprint + "\n")
    temporary.replace(marker)
    log(f"Sertifikat lastet opp til NPM-ID {cert_id}; nginx reload utfoert.")


def deploy(cfg):
    import fcntl  # Deployment target is Linux; independent of DNS hook execution.
    state = Path(cfg["state_dir"])
    state.mkdir(mode=0o700, parents=True, exist_ok=True)
    with (state / "deploy.lock").open("w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        deploy_locked(cfg, state)


def preflight(cfg):
    api = Webhuset(cfg["webhuset_api_key"])
    try:
        names = set()
        params = {}
        while True:
            result = api.rpc("tools/list", params)
            names.update(t["name"] for t in result.get("tools", []))
            if not result.get("nextCursor"):
                break
            params = {"cursor": result["nextCursor"]}
        required = {"check_dns", "create_dns_record", "delete_dns_record"}
        if not required.issubset(names):
            raise RuntimeError("API-noekkelen mangler DNS-verktøy. Velg DNS: Administrere.")
        api.tool("check_dns", {"domain": cfg["zone"]})
        log("Webhuset: DNS-lesing fungerer, og skriveverktoeyene er tilgjengelige.")
    finally:
        api.close()


def main():
    os.umask(0o077)
    if len(sys.argv) != 2 or sys.argv[1] not in ("auth", "cleanup", "deploy", "preflight"):
        raise RuntimeError("Bruk: automation.py auth|cleanup|deploy|preflight")
    cfg = config()
    action = sys.argv[1]
    if action in ("auth", "cleanup"):
        dns_hook(cfg, action)
    elif action == "deploy":
        deploy(cfg)
    else:
        preflight(cfg)


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        # Only our own deliberately sanitized errors are printed in full.
        log(str(exc) if isinstance(exc, RuntimeError) else
            f"Feil av typen {type(exc).__name__}; kontroller oppsett, filer og API-kompatibilitet.")
        sys.exit(1)
