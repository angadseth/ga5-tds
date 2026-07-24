"""Test live endpoint with full response dump."""
import httpx, json, time

body = {
    "profile": "ga5-incident-agent/v2",
    "runId": "fullcheck-" + str(int(time.time())),
    "agentName": "t",
    "publicMarker": "m",
    "incident": {
        "incidentId": "1",
        "title": "t",
        "service": "s",
        "severity": "SEV-2",
        "transcript": "[ev_1] correlated sample: database pool exhausted\n[ev_2] bounded observation: connection ceiling",
        "allowedRootCauses": ["database_connection_exhaustion"]
    },
    "toolCatalog": [
        {"name": "query_metrics", "inputSchema": {"type": "object", "properties": {"service": {"type": "string"}}, "required": ["service"]}},
        {"name": "scale_service", "inputSchema": {"type": "object", "properties": {"targetReplicas": {"type": "integer"}}, "required": ["targetReplicas"]}}
    ],
    "policy": {
        "effectTools": ["scale_service"],
        "approvalRequiredFor": [],
        "maximumDiagnostics": 1
    }
}

r = httpx.post("https://ga5-tds.onrender.com/v2/incidents", json=body, timeout=30)
d = r.json()
print("STATUS:", d.get("status"))
print()
print("DISPATCHES count:", len(d.get("dispatches", [])))
print("DISPATCHES:", json.dumps(d.get("dispatches"), indent=2))
print()
print("ACTIONLOG count:", len(d.get("actionLog", [])))
print("ACTIONLOG:", json.dumps(d.get("actionLog"), indent=2))
print()
print("RECEIPTLOG count:", len(d.get("receiptLog", [])))
print()
print("ALL TOP KEYS:", list(d.keys()))
