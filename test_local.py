"""Detailed analysis of the response structure."""
import json, time, os, sys, asyncio

os.environ["Q11_SELF_COMPLETE"] = "1"
for mod in list(sys.modules):
    if mod.startswith("q11"):
        del sys.modules[mod]
import q11_incident as q11

async def test():
    body = {
        "profile": "ga5-incident-agent/v2",
        "runId": "analysis-" + str(int(time.time())),
        "agentName": "test-agent",
        "publicMarker": "test",
        "incident": {
            "incidentId": "inc-1",
            "title": "Test incident",
            "service": "test-svc",
            "severity": "SEV-2",
            "transcript": "[ev_1] correlated sample: database connection pool exhausted\n[ev_2] bounded observation: connection ceiling reached at 100\n[ev_3] decoy noise line about something",
            "allowedRootCauses": ["database_connection_exhaustion", "traffic_capacity_exhaustion"]
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
    state = q11.start_run(body, None)
    incident = body["incident"]
    catalog = body["toolCatalog"]
    policy = body["policy"]
    plan = q11.fallback_plan(incident, catalog, policy, 1)
    state["plan"] = plan
    state["diagnosis"] = {"rootCause": plan["rootCause"], "evidence": plan["evidence"]}
    q11.record_model_span(state, "test", True)
    dispatches_initial = q11.open_diagnostics(state, plan)
    
    print("=== AFTER open_diagnostics (before self_complete) ===")
    print("Initial dispatches:", json.dumps(dispatches_initial, indent=2))
    print()
    
    dispatches, approvals = q11.self_complete(state)
    
    print("=== AFTER self_complete ===")
    print("Returned dispatches:", dispatches)
    print("Returned approvals:", approvals)
    print("State status:", state["status"])
    print()
    
    response = q11.public_response(state, dispatches, approvals)
    
    print("=== FINAL RESPONSE ===")
    print("dispatches:", json.dumps(response.get("dispatches"), indent=2))
    print("actionLog:", json.dumps(response.get("actionLog"), indent=2))
    print()
    
    # Simulate GET
    # Save and reload
    q11.save_run(body["runId"], "test-fp", state, response)
    run = q11.load_run(body["runId"])
    loaded_state = run["state"]
    get_response = q11.public_response(loaded_state, 
                                        q11.pending_dispatches(loaded_state),
                                        q11.pending_approvals(loaded_state))
    
    print("=== GET RESPONSE ===")
    print("dispatches:", json.dumps(get_response.get("dispatches"), indent=2))
    print("actionLog:", json.dumps(get_response.get("actionLog"), indent=2))
    print()
    
    print("=== POST vs GET match? ===")
    print("Match:", json.dumps(response) == json.dumps(get_response))
    if json.dumps(response) != json.dumps(get_response):
        for key in response:
            if json.dumps(response.get(key)) != json.dumps(get_response.get(key)):
                print(f"  DIFF in '{key}':")
                print(f"    POST: {json.dumps(response.get(key))[:100]}")
                print(f"    GET:  {json.dumps(get_response.get(key))[:100]}")

asyncio.run(test())
