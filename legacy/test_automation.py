import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch, Mock

import automation as a


class Response(io.BytesIO):
    def __init__(self, data, headers=None):
        super().__init__(data)
        self.headers = headers or {"Content-Type": "application/json"}


class AutomationTests(unittest.TestCase):
    def setUp(self):
        self.cfg = {"zone": "communitynord.com", "domains": ["communitynord.com",
                    "*.communitynord.com", "*.admin.communitynord.com"],
                    "webhuset_api_key": "test-key", "npm_test_command": ["test-nginx"],
                    "npm_reload_command": ["reload-nginx"]}
        self.env = {"CERTBOT_DOMAIN": "*.admin.communitynord.com", "CERTBOT_VALIDATION": "A" * 43}

    def test_challenge_scope_and_admin(self):
        record = a.challenge(self.cfg, self.env)
        self.assertEqual(record["fqdn"], "_acme-challenge.admin.communitynord.com")
        with self.assertRaises(RuntimeError):
            a.challenge(self.cfg, dict(self.env, CERTBOT_DOMAIN="evilcommunitynord.com"))

    def test_apex_and_wildcard_share_name_but_not_value(self):
        first = a.challenge(self.cfg, dict(self.env, CERTBOT_DOMAIN="communitynord.com"))
        second = a.challenge(self.cfg, dict(self.env, CERTBOT_DOMAIN="*.communitynord.com",
                                          CERTBOT_VALIDATION="B" * 43))
        self.assertEqual(first["fqdn"], second["fqdn"])
        self.assertNotEqual(first["value"], second["value"])

    def test_cleanup_only_exact_value(self):
        api = Mock()
        with patch.dict(a.os.environ, self.env), patch.object(a, "Webhuset", return_value=api):
            a.dns_hook(self.cfg, "cleanup")
        api.tool.assert_called_once_with("delete_dns_record", a.challenge(self.cfg, self.env))

    def test_propagation_failure_cleans_up_and_fails(self):
        api = Mock()
        with patch.dict(a.os.environ, self.env), patch.object(a, "Webhuset", return_value=api), \
                patch.object(a, "wait_dns", side_effect=RuntimeError("timeout")):
            with self.assertRaises(RuntimeError):
                a.dns_hook(self.cfg, "auth")
        self.assertEqual([c.args[0] for c in api.tool.call_args_list],
                         ["create_dns_record", "delete_dns_record"])
        self.assertEqual(api.tool.call_args_list[1].args[1]["value"], "A" * 43)

    def test_txt_multiple_values_and_chunks(self):
        self.assertEqual(a.txt_values(['"AAA" "BBB"', '"CCC"', 'alias.example.']),
                         {"AAABBB", "CCC"})

    def test_mcp_sse_ignores_unrelated_events(self):
        response = Response(b': ping\n\ndata: {"method":"notification"}\n\n'
                            b'data: {"id":3,"result":{"ok":true}}\n\n',
                            {"Content-Type": "text/event-stream"})
        self.assertEqual(a.rpc_response(response, 3)["result"], {"ok": True})

    def test_mcp_handshake_session_and_tool_errors(self):
        replies = [Response(b'{"id":1,"result":{"protocolVersion":"2025-03-26"}}',
                            {"Mcp-Session-Id": "session", "Content-Type": "application/json"}),
                   Response(b""), Response(b'{"id":2,"result":{"isError":true}}')]
        calls = []
        def fake(url, data=None, headers=None, method="POST"):
            calls.append((json.loads(data), dict(headers)))
            return replies.pop(0)
        with patch.object(a, "request", side_effect=fake):
            api = a.Webhuset("key")
            with self.assertRaises(RuntimeError):
                api.tool("create_dns_record", {})
        self.assertEqual(calls[1][0]["method"], "notifications/initialized")
        self.assertEqual(calls[2][1]["Mcp-Session-Id"], "session")

    def test_multipart_contains_three_separate_files(self):
        files = {"certificate": ("cert.pem", b"CERT"), "certificate_key": ("privkey.pem", b"KEY"),
                 "intermediate_certificate": ("chain.pem", b"CHAIN")}
        body, content_type = a.multipart(files)
        for field in files:
            self.assertIn(f'name="{field}"'.encode(), body)
        boundary = content_type.split("boundary=")[1]
        self.assertTrue(body.endswith(("--" + boundary + "--\r\n").encode()))

    def test_failed_upload_retried_then_unchanged_skipped(self):
        cfg = dict(self.cfg, npm_certificate_id=62, npm_url="http://npm", npm_identity="user",
                   npm_password="password", npm_certificate_name="communitynord.com")
        files = {"certificate": ("cert.pem", b"cert"), "certificate_key": ("privkey.pem", b"key")}
        def fake_json(url, *args, **kwargs):
            return {"token": "token"} if url.endswith("tokens") else {
                "provider": "other", "nice_name": "communitynord.com"}
        with tempfile.TemporaryDirectory() as directory, \
                patch.object(a, "certificate_files", return_value=files), \
                patch.object(a, "json_request", side_effect=fake_json), \
                patch.object(a, "reload_npm") as reload, \
                patch.object(a, "request") as upload:
            state = Path(directory)
            upload.side_effect = RuntimeError("HTTP 503")
            with self.assertRaises(RuntimeError):
                a.deploy_locked(cfg, state)
            self.assertFalse((state / "last-upload.sha256").exists())
            upload.side_effect = None
            upload.return_value = Response(b'{"certificate":"cert","certificate_key":"key"}')
            a.deploy_locked(cfg, state)
            self.assertTrue((state / "last-upload.sha256").exists())
            reload.assert_called_once()
            upload.reset_mock()
            a.deploy_locked(cfg, state)
            upload.assert_not_called()

    def test_reload_failure_prevents_success_marker(self):
        cfg = dict(self.cfg, npm_certificate_id=62, npm_url="http://npm", npm_identity="user",
                   npm_password="password", npm_certificate_name="communitynord.com")
        with tempfile.TemporaryDirectory() as directory, \
                patch.object(a, "certificate_files", return_value={"certificate": ("cert.pem", b"cert")}), \
                patch.object(a, "json_request", side_effect=[{"token": "token"},
                             {"provider": "other", "nice_name": "communitynord.com"}]), \
                patch.object(a, "request", return_value=Response(b'{"certificate":"cert","certificate_key":"key"}')), \
                patch.object(a, "reload_npm", side_effect=RuntimeError("reload failed")):
            with self.assertRaises(RuntimeError):
                a.deploy_locked(cfg, Path(directory))
            self.assertFalse((Path(directory) / "last-upload.sha256").exists())

    def test_wrong_npm_id_target_rejected(self):
        cfg = dict(self.cfg, npm_certificate_id=62, npm_url="http://npm", npm_identity="user",
                   npm_password="password", npm_certificate_name="communitynord.com")
        with tempfile.TemporaryDirectory() as directory, \
                patch.object(a, "certificate_files", return_value={"certificate": ("cert.pem", b"cert")}), \
                patch.object(a, "json_request", side_effect=[{"token": "token"},
                             {"provider": "letsencrypt", "nice_name": "other"}]), \
                patch.object(a, "request") as upload:
            with self.assertRaises(RuntimeError):
                a.deploy_locked(cfg, Path(directory))
            upload.assert_not_called()


if __name__ == "__main__":
    unittest.main()
