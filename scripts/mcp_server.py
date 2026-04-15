from __future__ import annotations

import json
import sys
import traceback

from services.mcp_tools import McpToolError, execute_mcp_tool, list_mcp_tools

SERVER_INFO = {
    "name": "gold-drop-mcp",
    "version": "1.0.0",
}


def _read_message():
    headers = {}
    while True:
        line = sys.stdin.buffer.readline()
        if not line:
            return None
        if line in (b"\r\n", b"\n"):
            break
        name, value = line.decode("utf-8").split(":", 1)
        headers[name.strip().lower()] = value.strip()
    length = int(headers.get("content-length", "0"))
    if length <= 0:
        return None
    body = sys.stdin.buffer.read(length)
    if not body:
        return None
    return json.loads(body.decode("utf-8"))


def _write_message(payload: dict):
    body = json.dumps(payload, ensure_ascii=True).encode("utf-8")
    sys.stdout.buffer.write(f"Content-Length: {len(body)}\r\n\r\n".encode("ascii"))
    sys.stdout.buffer.write(body)
    sys.stdout.buffer.flush()


def _success(msg_id, result):
    return {"jsonrpc": "2.0", "id": msg_id, "result": result}


def _error(msg_id, code: int, message: str):
    return {"jsonrpc": "2.0", "id": msg_id, "error": {"code": code, "message": message}}


def handle_request(message: dict) -> dict | None:
    method = message.get("method")
    msg_id = message.get("id")
    params = message.get("params") or {}

    if method == "initialize":
        return _success(
            msg_id,
            {
                "protocolVersion": "2024-11-05",
                "serverInfo": SERVER_INFO,
                "capabilities": {"tools": {"listChanged": False}},
            },
        )
    if method == "notifications/initialized":
        return None
    if method == "ping":
        return _success(msg_id, {})
    if method == "tools/list":
        return _success(msg_id, {"tools": list_mcp_tools()})
    if method == "tools/call":
        name = params.get("name")
        arguments = params.get("arguments") or {}
        if not name:
            return _error(msg_id, -32602, "Missing tool name")
        try:
            payload = execute_mcp_tool(name, arguments)
        except McpToolError as exc:
            return _error(msg_id, -32000, str(exc))
        return _success(
            msg_id,
            {
                "content": [
                    {
                        "type": "text",
                        "text": json.dumps(payload, ensure_ascii=True),
                    }
                ],
                "structuredContent": payload,
                "isError": False,
            },
        )
    return _error(msg_id, -32601, f"Method not found: {method}")


def main():
    while True:
        try:
            message = _read_message()
            if message is None:
                break
            response = handle_request(message)
            if response is not None:
                _write_message(response)
        except Exception as exc:  # pragma: no cover - emergency server boundary
            err = _error(None, -32099, f"{type(exc).__name__}: {exc}")
            _write_message(err)
            traceback.print_exc(file=sys.stderr)


if __name__ == "__main__":
    main()
