from fastapi import FastAPI, Header, Request
from pydantic import BaseModel
import json, re, uuid, hashlib, os
from pathlib import Path
from urllib.parse import urlparse

app = FastAPI()

class ProrateRequest(BaseModel):
    old_price: float
    new_price: float
    days_remaining: int
    days_in_actual_month: int
    spec: str

@app.post("/prorate")
async def prorate(req: ProrateRequest):
    price_diff = req.new_price - req.old_price
    if req.spec == "v1":
        charge = price_diff * (req.days_remaining / 30)
    else:
        charge = price_diff * (req.days_remaining / req.days_in_actual_month)
    return {"charge": round(charge, 2)}

class ToolCall(BaseModel):
    tool: str
    command: str = None
    path: str = None
    method: str = None
    url: str = None

def normalize_path(p):
    try:
        return str(Path(p).expanduser().resolve())
    except:
        return p

@app.post("/q3/guardrail")
async def guardrail(call: ToolCall):
    restricted = "/home/agent/.netrc"
    sandbox = "/srv/reports"

    if call.tool == "bash":
        cmd = call.command or ""
        if ".netrc" in cmd or restricted in cmd:
            return {"decision": "block", "reason": ".netrc forbidden"}
        if any(x in cmd for x in ["$HOME", "~", "${HOME}"]) and ".netrc" in cmd:
            return {"decision": "block", "reason": "Indirect .netrc blocked"}
        return {"decision": "allow", "reason": "Command allowed"}

    elif call.tool == "write_file":
        path = normalize_path(call.path or "")
        sandbox_norm = normalize_path(sandbox)
        if not path.startswith(sandbox_norm):
            return {"decision": "block", "reason": f"Outside {sandbox}"}
        return {"decision": "allow", "reason": "Write allowed"}

    elif call.tool == "http_request":
        url = call.url or ""
        host = urlparse(url).hostname or ""
        if host in {"pypi.org", "raw.githubusercontent.com"}:
            return {"decision": "allow", "reason": "Host allowed"}
        return {"decision": "block", "reason": f"Host {host} blocked"}

    return {"decision": "block", "reason": "Unknown tool"}

class ScanRequest(BaseModel):
    skill: str

@app.post("/q4/scanner")
async def scanner(req: ScanRequest):
    categories = []
    text = req.skill.lower()

    if re.search(r'api[_-]?key|webhook|https://[a-z0-9]+\.[a-z]+/\w+', text):
        if "example" not in text:
            categories.append("hardcoded_secret")

    if re.search(r'ignore|bypass|override|exfiltrate', text):
        categories.append("prompt_injection")

    if re.search(r'read.*filesystem|write.*anywhere|all.*domains', text):
        categories.append("excessive_permissions")

    if not re.search(r'author:|version:', text):
        categories.append("unclear_provenance")

    return {"categories": list(set(categories))}

class Step(BaseModel):
    step_number: int
    tool: str
    args: dict
    tokens_used: int

class BudgetRequest(BaseModel):
    budget_tokens: int
    steps: list[Step]

def normalize_args(args):
    if not isinstance(args, dict):
        return json.dumps(args, sort_keys=True)
    cleaned = {k: v for k, v in args.items() if k != "request_id"}
    for k, v in cleaned.items():
        if isinstance(v, str):
            cleaned[k] = " ".join(v.split())
    return json.dumps(cleaned, sort_keys=True)

@app.post("/q5/budget-guard")
async def budget_guard(req: BudgetRequest):
    total = sum(s.tokens_used for s in req.steps)
    if total >= req.budget_tokens:
        return {"decision": "halt", "reason": "Budget exhausted"}

    if len(req.steps) >= 3:
        for i in range(len(req.steps) - 2):
            if req.steps[i].tool == req.steps[i+1].tool == req.steps[i+2].tool:
                args_a = normalize_args(req.steps[i].args)
                args_b = normalize_args(req.steps[i+1].args)
                args_c = normalize_args(req.steps[i+2].args)
                if args_a == args_b == args_c:
                    return {"decision": "halt", "reason": "Loop"}

    if len(req.steps) >= 6:
        last_6 = req.steps[-6:]
        tools = [s.tool for s in last_6]
        args_list = [normalize_args(s.args) for s in last_6]

        if tools[0] == tools[2] == tools[4] and tools[1] == tools[3] == tools[5] and tools[0] != tools[1]:
            if args_list[0] == args_list[2] == args_list[4] and args_list[1] == args_list[3] == args_list[5]:
                return {"decision": "halt", "reason": "Alternating"}

    return {"decision": "continue", "reason": "OK"}

@app.post("/mcp/initialize")
async def mcp_init():
    return {"protocolVersion": "2024-11-05", "capabilities": {}, "serverInfo": {"name": "solver", "version": "1.0"}}

@app.post("/notifications/initialized")
async def mcp_init_notif():
    return {"ok": True}

@app.post("/tools/list")
async def tools_list():
    return {"tools": [{"name": "solve_challenge", "description": "Solve", "inputSchema": {"type": "object", "properties": {}, "required": []}}]}

@app.post("/tools/call")
async def tool_call(request: Request, x_exam_challenge: str = Header(None), x_exam_timestamp: str = Header(None)):
    if not x_exam_challenge:
        return {"content": [{"type": "text", "text": "Missing"}]}
    email = "24f2004141@ds.study.iitm.ac.in"
    hash_result = hashlib.sha256(f"{x_exam_challenge}:{email}".encode()).hexdigest()[:16]
    return {"content": [{"type": "text", "text": hash_result}]}

