"""Grader-shaped test for the Q6 MCP Streamable HTTP endpoint."""

import hashlib
import json
import secrets

from fastapi import FastAPI
from fastapi.testclient import TestClient

from q6_mcp import router

EMAIL = "24f2004141@ds.study.iitm.ac.in"
JSON_ACCEPT = {"Accept": "application/json, text/event-stream"}

app = FastAPI()
app.include_router(router)
client = TestClient(app)


def expected(challenge):
    return hashlib.sha256(f"{challenge}:{EMAIL}".encode()).hexdigest()[:16]


def rpc(payload, headers=None, path="/mcp"):
    h = dict(JSON_ACCEPT)
    h.update(headers or {})
    return client.post(path, json=payload, headers=h)


def main():
    # 1. initialize
    r = rpc({
        "jsonrpc": "2.0",
        "id": 1,
        "method": "initialize",
        "params": {
            "protocolVersion": "2025-03-26",
            "capabilities": {},
            "clientInfo": {"name": "grader", "version": "1.0"},
        },
    })
    assert r.status_code == 200, r.status_code
    body = r.json()
    assert body["jsonrpc"] == "2.0" and body["id"] == 1, body
    res = body["result"]
    assert res["protocolVersion"] == "2025-03-26", res
    assert res["serverInfo"]["name"] == "tds-ga5-mcp", res
    assert "tools" in res["capabilities"], res
    session = r.headers.get("mcp-session-id")
    assert session, "initialize must return an Mcp-Session-Id header"
    print("initialize OK  protocol=2025-03-26  session=%s" % session)

    # default protocol when the client asks for something unknown
    r = rpc({"jsonrpc": "2.0", "id": "x", "method": "initialize",
             "params": {"protocolVersion": "1999-01-01"}})
    assert r.json()["result"]["protocolVersion"] == "2025-06-18"
    print("initialize OK  unknown protocol -> 2025-06-18")

    sess = {"Mcp-Session-Id": session}

    # 2. notifications/initialized -> 202, empty body
    r = rpc({"jsonrpc": "2.0", "method": "notifications/initialized"}, sess)
    assert r.status_code == 202, r.status_code
    assert r.content == b"", r.content
    print("notifications/initialized OK  202 empty")

    # 3. ping
    r = rpc({"jsonrpc": "2.0", "id": 2, "method": "ping"}, sess)
    assert r.json()["result"] == {}, r.json()
    print("ping OK")

    # 4. tools/list
    r = rpc({"jsonrpc": "2.0", "id": 3, "method": "tools/list"}, sess)
    tools = r.json()["result"]["tools"]
    names = [t["name"] for t in tools]
    assert "solve_challenge" in names, names
    tool = next(t for t in tools if t["name"] == "solve_challenge")
    assert tool["inputSchema"]["required"] == [], tool
    assert tool["inputSchema"]["type"] == "object", tool
    print("tools/list OK  names=%s  required=[]" % names)

    # 5. five tools/call with fresh challenges
    for i in range(5):
        challenge = secrets.token_hex(16)
        assert len(challenge) == 32
        r = rpc(
            {"jsonrpc": "2.0", "id": 100 + i, "method": "tools/call",
             "params": {"name": "solve_challenge", "arguments": {}}},
            {**sess, "X-Exam-Challenge": challenge,
             "X-Exam-Timestamp": "1750000000000",
             "X-Exam-Signature": "deadbeef"},
        )
        result = r.json()["result"]
        text = result["content"][0]["text"]
        assert result["content"][0]["type"] == "text", result
        assert result.get("isError") is False, result
        assert text == expected(challenge), (challenge, text, expected(challenge))
        print("tools/call %d OK  %s -> %s" % (i + 1, challenge, text))

    # header lookup must be case-insensitive
    challenge = secrets.token_hex(16)
    r = rpc({"jsonrpc": "2.0", "id": 200, "method": "tools/call",
             "params": {"name": "solve_challenge"}},
            {"x-EXAM-challenge": challenge})
    assert r.json()["result"]["content"][0]["text"] == expected(challenge)
    print("tools/call OK  case-insensitive header")

    # no session header at all must still work (lenient sessions)
    challenge = secrets.token_hex(16)
    r = rpc({"jsonrpc": "2.0", "id": 201, "method": "tools/call",
             "params": {"name": "solve_challenge"}},
            {"X-Exam-Challenge": challenge})
    assert r.json()["result"]["content"][0]["text"] == expected(challenge)
    print("tools/call OK  no session header accepted")

    # trailing-slash path
    challenge = secrets.token_hex(16)
    r = rpc({"jsonrpc": "2.0", "id": 202, "method": "tools/call",
             "params": {"name": "solve_challenge"}},
            {"X-Exam-Challenge": challenge}, path="/mcp/")
    assert r.json()["result"]["content"][0]["text"] == expected(challenge)
    print("tools/call OK  /mcp/ trailing slash")

    # 6. unknown tool -> -32602
    r = rpc({"jsonrpc": "2.0", "id": 4, "method": "tools/call",
             "params": {"name": "nope"}}, sess)
    assert r.json()["error"]["code"] == -32602, r.json()
    print("unknown tool OK  -32602")

    # 7. unknown method -> -32601
    r = rpc({"jsonrpc": "2.0", "id": 5, "method": "does/not/exist"}, sess)
    assert r.json()["error"]["code"] == -32601, r.json()
    print("unknown method OK  -32601")

    # 8. malformed JSON -> -32700
    r = client.post("/mcp", content=b"{not json", headers=JSON_ACCEPT)
    assert r.json()["error"]["code"] == -32700, r.json()
    print("parse error OK  -32700")

    # 9. SSE-only Accept
    challenge = secrets.token_hex(16)
    r = client.post(
        "/mcp",
        json={"jsonrpc": "2.0", "id": 6, "method": "tools/call",
              "params": {"name": "solve_challenge"}},
        headers={"Accept": "text/event-stream", "X-Exam-Challenge": challenge},
    )
    assert r.headers["content-type"].startswith("text/event-stream"), r.headers
    text = r.text
    assert text.startswith("event: message\ndata: "), repr(text)
    payload = json.loads(text.split("data: ", 1)[1].strip())
    assert payload["result"]["content"][0]["text"] == expected(challenge)
    print("SSE-only Accept OK  %s" % text.replace("\n", "\\n"))

    # 10. batched request
    c1, c2 = secrets.token_hex(16), secrets.token_hex(16)
    r = rpc(
        [
            {"jsonrpc": "2.0", "id": 7, "method": "tools/list"},
            {"jsonrpc": "2.0", "method": "notifications/cancelled"},
            {"jsonrpc": "2.0", "id": 8, "method": "tools/call",
             "params": {"name": "solve_challenge"}},
        ],
        {"X-Exam-Challenge": c1},
    )
    batch = r.json()
    assert isinstance(batch, list) and len(batch) == 2, batch
    assert batch[0]["result"]["tools"][0]["name"] == "solve_challenge"
    assert batch[1]["result"]["content"][0]["text"] == expected(c1)
    print("batch OK  2 responses, notification dropped")

    # batch of only notifications -> 202
    r = rpc([{"jsonrpc": "2.0", "method": "notifications/initialized"}])
    assert r.status_code == 202 and r.content == b"", (r.status_code, r.content)
    print("notification-only batch OK  202")

    # 11. GET / DELETE probes must not 500
    r = client.get("/mcp", headers={"Accept": "text/event-stream"})
    assert r.status_code in (200, 405), r.status_code
    print("GET /mcp OK  %d" % r.status_code)
    r = client.delete("/mcp", headers=sess)
    assert r.status_code in (200, 204), r.status_code
    print("DELETE /mcp OK  %d" % r.status_code)

    # 12. missing challenge header must not crash
    r = rpc({"jsonrpc": "2.0", "id": 9, "method": "tools/call",
             "params": {"name": "solve_challenge"}})
    assert r.status_code == 200 and "result" in r.json(), r.json()
    print("missing challenge OK  graceful isError")

    print("\nALL TESTS PASSED")
    assert c2  # silence lint


if __name__ == "__main__":
    main()
