"""Comprehensive grader analysis - check every requirement."""
import httpx, json, time, sys

BASE = "https://ga5-tds.onrender.com"
RUN = "analysis-" + str(int(time.time()))

body = {
    "profile": "ga5-incident-agent/v2",
    "runId": RUN,
    "agentName": "test-agent",
    "publicMarker": "test-marker",
    "incident": {
        "incidentId": "inc-1",
        "title": "Database connection pool exhaustion",
        "service": "payment-service",
        "severity": "SEV-2",
        "transcript": "[ev_1] correlated sample: database connection pool exhausted at 100 connections\n[ev_2] bounded observation: connection ceiling reached, all connections in use\n[ev_3] decoy noise: CPU utilization normal at 45%",
        "allowedRootCauses": ["database_connection_exhaustion", "traffic_spike"]
    },
    "toolCatalog": [
        {"name": "query_database_metrics", "inputSchema": {"type": "object", "properties": {"service": {"type": "string"}, "metric": {"type": "string"}}, "required": ["service"]}},
        {"name": "scale_database_pool", "inputSchema": {"type": "object", "properties": {"service": {"type": "string"}, "targetConnections": {"type": "integer"}}, "required": ["service", "targetConnections"]}}
    ],
    "policy": {
        "effectTools": ["scale_database_pool"],
        "approvalRequiredFor": [],
        "maximumDiagnostics": 1
    }
}

print("=== POST ===")
r = httpx.post(f"{BASE}/v2/incidents", json=body, timeout=30)
print(f"HTTP {r.status_code}")
d = r.json()

print(f"\nstatus: {d.get('status')}")
print(f"runId: {d.get('runId')}")

# PROPOSAL checks
diag = d.get("diagnosis", {})
print(f"\n--- PROPOSAL ---")
print(f"rootCause: {diag.get('rootCause')}")
print(f"evidence: {diag.get('evidence')}")
print(f"chosenEffect: {d.get('chosenEffect')}")
print(f"dispatches count: {len(d.get('dispatches', []))}")
print(f"actionLog count: {len(d.get('actionLog', []))}")
alog = d.get("actionLog", [])
for i, a in enumerate(alog):
    print(f"  [{i}] phase={a.get('phase')} tool={a.get('toolName')} args={a.get('arguments')} tp={a.get('traceparent','')[:30]}")

# CORRELATION checks
print(f"\n--- CORRELATION ---")
rlog = d.get("receiptLog", [])
print(f"receiptLog count: {len(rlog)}")
for i, r_entry in enumerate(rlog):
    print(f"  [{i}] receiptId={r_entry.get('receiptId','?')[:20]} actionId={r_entry.get('actionId','?')[:20]} callId={r_entry.get('callId','?')[:20]}")

# TOPOLOGY checks - OTLP
print(f"\n--- TOPOLOGY (OTLP) ---")
otlp = d.get("otlp", {})
res_spans = otlp.get("resourceSpans", [])
print(f"resourceSpans count: {len(res_spans)}")
if res_spans:
    scope_spans = res_spans[0].get("scopeSpans", [])
    print(f"scopeSpans count: {len(scope_spans)}")
    if scope_spans:
        spans = scope_spans[0].get("spans", [])
        print(f"spans count: {len(spans)}")
        trace_ids = set()
        span_ids = set()
        for s in spans:
            tid = s.get("traceId", "")
            sid = s.get("spanId", "")
            pid = s.get("parentSpanId", "")
            name = s.get("name", "")
            kind = s.get("kind", 0)
            trace_ids.add(tid)
            span_ids.add(sid)
            attrs = {a["key"]: a.get("value", {}) for a in s.get("attributes", [])}
            print(f"  span: {name:40s} kind={kind} sid={sid[:12]} pid={pid[:12]} action={attrs.get('ga5.action.id',{}).get('stringValue','')[:20]} receipt={attrs.get('ga5.receipt.id',{}).get('stringValue','')[:20]}")
        print(f"unique traceIds: {len(trace_ids)} (should be 1)")
        print(f"unique spanIds: {len(span_ids)} vs spans: {len(spans)} (should match)")
        # Check parent links
        for s in spans:
            pid = s.get("parentSpanId", "")
            if pid and pid not in span_ids:
                print(f"  BROKEN PARENT: span {s['name']} has parent {pid} which is NOT in span set!")

# DURABILITY check
print(f"\n--- DURABILITY ---")
r2 = httpx.get(f"{BASE}/v2/incidents/{RUN}", timeout=15)
d2 = r2.json()
match = json.dumps(d, sort_keys=True) == json.dumps(d2, sort_keys=True)
print(f"POST==GET (sort_keys): {match}")
if not match:
    for key in d:
        v1 = json.dumps(d.get(key), sort_keys=True)
        v2 = json.dumps(d2.get(key), sort_keys=True)
        if v1 != v2:
            print(f"  DIFF in '{key}'")

# REDACTION check
print(f"\n--- REDACTION ---")
resp_str = json.dumps(d)
forbidden = ["database connection pool exhausted", "connection ceiling", "CPU utilization"]
for f in forbidden:
    if f.lower() in resp_str.lower():
        print(f"  LEAKED: '{f}' found in response!")
    else:
        print(f"  OK: '{f}' not found")

# 409 REPLAY check
print(f"\n--- REPLAY (409) ---")
r3 = httpx.post(f"{BASE}/v2/incidents", json=body, timeout=30)
print(f"Replay HTTP status: {r3.status_code} (should be 409)")
