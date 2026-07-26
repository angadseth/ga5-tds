import glob
import json
import os
import sys
import uuid

SCRATCH = os.path.dirname(os.path.abspath(__file__))
GA5 = r"C:\Users\24f20\Desktop\IITM-Subjects\TDS\ga5"
os.environ["Q11_DB_PATH"] = os.path.join(os.environ["TEMP"], "q11a_%s.db" % uuid.uuid4().hex[:6])
os.environ.setdefault("LLM_BASE_URL", "https://api.openai.com/v1")
os.environ.setdefault("LLM_MODEL", "gpt-4o-mini")
os.environ.setdefault("LLM_API_KEY", open(os.path.join(SCRATCH, "key.txt")).read().strip())
sys.path.insert(0, GA5)
sys.path.insert(0, SCRATCH)

from fastapi.testclient import TestClient  # noqa: E402
import main  # noqa: E402
from audit import audit  # noqa: E402

client = TestClient(main.app)
total = 0

cases = []
for path in sorted(glob.glob(os.path.join(GA5, "q11_stable", "*.json"))):
    cases.append((os.path.basename(path)[:-5], json.load(open(path, encoding="utf-8"))))
audit_path = os.path.join(SCRATCH, "audit_incident.json")
if os.path.exists(audit_path):
    cases.append(("audit", json.load(open(audit_path, encoding="utf-8"))))

for label, body in cases:
    body = json.loads(json.dumps(body))
    body["runId"] = "run_" + uuid.uuid4().hex[:20]
    resp = client.post("/v2/incidents", json=body).json()
    total += len(audit(resp, body, label))
    # Drive the approval handshake the way the grader is supposed to, then
    # re-audit the terminal state.
    if resp.get("approvals"):
        ap = resp["approvals"][0]
        resp2 = client.post(
            "/v2/incidents/%s/receipts" % body["runId"],
            json={"receiptId": "rc_" + uuid.uuid4().hex[:10],
                  "approvals": [{"approvalId": ap["approvalId"],
                                 "decision": "approved",
                                 "nonce": str(uuid.uuid4())}]}).json()
        total += len(audit(resp2, body, label + " (approved)"))

print("\nTOTAL PROBLEMS:", total)
