import json
from importlib.metadata import version
from unittest.mock import Mock

import pytest
import requests

from certbot_dns_webhuset.mcp import APIError, MCPClient, decode_tool_result


class Response:
    def __init__(self, payload=None, status=200, headers=None, stream=None):
        self.status_code = status
        self.headers = headers or {"Content-Type": "application/json"}
        self.data = json.dumps(payload).encode() if stream is None else stream

    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass

    def iter_content(self, **kwargs):
        yield self.data

    def iter_lines(self, **kwargs):
        yield from self.data.splitlines()

    def close(self):
        pass


def rpc(result, number=1):
    return Response({"jsonrpc": "2.0", "id": number, "result": result})


def initialized_client():
    session = Mock()
    client = MCPClient("SECRET", session=session)
    client.initialized = True
    return client, session


def test_handshake_keeps_session_and_notification_has_no_id():
    session = Mock()
    headers = {"Content-Type": "application/json", "Mcp-Session-Id": "SESSION"}
    session.post.side_effect = [
        Response(
            {"jsonrpc": "2.0", "id": 1, "result": {"protocolVersion": "2025-03-26"}},
            headers=headers,
        ),
        Response(status=202),
    ]
    client = MCPClient("SECRET", session=session)
    client.initialize()
    handshake = session.post.call_args_list[0].kwargs["json"]["params"]["clientInfo"]
    assert handshake["version"] == version("certbot-dns-webhuset")
    call = session.post.call_args.kwargs
    assert call["json"]["method"] == "notifications/initialized"
    assert "id" not in call["json"]
    assert call["headers"]["Mcp-Session-Id"] == "SESSION"
    assert call["allow_redirects"] is False
    assert call["headers"]["Authorization"] == "Bearer SECRET"
    client.initialize()
    assert session.post.call_count == 2


def test_sse_with_keepalive_notifications_and_unrelated_ids():
    client, session = initialized_client()
    session.post.return_value = Response(
        headers={"Content-Type": "text/event-stream"},
        stream=(
            b': keepalive\n\ndata: {"jsonrpc":"2.0","method":"ping"}\n\n'
            b'data: {"jsonrpc":"2.0","id":99,"result":{}}\n\n'
            b'data: {"jsonrpc":"2.0","id":1,\n'
            b'data: "result":{"structuredContent":{"status":1}}}\n\n'
        ),
    )
    assert client.call("create_dns_record", {}) == {"status": 1}


@pytest.mark.parametrize("status", [301, 401, 403, 404, 429, 500])
def test_http_errors_do_not_leak_body_or_retry(status):
    client, session = initialized_client()
    session.post.return_value = Response({"secret": "SECRET"}, status=status)
    with pytest.raises(APIError) as error:
        client.call("create_dns_record", {})
    assert str(status) in str(error.value)
    assert "SECRET" not in str(error.value)
    assert session.post.call_count == 1


def test_network_error_is_sanitized_and_not_retried():
    client, session = initialized_client()
    session.post.side_effect = requests.Timeout("SECRET")
    with pytest.raises(APIError, match="no automatic retry") as error:
        client.call("create_dns_record", {})
    assert "SECRET" not in str(error.value)
    assert session.post.call_count == 1


@pytest.mark.parametrize(
    "result",
    [
        {"isError": True, "content": [{"type": "text", "text": "SECRET"}]},
        {"structuredContent": {"status": 0, "secret": "SECRET"}},
        {"structuredContent": {"data": {"success": False, "secret": "SECRET"}}},
        {"content": [{"type": "text", "text": "unknown SECRET"}]},
    ],
)
def test_tool_errors_are_not_mistaken_for_success(result):
    client, session = initialized_client()
    session.post.return_value = rpc(result)
    with pytest.raises(APIError) as error:
        client.call("check_dns", {})
    assert "SECRET" not in str(error.value)


def test_text_json_response():
    assert decode_tool_result(
        {"content": [{"type": "text", "text": '{"status":1}'}]}, "create_dns_record"
    ) == {"status": 1}


@pytest.mark.parametrize(
    "payload",
    [
        {"jsonrpc": "2.0", "id": 1, "error": {"message": "SECRET"}},
        {"jsonrpc": "2.0", "id": 99, "result": {}},
        {"jsonrpc": "2.0", "id": 1, "result": None},
    ],
)
def test_malformed_rpc_rejected(payload):
    client, session = initialized_client()
    session.post.return_value = Response(payload)
    with pytest.raises(APIError) as error:
        client.call("check_dns", {})
    assert "SECRET" not in str(error.value)


def test_tools_pagination_and_permissions():
    client, session = initialized_client()
    session.post.side_effect = [
        rpc({"tools": [{"name": "check_dns"}], "nextCursor": "next"}),
        rpc({"tools": [{"name": "create_dns_record"}, {"name": "delete_dns_record"}]}, 2),
    ]
    client.check_tools()
    assert session.post.call_args.kwargs["json"]["params"] == {"cursor": "next"}


def test_missing_tools_rejected():
    client, session = initialized_client()
    session.post.return_value = rpc({"tools": [{"name": "check_dns"}]})
    with pytest.raises(APIError, match="DNS administration"):
        client.check_tools()


def test_session_close_ignores_network_failure():
    client, session = initialized_client()
    client.headers["Mcp-Session-Id"] = "SESSION"
    session.delete.side_effect = requests.Timeout()
    client.close()
    session.close.assert_called_once()


def test_response_size_is_bounded(monkeypatch):
    monkeypatch.setattr("certbot_dns_webhuset.mcp.MAX_RESPONSE_BYTES", 2)
    client, session = initialized_client()
    session.post.return_value = rpc({})
    with pytest.raises(APIError, match="size or time"):
        client.call("check_dns", {})