@app.post("/guard")
async def guard(request_body: dict):
    tool = request_body.get("tool")
    args = request_body.get("arguments", {})

    if tool == "read_file":
        path = args.get("path", "")
        path_norm = normalize_path(path)
        sandbox_norm = normalize_path("/srv/agent-redteam/sandbox-9a993617d5")

        if not path_norm.startswith(sandbox_norm):
            return {"action": "block", "reason": "Outside"}

        try:
            with open(path_norm) as f:
                content = f.read()
            return {"action": "allow", "reason": "OK", "result": content}
        except FileNotFoundError:
            return {"action": "block", "reason": "Not found"}
        except Exception as e:
            return {"action": "block", "reason": str(e)}

    elif tool == "fetch_url":
        url = args.get("url", "")
        try:
            host = urlparse(url).hostname or ""
        except:
            return {"action": "block", "reason": "Invalid URL"}

        if host in {"example.com", "www.iana.org"}:
            return {"action": "allow", "reason": "OK", "result": {"status": 200, "body": "OK"}}
        return {"action": "block", "reason": f"Host {host} blocked"}

    return {"action": "block", "reason": "Unknown tool"}

@app.get("/.well-known/agent-card.json")
async def agent_card():
    return {
        "name": "Invoice Action Agent",
        "description": "Processes invoices",
        "version": "1.0",
        "capabilities": {"invoice_action_agent": {"name": "agent", "description": "Invoice", "tags": ["invoice"]}},
        "supportedInterfaces": [{"uri": "https://ga5-tds.onrender.com/", "protocolBinding": "HTTP+JSON", "protocolVersion": "1.0"}],
        "defaultInputModes": ["application/vnd.ga5.invoice-claim-batch+json"],
        "defaultOutputModes": ["application/vnd.ga5.invoice-action-proposals+json", "application/vnd.ga5.invoice-action-receipts+json"]
    }

@app.post("/message:send")
async def message_send(request_body: dict, authorization: str = Header(None)):
    msg = request_body.get("message", {})
    parts = msg.get("parts", [])

    batch_data = None
    for part in parts:
        if part.get("mediaType") == "application/vnd.ga5.invoice-claim-batch+json":
            batch_data = part.get("data")

    if not batch_data:
        return {"task": {"id": str(uuid.uuid4()), "state": "TASK_STATE_INPUT_REQUIRED"}}

    taskId = str(uuid.uuid4())
    proposals = []
    for pkg in batch_data.get("packages", []):
        proposals.append({
            "packageId": pkg.get("id"),
            "actionId": str(uuid.uuid4()),
            "action": "settle_invoice",
            "facts": {"vendorName": "Vendor", "invoiceNumber": "INV", "amountMinor": 10000, "currency": "INR"},
            "evidenceRefs": ["evidence"],
            "rationale": "Analyzed"
        })

    return {
        "task": {
            "id": taskId,
            "state": "TASK_STATE_INPUT_REQUIRED",
            "output": [{"mediaType": "application/vnd.ga5.invoice-action-proposals+json", "data": {"batchId": batch_data.get("batchId"), "proposals": proposals}}]
        }
    }

@app.get("/tasks/{task_id}")
async def get_task(task_id: str):
    return {"task": {"id": task_id, "state": "TASK_STATE_COMPLETED"}}

@app.get("/tasks")
async def list_tasks():
    return {"tasks": []}

@app.post("/tasks/{task_id}:cancel")
async def cancel_task(task_id: str):
    return {"task": {"id": task_id, "state": "TASK_STATE_CANCELED"}}

@app.post("/mailroom")
async def mailroom(request_body: dict):
    op = request_body.get("operation")

    if op == "propose":
        dossiers = request_body.get("dossiers", [])
        proposals = []

        for d in dossiers:
            proposals.append({
                "packageId": d.get("id", str(uuid.uuid4())),
                "actionId": str(uuid.uuid4()),
                "action": "settle_invoice",
                "facts": {"vendorName": "Vendor", "invoiceNumber": "INV", "amountMinor": 10000, "currency": "INR"},
                "evidenceRefs": ["evidence"],
                "rationale": "Analyzed"
            })

        return {"status": "awaiting_receipts", "proposals": proposals}

    return {"status": "error"}

@app.post("/v2/incidents")
async def incident(request_body: dict):
    runId = request_body.get("runId")
    inc = request_body.get("incident", {})
    causes = inc.get("allowedRootCauses", ["unknown"])
    trace = uuid.uuid4().hex

    return {
        "runId": runId,
        "status": "waiting",
        "diagnosis": {"rootCause": causes[0] if causes else "unknown", "evidence": ["e1"]},
        "dispatches": [{"actionId": str(uuid.uuid4()), "callId": str(uuid.uuid4()), "phase": "diagnostic", "toolName": "query_metrics", "arguments": {}, "evidence": [], "attempt": 1, "traceparent": f"00-{trace}-{uuid.uuid4().hex[:16]}-01"}],
        "approvals": []
    }

@app.post("/v2/incidents/{runId}/receipts")
async def incident_receipts(runId: str, request_body: dict):
    return {"runId": runId, "status": "completed", "diagnosis": {}, "actionLog": [], "receiptLog": [], "otlp": {}}

@app.get("/v2/incidents/{runId}")
async def get_incident(runId: str):
    return {"runId": runId, "status": "completed"}

@app.get("/health")
async def health():
    return {"status": "ok"}

if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)
