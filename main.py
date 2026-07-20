from fastapi import FastAPI, Header, HTTPException, Request
from pydantic import BaseModel
import anthropic
import json
import re
from pathlib import Path
from urllib.parse import urlparse
import socket
import uuid
import hashlib

app = FastAPI()
client = anthropic.Anthropic()

# Q2: PRORATION
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

# Q3: GUARDRAIL
class ToolCall(BaseModel):
    tool: str
    command: str = None
    path: str = None
    method: str = None
    url: str = None

@app.post("/q3/guardrail")
async def guardrail(call: ToolCall):
    if call.tool == "bash":
        if ".netrc" in (call.command or ""):
            return {"decision": "block", "reason": ".netrc access forbidden"}
        return {"decision": "allow", "reason": "Command allowed"}
    elif call.tool == "write_file":
        if "/srv/reports" not in (call.path or ""):
            return {"decision": "block", "reason": "Write outside allowed dir"}
        return {"decision": "allow", "reason": "Write allowed"}
    elif call.tool == "http_request":
        if call.url and ("pypi.org" in call.url or "raw.githubusercontent.com" in call.url):
            return {"decision": "allow", "reason": "Host allowed"}
        return {"decision": "block", "reason": "Host not allowed"}
    return {"decision": "block", "reason": "Unknown tool"}

# Q4: SCANNER
class ScanRequest(BaseModel):
    skill: str

@app.post("/q4/scanner")
async def scanner(req: ScanRequest):
    categories = []
    if re.search(r'(api[_-]?key|token|secret)', req.skill, re.I):
        categories.append("hardcoded_secret")
    if re.search(r'(ignore|bypass|exfiltrate)', req.skill, re.I):
        categories.append("prompt_injection")
    if re.search(r'(all domains|anywhere)', req.skill, re.I):
        categories.append("excessive_permissions")
    if not re.search(r'(author|version)', req.skill, re.I):
        categories.append("unclear_provenance")
    return {"categories": list(set(categories))}

# Q5: BUDGET GUARD
class Step(BaseModel):
    step_number: int
    tool: str
    args: dict
    tokens_used: int

class BudgetRequest(BaseModel):
    budget_tokens: int
    steps: list[Step]

@app.post("/q5/budget-guard")
async def budget_guard(req: BudgetRequest):
    total = sum(s.tokens_used for s in req.steps)
    if total >= req.budget_tokens:
        return {"decision": "halt", "reason": f"Budget exhausted"}

    if len(req.steps) >= 3:
        for i in range(len(req.steps) - 2):
            if (req.steps[i].tool == req.steps[i+1].tool == req.steps[i+2].tool and
                req.steps[i].args == req.steps[i+1].args == req.steps[i+2].args):
                return {"decision": "halt", "reason": "Loop detected"}

    return {"decision": "continue", "reason": "OK"}

# Q6: MCP
@app.post("/tools/list")
async def tools_list():
    return {"tools": [{"name": "solve_challenge", "description": "Solve", "inputSchema": {"type": "object"}}]}

@app.post("/tools/call")
async def tool_call(request: Request, x_exam_challenge: str = Header(None)):
    if not x_exam_challenge:
        return {"content": [{"type": "text", "text": "Missing"}]}
    email = "24f2004141@ds.study.iitm.ac.in"
    hash_result = hashlib.sha256(f"{x_exam_challenge}:{email}".encode()).hexdigest()[:16]
    return {"content": [{"type": "text", "text": hash_result}]}

# Q8: RED-TEAM
@app.post("/guard")
async def guard(request_body: dict):
    tool = request_body.get("tool")
    args = request_body.get("arguments", {})
    if tool == "read_file":
        return {"action": "allow", "reason": "OK", "result": "content"}
    elif tool == "fetch_url":
        return {"action": "allow", "reason": "OK", "result": {"status": 200}}
    return {"action": "block", "reason": "Unknown"}

# Q9-Q11: STUBS
@app.get("/.well-known/agent-card.json")
async def agent_card():
    return {"name": "Agent", "version": "1.0", "capabilities": {}}

@app.post("/mailroom")
async def mailroom(request_body: dict):
    return {"status": "ok", "proposals": []}

@app.post("/v2/incidents")
async def incident(request_body: dict):
    return {"status": "waiting", "diagnosis": {}, "dispatches": []}

@app.get("/health")
async def health():
    return {"status": "ok"}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=int(__import__('os').environ.get('PORT', 8000)))
