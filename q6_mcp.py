"""MCP Streamable HTTP transport for TDS GA5 Q6.

Single JSON-RPC 2.0 endpoint at /mcp exposing one tool, `solve_challenge`,
which hashes the per-call X-Exam-Challenge header with the registered email.
"""

import hashlib
import json
import uuid

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, Response

router = APIRouter()

EMAIL = "24f2004141@ds.study.iitm.ac.in"
SERVER_NAME = "tds-ga5-mcp"
SERVER_VERSION = "1.0.0"
DEFAULT_PROTOCOL = "2025-06-18"
SUPPORTED_PROTOCOLS = {"2024-11-05", "2025-03-26", "2025-06-18"}
TOOL_NAME = "solve_challenge"

TOOL_DEF = {
    "name": TOOL_NAME,
    "description": (
        "Return the first 16 lowercase hex characters of "
        "SHA-256(\"${X-Exam-Challenge}:${registered email}\"). The challenge is "
        "read from the X-Exam-Challenge HTTP request header of this call, not "
        "from the arguments. Takes no input."
    ),
    "inputSchema": {"type": "object", "properties": {}, "required": []},
}


def _header(request, name):
    """Case-insensitive header lookup that never raises."""
    try:
        value = request.headers.get(name)
        if value is not None:
            return value
    except Exception:
        pass
    try:
        wanted = name.lower()
        for key, value in request.headers.items():
            if key.lower() == wanted:
                return value
    except Exception:
        pass
    return None


def _error(msg_id, code, message, data=None):
    err = {"code": code, "message": message}
    if data is not None:
        err["data"] = data
    return {"jsonrpc": "2.0", "id": msg_id, "error": err}


def _result(msg_id, result):
    return {"jsonrpc": "2.0", "id": msg_id, "result": result}


def solve(challenge):
    payload = "{}:{}".format(challenge, EMAIL)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


def _call_tool(params, request):
    name = params.get("name")
    if name != TOOL_NAME:
        return None, _err_payload(-32602, "Unknown tool: {!r}".format(name))

    challenge = _header(request, "X-Exam-Challenge")
    if challenge is None:
        # Fall back to arguments so manual probes still get a sane answer.
        args = params.get("arguments") or {}
        if isinstance(args, dict):
            for key in ("challenge", "x-exam-challenge", "X-Exam-Challenge"):
                if isinstance(args.get(key), str):
                    challenge = args[key]
                    break
    if challenge is None:
        return {
            "content": [
                {"type": "text", "text": "missing X-Exam-Challenge header"}
            ],
            "isError": True,
        }, None

    challenge = challenge.strip()
    return {
        "content": [{"type": "text", "text": solve(challenge)}],
        "isError": False,
    }, None


def _err_payload(code, message):
    return {"code": code, "message": message}


def _dispatch(message, request, state):
    """Handle one JSON-RPC message. Returns a response dict or None."""
    if not isinstance(message, dict):
        return _error(None, -32600, "Invalid Request")

    msg_id = message.get("id")
    is_request = "id" in message and msg_id is not None
    method = message.get("method")
    params = message.get("params")
    if not isinstance(params, dict):
        params = {}

    if not isinstance(method, str):
        return _error(msg_id, -32600, "Invalid Request") if is_request else None

    if method == "initialize":
        requested = params.get("protocolVersion")
        version = requested if requested in SUPPORTED_PROTOCOLS else DEFAULT_PROTOCOL
        state["new_session"] = True
        return _result(
            msg_id,
            {
                "protocolVersion": version,
                "capabilities": {"tools": {"listChanged": False}},
                "serverInfo": {"name": SERVER_NAME, "version": SERVER_VERSION},
            },
        )

    if method.startswith("notifications/"):
        return None

    if method == "ping":
        return _result(msg_id, {}) if is_request else None

    if method == "tools/list":
        return _result(msg_id, {"tools": [TOOL_DEF]})

    if method == "tools/call":
        result, err = _call_tool(params, request)
        if err is not None:
            return _error(msg_id, err["code"], err["message"])
        return _result(msg_id, result)

    if method in ("resources/list", "resources/templates/list"):
        key = "resourceTemplates" if method.endswith("templates/list") else "resources"
        return _result(msg_id, {key: []})

    if method == "prompts/list":
        return _result(msg_id, {"prompts": []})

    if not is_request:
        return None
    return _error(msg_id, -32601, "Method not found: {}".format(method))


def _wants_sse_only(request):
    accept = (_header(request, "accept") or "").lower()
    return "text/event-stream" in accept and "application/json" not in accept


def _respond(payload, request, state, status=200):
    headers = {}
    session_id = state.get("session_id")
    if session_id:
        headers["Mcp-Session-Id"] = session_id
    if payload is None:
        return Response(status_code=202, headers=headers)
    body = json.dumps(payload, ensure_ascii=False)
    if _wants_sse_only(request):
        headers["Cache-Control"] = "no-cache"
        return Response(
            content="event: message\ndata: {}\n\n".format(body),
            media_type="text/event-stream",
            status_code=status,
            headers=headers,
        )
    return Response(
        content=body,
        media_type="application/json",
        status_code=status,
        headers=headers,
    )


async def _handle(request: Request):
    state = {"session_id": _header(request, "Mcp-Session-Id"), "new_session": False}
    try:
        raw = await request.body()
        try:
            message = json.loads(raw.decode("utf-8")) if raw else None
        except Exception:
            return _respond(_error(None, -32700, "Parse error"), request, state, 200)

        if isinstance(message, list):
            if not message:
                return _respond(
                    _error(None, -32600, "Invalid Request"), request, state, 200
                )
            responses = []
            for item in message:
                out = _dispatch(item, request, state)
                if out is not None:
                    responses.append(out)
            if state.get("new_session") and not state.get("session_id"):
                state["session_id"] = uuid.uuid4().hex
            return _respond(responses or None, request, state)

        if not isinstance(message, dict):
            return _respond(_error(None, -32600, "Invalid Request"), request, state, 200)

        out = _dispatch(message, request, state)
        if state.get("new_session") and not state.get("session_id"):
            state["session_id"] = uuid.uuid4().hex
        return _respond(out, request, state)
    except Exception as exc:  # never raise out of the transport
        return _respond(
            _error(None, -32603, "Internal error: {}".format(exc)), request, state, 200
        )


@router.post("/mcp")
async def mcp_post(request: Request):
    return await _handle(request)


@router.post("/mcp/")
async def mcp_post_slash(request: Request):
    return await _handle(request)


async def _empty_stream(request: Request):
    """Clients probe GET /mcp for a server->client SSE channel.

    We never push anything, so decline with the 405 the spec reserves for
    servers that do not offer that stream. Clients treat it as "no SSE".
    """
    return JSONResponse(
        _error(None, -32000, "Method Not Allowed"),
        status_code=405,
        headers={"Allow": "POST, DELETE"},
    )


@router.get("/mcp")
async def mcp_get(request: Request):
    return await _empty_stream(request)


@router.get("/mcp/")
async def mcp_get_slash(request: Request):
    return await _empty_stream(request)


@router.delete("/mcp")
async def mcp_delete(request: Request):
    return Response(status_code=204)


@router.delete("/mcp/")
async def mcp_delete_slash(request: Request):
    return Response(status_code=204)
