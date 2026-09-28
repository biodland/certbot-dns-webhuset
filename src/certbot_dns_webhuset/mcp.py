"""Small synchronous Streamable HTTP MCP client; no LLM or browser involved."""

import json
import time
from contextlib import suppress
from importlib.metadata import version

import requests
from certbot import errors

ENDPOINT = "https://mcp.webhuset.no/mcp/v1"
PROTOCOL = "2025-03-26"
MAX_RESPONSE_BYTES = 4 * 1024 * 1024


class APIError(errors.PluginError):
    """A sanitized error: API bodies and credentials are never included."""


class MCPClient:
    def __init__(self, api_key, timeout=30, session=None):
        self.timeout = timeout
        self.session = session or requests.Session()
        self.headers = {
            "Authorization": "Bearer " + api_key,
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
        }
        self.sequence = 0
        self.initialized = False

    def initialize(self):
        if self.initialized:
            return
        result = self.rpc(
            "initialize",
            {
                "protocolVersion": PROTOCOL,
                "capabilities": {},
                "clientInfo": {
                    "name": "certbot-dns-webhuset",
                    "version": version("certbot-dns-webhuset"),
                },
            },
        )
        if result.get("protocolVersion") != PROTOCOL:
            raise APIError("Webhuset negotiated an unsupported MCP protocol version.")
        self.headers["MCP-Protocol-Version"] = PROTOCOL
        self.rpc("notifications/initialized", notification=True)
        self.initialized = True

    def rpc(self, method, params=None, notification=False):
        message = {"jsonrpc": "2.0", "method": method}
        if params is not None:
            message["params"] = params
        if not notification:
            self.sequence += 1
            message["id"] = self.sequence
        try:
            with self.session.post(
                ENDPOINT,
                json=message,
                headers=self.headers,
                timeout=(self.timeout, self.timeout),
                stream=True,
                allow_redirects=False,
            ) as response:
                if not 200 <= response.status_code < 300:
                    hint = (
                        " Check the API key and DNS administration permission."
                        if response.status_code in (401, 403)
                        else ""
                    )
                    raise APIError(f"Webhuset HTTP {response.status_code} during {method}.{hint}")
                if method == "initialize" and response.headers.get("Mcp-Session-Id"):
                    self.headers["Mcp-Session-Id"] = response.headers["Mcp-Session-Id"]
                if notification:
                    return {}
                reply = self._read_response(response, self.sequence)
        except (requests.RequestException, OSError, ValueError):
            raise APIError(
                f"Webhuset transport/JSON error during {method}; no automatic retry."
            ) from None
        if not isinstance(reply, dict) or reply.get("jsonrpc") != "2.0":
            raise APIError("Invalid Webhuset JSON-RPC response.")
        if "error" in reply:
            raise APIError(
                f"Webhuset rejected MCP method {method}; check permissions and API compatibility."
            )
        if not isinstance(reply.get("result"), dict):
            raise APIError("Webhuset returned no MCP result object.")
        return reply["result"]

    def _read_response(self, response, expected_id):
        deadline = time.monotonic() + self.timeout
        total = 0
        event = []
        if "text/event-stream" in response.headers.get("Content-Type", "").lower():
            for raw_line in response.iter_lines(chunk_size=1):
                total += len(raw_line)
                self._check_limit(total, deadline)
                line = raw_line.decode("utf-8")
                if line.startswith("data:"):
                    event.append(line[5:].removeprefix(" "))
                elif not line and event:
                    reply = json.loads("\n".join(event))
                    event = []
                    if isinstance(reply, dict) and reply.get("id") == expected_id:
                        return reply
            raise APIError("Webhuset MCP stream ended without the expected response.")
        chunks = []
        for chunk in response.iter_content(chunk_size=8192):
            total += len(chunk)
            self._check_limit(total, deadline)
            chunks.append(chunk)
        reply = json.loads(b"".join(chunks))
        if not isinstance(reply, dict) or reply.get("id") != expected_id:
            raise APIError("Webhuset returned an unexpected JSON-RPC ID.")
        return reply

    @staticmethod
    def _check_limit(total, deadline):
        if total > MAX_RESPONSE_BYTES or time.monotonic() > deadline:
            raise APIError("Webhuset MCP response exceeded its size or time limit.")

    def call(self, name, arguments):
        self.initialize()
        result = self.rpc("tools/call", {"name": name, "arguments": arguments})
        if result.get("isError"):
            raise APIError(
                f"Webhuset tool {name} failed; check DNS permissions and zone ownership."
            )
        return decode_tool_result(result, name)

    def check_tools(self):
        self.initialize()
        required = {"check_dns", "create_dns_record", "delete_dns_record"}
        names, cursors = set(), set()
        params = {}
        for _ in range(100):
            page = self.rpc("tools/list", params)
            names.update(t.get("name") for t in page.get("tools", []) if isinstance(t, dict))
            cursor = page.get("nextCursor")
            if not cursor:
                break
            if cursor in cursors:
                raise APIError("Webhuset repeated a tool-list cursor.")
            cursors.add(cursor)
            params = {"cursor": cursor}
        else:
            raise APIError("Webhuset tool list exceeded the page limit.")
        if not required.issubset(names):
            raise APIError(
                "The Webhuset key needs DNS administration permission (DNS: Administrere)."
            )

    def close(self):
        if self.headers.get("Mcp-Session-Id"):
            with suppress(requests.RequestException):
                response = self.session.delete(
                    ENDPOINT,
                    headers=self.headers,
                    timeout=self.timeout,
                    allow_redirects=False,
                )
                response.close()
        self.session.close()


def decode_tool_result(result, name):
    """Accept structured content or one JSON text block; reject unknown shapes."""
    payload = result.get("structuredContent")
    if payload is None:
        texts = [
            block.get("text", "")
            for block in result.get("content", [])
            if isinstance(block, dict) and block.get("type") == "text"
        ]
        if len(texts) != 1:
            raise APIError(f"Unexpected response format for Webhuset tool {name}.")
        try:
            payload = json.loads(texts[0])
        except ValueError:
            raise APIError(
                f"Expected JSON data from Webhuset tool {name}; live API verification needed."
            ) from None
    if not isinstance(payload, (dict, list)):
        raise APIError(f"Unexpected data type for Webhuset tool {name}.")
    # The Webhuset web API uses status=1 for success. MCP may wrap that object.
    check = payload
    for _ in range(4):
        if not isinstance(check, dict):
            break
        if (
            check.get("error")
            or check.get("success") is False
            or ("status" in check and check["status"] in (0, "error", "failed"))
        ):
            raise APIError(f"Webhuset reported an application error for {name}.")
        if "data" in check:
            check = check["data"]
        elif "result" in check:
            check = check["result"]
        else:
            break
    return payload
