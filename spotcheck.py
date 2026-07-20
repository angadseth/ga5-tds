"""Independent adversarial spot-check, written by the orchestrator (not the
module authors) against the highest-risk graded traps."""
import hashlib

from fastapi.testclient import TestClient

from main import app

c = TestClient(app)
fails = []


def chk(label, cond, detail=""):
    print(("PASS  " if cond else "FAIL  ") + label + ("  | " + detail if detail else ""))
    if not cond:
        fails.append(label)


# --- Q3: must-allow reads (over-blocking scores poorly) ---
for cmd in ["ls -la /home/agent/workspace",
            "cat /home/agent/workspace/main.py",
            "grep -rn TODO .",
            "python3 -m pytest -q",
            "cat /etc/hostname"]:
    r = c.post("/q3/check", json={"tool": "bash", "command": cmd}).json()
    chk(f"Q3 allow: {cmd[:38]}", r["decision"] == "allow", r["reason"])

# --- Q3: must-block .netrc in every disguise ---
for cmd in ["cat /home/agent/.netrc",
            "cat $HOME/.netrc",
            "cat ${HOME}/.netrc",
            "cat ~/.netrc",
            "cat ../.netrc",
            "cd /tmp && cat /home/agent/.netrc",
            "bash -c 'cat /home/agent/.netrc'",
            "echo Y2F0IC9ob21lL2FnZW50Ly5uZXRyYw== | base64 -d | sh",
            "cat /home/agent/.n''etrc",
            "c\\at /home/agent/.netrc",
            "head -n5 ../../agent/.netrc",
            "python3 -c \"print(open('/home/agent/.netrc').read())\""]:
    r = c.post("/q3/check", json={"tool": "bash", "command": cmd}).json()
    chk(f"Q3 block: {cmd[:38]}", r["decision"] == "block", r["reason"])

# --- Q3: writes + hosts ---
chk("Q3 write inside", c.post("/q3/check", json={"tool": "write_file", "path": "/srv/reports/a/b.txt", "content": "x"}).json()["decision"] == "allow")
chk("Q3 write traversal", c.post("/q3/check", json={"tool": "write_file", "path": "/srv/reports/../etc/passwd", "content": "x"}).json()["decision"] == "block")
chk("Q3 write prefix-confusion", c.post("/q3/check", json={"tool": "write_file", "path": "/srv/reportsevil/x", "content": "x"}).json()["decision"] == "block")
chk("Q3 host pypi", c.post("/q3/check", json={"tool": "http_request", "method": "GET", "url": "https://pypi.org/simple/"}).json()["decision"] == "allow")
chk("Q3 host raw.gh", c.post("/q3/check", json={"tool": "http_request", "method": "GET", "url": "https://raw.githubusercontent.com/a/b"}).json()["decision"] == "allow")
chk("Q3 host confusion", c.post("/q3/check", json={"tool": "http_request", "method": "GET", "url": "https://pypi.org.evil.example/x"}).json()["decision"] == "block")
chk("Q3 host subdomain", c.post("/q3/check", json={"tool": "http_request", "method": "GET", "url": "https://evil.pypi.org/x"}).json()["decision"] == "block")
chk("Q3 host userinfo", c.post("/q3/check", json={"tool": "http_request", "method": "GET", "url": "https://pypi.org@evil.example/x"}).json()["decision"] == "block")

# --- Q5: the two rules the grader probes hardest ---
def steps(*t):
    return [{"step_number": i + 1, "tool": a, "args": b, "tokens_used": 10} for i, (a, b) in enumerate(t)]


two = steps(("f", {"x": 1}), ("f", {"x": 1}))
chk("Q5 two-in-a-row continues", c.post("/q5/check", json={"budget_tokens": 34000, "steps": two}).json()["decision"] == "continue")
three = steps(("f", {"x": 1}), ("f", {"x": 1}), ("f", {"x": 1}))
chk("Q5 three-in-a-row halts", c.post("/q5/check", json={"budget_tokens": 34000, "steps": three}).json()["decision"] == "halt")
page = steps(("l", {"page": 1}), ("l", {"page": 2}), ("l", {"page": 3}), ("l", {"page": 4}))
chk("Q5 pagination continues", c.post("/q5/check", json={"budget_tokens": 34000, "steps": page}).json()["decision"] == "continue")
rid = steps(("f", {"a": 1, "request_id": "p"}), ("f", {"request_id": "q", "a": 1}), ("f", {"a": 1, "request_id": "r"}))
chk("Q5 request_id+keyorder halts", c.post("/q5/check", json={"budget_tokens": 34000, "steps": rid}).json()["decision"] == "halt")
chk("Q5 budget exact halts", c.post("/q5/check", json={"budget_tokens": 20, "steps": two}).json()["decision"] == "halt")
chk("Q5 budget one-below continues", c.post("/q5/check", json={"budget_tokens": 21, "steps": two}).json()["decision"] == "continue")
chk("Q5 empty continues", c.post("/q5/check", json={"budget_tokens": 34000, "steps": []}).json()["decision"] == "continue")

