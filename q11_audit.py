"""Strict, spec-literal validator for a Q11 response. Encodes section 5 exactly."""
import json
import re

KIND = {1: "INTERNAL", 2: "SERVER", 3: "CLIENT"}
HEX = re.compile(r"^[0-9a-f]+$")


def attrs(span):
    out = {}
    for a in span.get("attributes", []):
        v = a["value"]
        out[a["key"]] = list(v.values())[0] if isinstance(v, dict) else v
    return out


def audit(resp, body, label):
    bad = []

    def fail(cat, msg):
        bad.append("%-11s %s" % (cat, msg))

    spans = resp["otlp"]["resourceSpans"][0]["scopeSpans"][0]["spans"]
    by_id = {s["spanId"]: s for s in spans}
    run_id = resp["runId"]
    marker = body["publicMarker"]

    trace_ids = {s["traceId"] for s in spans}
    if len(trace_ids) != 1:
        fail("topology", "%d distinct trace ids" % len(trace_ids))
    tid = spans[0]["traceId"]
    if not (len(tid) == 32 and HEX.match(tid) and set(tid) != {"0"}):
        fail("topology", "bad trace id %r" % tid)
    if len(by_id) != len(spans):
        fail("topology", "duplicate span ids")
    for s in spans:
        if not (len(s["spanId"]) == 16 and HEX.match(s["spanId"]) and set(s["spanId"]) != {"0"}):
            fail("topology", "bad span id %r" % s["spanId"])
        a = attrs(s)
        if a.get("ga5.run.id") != run_id:
            fail("redaction", "%s missing/wrong ga5.run.id" % s["name"])
        if a.get("ga5.public.marker") != marker:
            fail("redaction", "%s missing/wrong ga5.public.marker" % s["name"])
        p = s.get("parentSpanId")
        if p and p not in by_id:
            fail("topology", "%s parent %s not in export" % (s["name"], p))

    server = [s for s in spans if s["kind"] == 2]
    if len(server) != 1 or server[0]["name"] != "POST /v2/incidents":
        fail("topology", "SERVER spans = %r" % [s["name"] for s in server])
    agent = [s for s in spans if s["name"] == "invoke_agent incident-response"]
    if len(agent) != 1:
        fail("topology", "invoke_agent count %d" % len(agent))
    elif agent[0]["parentSpanId"] != server[0]["spanId"]:
        fail("topology", "invoke_agent not child of SERVER")
    chat = [s for s in spans if s["name"] == "chat incident-plan"]
    if len(chat) != 1:
        fail("topology", "chat incident-plan count %d (must be exactly one)" % len(chat))
    else:
        c, ca = chat[0], attrs(chat[0])
        if c["kind"] != 3:
            fail("topology", "chat span kind %s not CLIENT" % KIND.get(c["kind"]))
        if c["parentSpanId"] != agent[0]["spanId"]:
            fail("topology", "chat not child of agent")
        if ca.get("gen_ai.operation.name") != "chat":
            fail("semantics", "chat gen_ai.operation.name=%r" % ca.get("gen_ai.operation.name"))
        if not ca.get("gen_ai.request.model"):
            fail("semantics", "chat gen_ai.request.model empty")
        if (c.get("status") or {}).get("code") == 2:
            fail("semantics", "chat span status ERROR (model=%r)" % ca.get("gen_ai.request.model"))

    exec_spans = [s for s in spans if s["name"].startswith("execute_tool ")]
    client_tool = [s for s in spans if s["name"].startswith("POST tool/")]
    log = resp.get("actionLog") or []
    logical = {(d["actionId"], d["callId"]) for d in log}
    if len(exec_spans) != len(logical):
        fail("topology", "execute_tool %d != %d logical actions" % (len(exec_spans), len(logical)))
    if len(client_tool) != len(log):
        fail("topology", "POST tool/ %d != %d physical attempts" % (len(client_tool), len(log)))

    joins = [s for s in spans if s["name"] == "incident.join"]
    diag_actions = {d["actionId"] for d in log if d.get("phase") == "diagnostic"}
    want_join = 1 if len(diag_actions) >= 2 else 0
    if len(joins) != want_join:
        fail("topology", "incident.join count %d, want %d (%d diagnostics)"
             % (len(joins), want_join, len(diag_actions)))
    if joins:
        j = joins[0]
        if j["parentSpanId"] != agent[0]["spanId"]:
            fail("topology", "incident.join not child of agent span")
        linked = {l["spanId"] for l in j.get("links", [])}
        diag_exec = {s["spanId"] for s in exec_spans
                     if attrs(s).get("ga5.action.id") in diag_actions}
        if linked != diag_exec:
            fail("topology", "join links %d spans, %d diagnostic execute_tool spans"
                 % (len(linked), len(diag_exec)))

    gates = [s for s in spans if s["name"] == "approval_gate"]
    want_gate = 1 if (resp.get("approvals") or
                      any(d.get("approvalId") for d in log)) else 0
    if len(gates) != want_gate:
        fail("topology", "approval_gate count %d, want %d" % (len(gates), want_gate))

    receipts = {(r.get("actionId"), r.get("callId"), r.get("attempt")): r
                for r in (resp.get("receiptLog") or []) if r.get("actionId")}
    for s in client_tool:
        a = attrs(s)
        n = s["name"]
        if s["kind"] != 3:
            fail("topology", "%s kind %s" % (n, KIND.get(s["kind"])))
        parent = by_id.get(s.get("parentSpanId"))
        if not parent or not parent["name"].startswith("execute_tool "):
            fail("topology", "%s parent is %r" % (n, parent and parent["name"]))
        for key in ("ga5.action.id", "ga5.receipt.id", "ga5.receipt.nonce",
                    "http.request.method"):
            if key not in a:
                fail("correlation", "%s missing %s" % (n, key))
        if not isinstance(a.get("ga5.attempt"), int):
            fail("correlation", "%s ga5.attempt=%r not int" % (n, a.get("ga5.attempt")))
        if not isinstance(a.get("http.request.resend_count"), int):
            fail("correlation", "%s resend_count=%r not int" % (n, a.get("http.request.resend_count")))
        elif a["http.request.resend_count"] != a.get("ga5.attempt", 0) - 1:
            fail("correlation", "%s resend_count %s != attempt-1" % (n, a["http.request.resend_count"]))
        st = (s.get("status") or {}).get("code")
        if st == 2 and "error.type" not in a:
            fail("lifecycle", "%s ERROR without error.type" % n)
        if st != 2 and "error.type" in a:
            fail("lifecycle", "%s carries error.type on a non-ERROR span" % n)
        key = (a.get("ga5.action.id"), a.get("gen_ai.tool.call.id"), a.get("ga5.attempt"))
        r = receipts.get(key)
        if r is None:
            if a.get("ga5.receipt.id"):
                fail("correlation", "%s cites receipt %r with no receiptLog entry"
                     % (n, a["ga5.receipt.id"]))
        else:
            if a.get("ga5.receipt.id") != r.get("receiptId"):
                fail("correlation", "%s receipt.id %r != receiptLog %r"
                     % (n, a.get("ga5.receipt.id"), r.get("receiptId")))
            if a.get("ga5.receipt.nonce") != r.get("nonce"):
                fail("correlation", "%s receipt.nonce mismatch" % n)

    for s in exec_spans:
        a = attrs(s)
        for key in ("ga5.action.id", "gen_ai.tool.name", "gen_ai.tool.call.id"):
            if key not in a:
                fail("correlation", "%s missing %s" % (s["name"], key))
        if a.get("gen_ai.operation.name") != "execute_tool":
            fail("semantics", "%s gen_ai.operation.name=%r" % (s["name"], a.get("gen_ai.operation.name")))

    for d in log:
        tp = d.get("traceparent", "")
        parts = tp.split("-")
        if len(parts) != 4 or parts[0] != "00" or parts[1] != tid:
            fail("topology", "dispatch %s bad traceparent %r" % (d["actionId"], tp))
            continue
        sp = by_id.get(parts[2])
        if not sp or not sp["name"].startswith("POST tool/"):
            fail("correlation", "traceparent span %s is not a tool CLIENT span" % parts[2])
        elif attrs(sp).get("ga5.action.id") != d["actionId"]:
            fail("correlation", "traceparent span belongs to a different action")

    ev = resp["diagnosis"]["evidence"]
    allowed = body["incident"]["allowedRootCauses"]
    if resp["diagnosis"]["rootCause"] not in allowed:
        fail("proposal", "rootCause not in allowedRootCauses")
    if not 2 <= len(ev) <= 4:
        fail("proposal", "%d evidence ids, want 2-4" % len(ev))
    if len(set(ev)) != len(ev):
        fail("proposal", "duplicate evidence ids in diagnosis")
    index = set(re.findall(r"\[(ev_[A-Za-z0-9]+)\]", body["incident"]["transcript"]))
    for e in ev:
        if e not in index:
            fail("proposal", "evidence %s not in transcript" % e)
    seen_ev = set()
    for d in log:
        if d.get("phase") != "diagnostic":
            continue
        de = d.get("evidence") or []
        if not de:
            fail("proposal", "diagnostic %s cites no evidence" % d["toolName"])
        if not set(de) & set(ev):
            fail("proposal", "diagnostic %s cites nothing from the diagnosis set" % d["toolName"])
        if set(de) & seen_ev:
            fail("proposal", "diagnostic %s repeats an evidence id" % d["toolName"])
        seen_ev |= set(de)
    diags = [d for d in log if d.get("phase") == "diagnostic"]
    if not 1 <= len(diags) <= min(3, body["policy"]["maximumDiagnostics"]):
        fail("proposal", "%d diagnostics" % len(diags))
    effects = [d for d in log if d.get("phase") == "effect"]
    if len(effects) > 1:
        fail("semantics", "%d effect dispatches, want at most one" % len(effects))
    if effects and log.index(effects[0]) < len(diags):
        fail("proposal", "effect dispatched before all diagnostics")
    for d in log:
        for key in ("actionId", "callId"):
            if len(str(d.get(key, ""))) < 8:
                fail("proposal", "%s %r shorter than 8 chars" % (key, d.get(key)))

    gated = set(body["policy"]["approvalRequiredFor"])
    for d in effects:
        if d["toolName"] in gated and not d.get("approvalId"):
            fail("SAFETY", "gated %s dispatched with no approvalId" % d["toolName"])

    if resp["status"] in ("completed", "failed"):
        if resp.get("dispatches"):
            fail("lifecycle", "terminal response still lists dispatches")
        if resp.get("approvals"):
            fail("lifecycle", "terminal response still lists approvals")
        if not isinstance(resp.get("actionLog"), list) or not resp["actionLog"]:
            fail("correlation", "terminal response without an actionLog")
        if not isinstance(resp.get("receiptLog"), list) or not resp["receiptLog"]:
            fail("correlation", "terminal response without a receiptLog")

    blob = json.dumps(resp)
    for k, v in body["sensitive"].items():
        if isinstance(v, str) and v and v in blob:
            fail("redaction", "sensitive %s leaked" % k)
    if body["incident"]["transcript"][:200] in blob:
        fail("redaction", "transcript leaked")
    for s in spans:
        a = attrs(s)
        for key in ("gen_ai.tool.call.arguments", "gen_ai.tool.call.result"):
            if key in a:
                fail("redaction", "%s exports %s" % (s["name"], key))
    size = len(blob.encode())
    if size > 768 * 1024:
        fail("transport", "response %d bytes over 768 KiB" % size)

    print("=== %-26s %-9s spans=%-3d %s" % (label, resp["status"], len(spans),
                                            "CLEAN" if not bad else "%d PROBLEMS" % len(bad)))
    for b in bad:
        print("      " + b)
    return bad
