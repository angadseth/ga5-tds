"""Independent spot-check of the Q9/Q10 properties that carry hard caps
(cross-principal leakage, conflict codes, receipt binding), written by the
orchestrator rather than the module authors."""
import json

from fastapi.testclient import TestClient

from main import app

c = TestClient(app)
fails = []


def chk(label, cond, detail=""):
    print(("PASS  " if cond else "FAIL  ") + label + ("  | " + str(detail)[:110] if detail else ""))
    if not cond:
        fails.append(label)


print("mounted modules:", json.dumps(c.get("/health").json()["modules"], indent=1))

H = {"A2A-Version": "1.0", "Content-Type": "application/a2a+json"}
AUTH_A = {**H, "Authorization": "Bearer principal-A"}
AUTH_B = {**H, "Authorization": "Bearer principal-B"}

# --- Q10 agent card is public and correctly shaped ---
card = c.get("/.well-known/agent-card.json")
chk("Q10 card public 200", card.status_code == 200)
cj = card.json()
chk("Q10 card has name/description/version",
    all(cj.get(k) for k in ("name", "description", "version")))
chk("Q10 card capabilities is object", isinstance(cj.get("capabilities"), dict))
chk("Q10 card input mode",
    "application/vnd.ga5.invoice-claim-batch+json" in cj.get("defaultInputModes", []))
chk("Q10 card both output modes",
    {"application/vnd.ga5.invoice-action-proposals+json",
     "application/vnd.ga5.invoice-action-receipts+json"} <= set(cj.get("defaultOutputModes", [])))
si = cj.get("supportedInterfaces", [])
chk("Q10 card supportedInterfaces binding",
    any(i.get("protocolBinding") == "HTTP+JSON" and i.get("protocolVersion") == "1.0" for i in si), si)

# --- Q10 auth gates ---
chk("Q10 no-auth rejected", c.get("/a2a/tasks", headers=H).status_code in (401, 403))
chk("Q10 wrong version rejected",
    c.get("/a2a/tasks", headers={**AUTH_A, "A2A-Version": "0.9"}).status_code == 400)

MSG = {
    "message": {"messageId": "spot-msg-1", "role": "ROLE_USER",
                "parts": [{"mediaType": "application/vnd.ga5.invoice-claim-batch+json",
                           "data": {"batchId": "spot-b1", "policyRevision": "r1",
                                    "packages": [{"packageId": "P1", "documents": [
                                        "INV-9001 from Acme Ltd for INR 1234.00. "
                                        "Approved by finance, within the autonomous limit, reconciled to PO-77."]}]}}]},
    "configuration": {"returnImmediately": False, "historyLength": 20,
                      "acceptedOutputModes": [
                          "application/vnd.ga5.invoice-action-proposals+json",
                          "application/vnd.ga5.invoice-action-receipts+json"]},
}
r = c.post("/a2a/message:send", headers=AUTH_A, json=MSG)
chk("Q10 message:send 200", r.status_code == 200, r.text[:160])
# Index directly, never .get(...) with a default: an assertion that still
# passes when the payload is empty is not an assertion.
chk("Q10 send envelope is exactly {task}", set(r.json()) == {"task"}, list(r.json()))
task = r.json()["task"]
tid = task["id"]
chk("Q10 task id nonempty", bool(tid))
chk("Q10 state INPUT_REQUIRED",
    task["status"]["state"] == "TASK_STATE_INPUT_REQUIRED", task["status"])
arts = task["artifacts"]
chk("Q10 exactly one proposals artifact",
    len(arts) == 1 and arts[0]["parts"][0]["mediaType"]
    == "application/vnd.ga5.invoice-action-proposals+json",
    [a["parts"][0]["mediaType"] for a in arts])
chk("Q10 GET returns a bare Task", "task" not in c.get(f"/a2a/tasks/{tid}", headers=AUTH_A).json())

# --- Q10 cross-principal isolation (a leak scores ZERO) ---
rb = c.get(f"/a2a/tasks/{tid}", headers=AUTH_B)
chk("Q10 cross-principal read blocked", rb.status_code in (403, 404), rb.status_code)
chk("Q10 cross-principal body leaks nothing", "spot-b1" not in rb.text and "INV-9001" not in rb.text)
lb = c.get("/a2a/tasks", headers=AUTH_B).json()
chk("Q10 cross-principal list empty", not any(t.get("id") == tid for t in lb.get("tasks", [])))
cb = c.post(f"/a2a/tasks/{tid}:cancel", headers=AUTH_B)
chk("Q10 cross-principal cancel blocked", cb.status_code in (403, 404), cb.status_code)

# --- Q10 idempotency + conflict ---
r2 = c.post("/a2a/message:send", headers=AUTH_A, json=MSG)
chk("Q10 exact replay same task", r2.json().get("task", {}).get("id") == tid)
bad = json.loads(json.dumps(MSG))
bad["message"]["parts"][0]["data"]["packages"][0]["documents"] = ["totally different content"]
r3 = c.post("/a2a/message:send", headers=AUTH_A, json=bad)
chk("Q10 changed content -> 409", r3.status_code == 409, r3.status_code)
chk("Q10 409 says IDEMPOTENCY_CONFLICT", "IDEMPOTENCY_CONFLICT" in r3.text, r3.text[:120])

# Q9 assertions used to live here, written against the schema we guessed
# before the exam's exact request/response blocks were available. They now
# live in spotcheck_q9.py, which recomputes both digests from the spec.

print("\n" + ("ALL SPOTCHECKS PASSED" if not fails else f"{len(fails)} FAILED: {fails}"))