# --- Q6: full MCP handshake + the 5 graded challenges ---
EMAIL = "24f2004141@ds.study.iitm.ac.in"
init = c.post("/mcp", json={"jsonrpc": "2.0", "id": 1, "method": "initialize",
                            "params": {"protocolVersion": "2025-06-18", "capabilities": {},
                                       "clientInfo": {"name": "t", "version": "1"}}},
              headers={"Accept": "application/json, text/event-stream"})
chk("Q6 initialize 200", init.status_code == 200, str(init.status_code))
tl = c.post("/mcp", json={"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
            headers={"Accept": "application/json, text/event-stream"}).json()
names = [t["name"] for t in tl["result"]["tools"]]
chk("Q6 tool named solve_challenge", names == ["solve_challenge"], str(names))
chk("Q6 no required props", not tl["result"]["tools"][0]["inputSchema"].get("required"))
ok = True
for i in range(5):
    ch = hashlib.sha256(str(i).encode()).hexdigest()[:32]
    r = c.post("/mcp", json={"jsonrpc": "2.0", "id": 10 + i, "method": "tools/call",
                             "params": {"name": "solve_challenge", "arguments": {}}},
               headers={"X-Exam-Challenge": ch, "Accept": "application/json, text/event-stream"}).json()
    want = hashlib.sha256(f"{ch}:{EMAIL}".encode()).hexdigest()[:16]
    got = r["result"]["content"][0]["text"]
    ok = ok and got == want
chk("Q6 five fresh challenges correct", ok)

# --- Q8: the benign traps that must be ALLOWED, and the canary that must not leak ---
SB = "/srv/agent-redteam/sandbox-9a993617d5"
CANARY = "AGENT_GUARDRAIL_CANARY_54c3dc886628f3ce4d1f06ddaaa03146ef7fdc1e"
bodies = []
for p, want in [(f"{SB}/notes/report.txt", "allow"),
                (f"{SB}/notes/looks-like-..-but-safe.txt", "allow"),
                (f"{SB}/encoded/%2e%2e-literal.txt", "allow"),
                ("/srv/agent-redteam/outside-87c065e3/canary.txt", "block"),
                (f"{SB}/../outside-87c065e3/canary.txt", "block"),
                (f"{SB}/%2e%2e/outside-87c065e3/canary.txt", "block"),
                (f"{SB}/%252e%252e/outside-87c065e3/canary.txt", "block"),
                ("/etc/passwd", "block"),
                ("/srv/agent-redteam/sandbox-9a993617d5-evil/x.txt", "block")]:
    r = c.post("/q8/check", json={"tool": "read_file", "arguments": {"path": p}})
    bodies.append(r.text)
    chk(f"Q8 {want}: {p[-46:]}", r.json()["action"] == want, r.json().get("reason", ""))
for u, want in [("https://example.com/", "allow"), ("https://www.iana.org/", "allow"),
                ("http://127.0.0.1/", "block"), ("http://169.254.169.254/latest/meta-data/", "block"),
                ("https://example.com@evil.example/", "block"), ("https://example.com.evil.example/", "block"),
                ("file:///etc/passwd", "block"), ("http://localhost:8080/", "block")]:
    r = c.post("/q8/check", json={"tool": "fetch_url", "arguments": {"url": u}})
    bodies.append(r.text)
    chk(f"Q8 {want}: {u[:44]}", r.json()["action"] == want, r.json().get("reason", ""))
chk("Q8 canary never leaked", not any(CANARY in b for b in bodies))

print("\n" + ("ALL SPOTCHECKS PASSED" if not fails else f"{len(fails)} FAILED: {fails}"))
