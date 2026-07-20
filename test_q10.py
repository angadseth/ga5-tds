"""Q10 self-check. Run: python test_q10.py

Uses a fake LLM for determinism plus one optional live call at the end to prove
the real prompt classifies sensibly.
"""
import copy
import json
import os
import sys
import tempfile
import uuid

os.environ["GA5_DB"] = os.path.join(tempfile.mkdtemp(), "q10test.db")
os.environ.setdefault("A2A_BASE_URL", "https://ga5-tds.onrender.com/a2a/")

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from fastapi import FastAPI            # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

import q10_a2a                          # noqa: E402

app = FastAPI()
app.include_router(q10_a2a.router)
client = TestClient(app)

BASE = "https://ga5-tds.onrender.com/a2a/"
H = {"A2A-Version": "1.0", "Content-Type": "application/a2a+json"}
ALICE = dict(H, Authorization="Bearer alice-token")
BOB = dict(H, Authorization="Bearer bob-token")

PASS, FAIL = [], []


def check(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    print(("  ok   " if cond else "  FAIL ") + name + ("" if cond else f"  <- {detail}"))


# ---------------------------------------------------------------- fixtures

def make_package(pid, kind):
    docs = {
        "clean": [
            {"docId": f"DOC-{pid}-01",
             "text": f"Invoice INV-{pid}-77 from Larkfield Components Pvt Ltd for INR 12,340.50. "
                     f"Purchase order PO-{pid}-A matches goods receipt GRN-{pid}-9 line for line. "
                     f"Policy 4.2 sets the autonomous settlement limit at INR 50,000."},
            {"docId": f"DOC-{pid}-02",
             "text": "Historical note: in an earlier case from 2019 we opened an exception for a "
                     "similar vendor. That example is illustrative only. The quality hold that was "
                     "raised on 2 March is no longer applicable once GRN-%s-9 cleared, and it did "
                     "clear. Payment is NOT to be held." % pid},
        ],
        "authority": [
            {"docId": f"DOC-{pid}-01",
             "text": f"Invoice INV-{pid}-88 from Vantel Systems Ltd for INR 8,50,000.00 against "
                     f"contract CTR-{pid}-B. Reconciliation is complete and no discrepancy remains. "
                     f"Policy 4.2 caps autonomous settlement at INR 50,000; anything above that is "
                     f"outside delegated authority and requires approval."},
        ],
        "hold": [
            {"docId": f"DOC-{pid}-01",
             "text": f"Invoice INV-{pid}-99 from Corbin Freight LLP for INR 21,000.00. Goods receipt "
                     f"GRN-{pid}-3 is still awaiting the third party inspection certificate; payment "
                     f"pauses until that verification completes. Policy 4.2 applies."},
        ],
        "duplicate": [
            {"docId": f"DOC-{pid}-01",
             "text": f"Invoice INV-{pid}-55 from Halvern Tools Pvt Ltd for INR 4,500.00 was already "
                     f"paid on 11 April under payment run PR-{pid}-2. This submission is the same "
                     f"commercial invoice re-sent by the vendor."},
        ],
        "conflict": [
            {"docId": f"DOC-{pid}-01",
             "text": f"Invoice INV-{pid}-66 from Merrow Optics for INR 74,000.00 but purchase order "
                     f"PO-{pid}-C records 30 units while goods receipt GRN-{pid}-7 records 12 units. "
                     f"The records materially conflict and cannot be reconciled."},
        ],
    }[kind]
    return {"packageId": pid, "documents": docs}


KINDS = ["clean", "authority", "hold", "duplicate", "conflict"]


def make_batch(batch_id="BATCH-1", n=12, prefix="PKG"):
    return {"batchId": batch_id, "policyRevision": "R-4.2",
            "packages": [make_package(f"{prefix}-{i:02d}", KINDS[i % len(KINDS)])
                         for i in range(n)]}


def send_body(batch, message_id):
    return {
        "message": {"messageId": message_id, "role": "ROLE_USER",
                    "parts": [{"mediaType": q10_a2a.MODE_BATCH, "data": batch}]},
        "configuration": {"returnImmediately": False, "historyLength": 20,
                          "acceptedOutputModes": [q10_a2a.MODE_PROPOSALS,
                                                  q10_a2a.MODE_RECEIPTS]},
    }


# ---------------------------------------------------------------- fake LLM

CALLS = {"n": 0}
EXPECTED = {"clean": "settle_invoice", "authority": "request_approval",
            "hold": "hold_invoice", "duplicate": "reject_duplicate",
            "conflict": "open_exception"}


async def fake_chat_json(messages, **kwargs):
    CALLS["n"] += 1
    user = messages[-1]["content"]
    proposals = []
    for block in user.split("===== PACKAGE ")[1:]:
        pid = block.split("packageId=")[1].split(" ")[0]
        kind = KINDS[int(pid.split("-")[1]) % len(KINDS)]
        inv = [w.strip(".,") for w in block.split() if w.startswith("INV-")][0]
        proposals.append({
            "packageId": pid, "action": EXPECTED[kind],
            "facts": {"vendorName": "Test Vendor", "invoiceNumber": inv,
                      "amountMinor": 1234050, "currency": "INR"},
            "evidenceRefs": [inv, f"DOC-{pid}-01"],
            "rationale": (f"Chose {EXPECTED[kind]} because {inv} in DOC-{pid}-01 is decisive "
                          f"and the surrounding policy text confirms it beyond doubt here."),
        })
    return {"proposals": proposals}


q10_a2a.chat_json = fake_chat_json


def sent_task(resp):
    """Unwrap a message:send response, asserting the envelope is exactly right.

    Deliberately indexes with [...] and never .get(...,{}): an assertion that
    can still pass on an empty payload is not an assertion.
    """
    body = resp.json()
    assert set(body) == {"task"}, f"send envelope must be exactly {{'task'}}, got {sorted(body)}"
    task = body["task"]
    assert isinstance(task, dict) and task["id"] and task["contextId"], "empty Task in envelope"
    assert task["status"]["state"], "Task carries no state"
    return task


def get_artifact(task, media_type):
    out = []
    for art in task.get("artifacts") or []:
        for p in art.get("parts") or []:
            if p.get("mediaType") == media_type:
                out.append(p["data"])
    return out


# ------------------------------------------------------------- agent card

card = client.get("/.well-known/agent-card.json").json()
check("card: nonempty name/description/version",
      all(isinstance(card.get(k), str) and card[k].strip()
          for k in ("name", "description", "version")))
check("card: capabilities is an object", isinstance(card.get("capabilities"), dict))
skill = next((s for s in card.get("skills", []) if s.get("id") == "invoice_action_agent"), None)
check("card: invoice_action_agent skill present", skill is not None)
check("card: skill name/description/tags nonempty",
      bool(skill and skill.get("name") and skill.get("description") and skill.get("tags")))
check("card: supportedInterfaces has exact base URL + binding",
      any(i.get("url") == BASE and i.get("protocolBinding") == "HTTP+JSON"
          and i.get("protocolVersion") == "1.0"
          for i in card.get("supportedInterfaces", [])), json.dumps(card.get("supportedInterfaces")))
check("card: defaultInputModes has claim-batch", q10_a2a.MODE_BATCH in card["defaultInputModes"])
check("card: defaultOutputModes has both output modes",
      q10_a2a.MODE_PROPOSALS in card["defaultOutputModes"]
      and q10_a2a.MODE_RECEIPTS in card["defaultOutputModes"])
check("card: public (no auth needed)", client.get("/.well-known/agent-card.json").status_code == 200)

# ------------------------------------------------------------ auth/version

body = send_body(make_batch(), "m-auth")
check("401 without Authorization",
      client.post("/a2a/message:send", json=body, headers=H).status_code == 401)
check("401 with non-Bearer scheme",
      client.post("/a2a/message:send", json=body,
                  headers=dict(H, Authorization="Basic xyz")).status_code == 401)
check("401 on GET /a2a/tasks without auth",
      client.get("/a2a/tasks", headers={"A2A-Version": "1.0"}).status_code == 401)
r = client.post("/a2a/message:send", json=body,
                headers=dict(ALICE, **{"A2A-Version": "2.0"}))
check("400 on wrong A2A-Version", r.status_code == 400, r.text[:120])
r = client.get("/a2a/tasks", headers={"Authorization": "Bearer alice-token"})
check("400 when A2A-Version missing", r.status_code == 400, r.text[:120])

# ---------------------------------------------------------- happy path

CALLS["n"] = 0
r = client.post("/a2a/message:send", json=send_body(make_batch(), "m-1"), headers=ALICE)
check("send -> 200", r.status_code == 200, r.text[:200])
_body = r.json()
check("send response top-level keys are exactly {'task'}", set(_body) == {"task"},
      str(sorted(_body)))
check("send envelope wraps a real Task, not an empty object",
      isinstance(_body.get("task"), dict) and bool(_body["task"].get("id"))
      and bool(_body["task"].get("status", {}).get("state")),
      json.dumps(_body)[:200])
task = sent_task(r)
check("state INPUT_REQUIRED", task["status"]["state"] == "TASK_STATE_INPUT_REQUIRED",
      task["status"]["state"])
props_arts = get_artifact(task, q10_a2a.MODE_PROPOSALS)
check("exactly one proposals artifact part", len(props_arts) == 1)
check("no receipts artifact yet", len(get_artifact(task, q10_a2a.MODE_RECEIPTS)) == 0)
props = props_arts[0]["proposals"]
check("12 proposals", len(props) == 12, str(len(props)))
_read = client.get(f"/a2a/tasks/{task['id']}", headers=ALICE).json()
check("task read returns a BARE Task (not wrapped in {'task'})",
      "task" not in _read and _read["id"] == task["id"], str(sorted(_read))[:160])
_list = client.get("/a2a/tasks", headers=ALICE).json()
check("list returns {'tasks': [...]} with real Tasks",
      set(_list) == {"tasks"} and isinstance(_list["tasks"], list)
      and all(t["id"] and t["status"]["state"] for t in _list["tasks"]),
      str(sorted(_list))[:160])
check("initial message preserved in history",
      any(m.get("messageId") == "m-1" and m.get("role") == "ROLE_USER"
          for m in task["history"]))
check("unique packageIds and actionIds",
      len({p["packageId"] for p in props}) == 12
      and len({p["actionId"] for p in props}) == 12)
check("all actions in the enum",
      all(p["action"] in q10_a2a.ACTIONS for p in props))
check("actions are macro-balanced (not blanket)",
      len({p["action"] for p in props}) >= 4,
      str(sorted({p["action"] for p in props})))
check("facts shape (amountMinor int, currency str)",
      all(isinstance(p["facts"]["amountMinor"], int)
          and isinstance(p["facts"]["currency"], str)
          and p["facts"]["vendorName"] and p["facts"]["invoiceNumber"] for p in props))
check("rationale 60-1500 chars",
      all(60 <= len(p["rationale"]) <= 1500 for p in props),
      str(sorted(len(p["rationale"]) for p in props)[:3]))
check("rationale names the action and cites >=2 refs",
      all(p["action"] in p["rationale"]
          and sum(1 for r in p["evidenceRefs"] if r in p["rationale"]) >= 2
          for p in props))
batch = make_batch()
texts = {p["packageId"]: q10_a2a.pkg_text(p) for p in batch["packages"]}
check("evidenceRefs are verbatim substrings of the source",
      all(all(ref in texts[p["packageId"]] for ref in p["evidenceRefs"]) for p in props))
check("semantic accuracy vs expected actions",
      all(p["action"] == EXPECTED[KINDS[int(p["packageId"].split("-")[1]) % len(KINDS)]]
          for p in props))
check("one model call for the whole batch", CALLS["n"] == 1, str(CALLS["n"]))

TASK_ID, CTX_ID = task["id"], task["contextId"]

# ------------------------------------------------- rationale repair path

bad = q10_a2a.normalise_decision(
    {"action": "settle_invoice", "facts": {"vendorName": "V", "invoiceNumber": "INV-PKG-00-77",
                                           "amountMinor": "12,340.50", "currency": "inr"},
     "evidenceRefs": ["INV-PKG-00-77", "NOT-IN-DOCS-XYZ"], "rationale": "too short"},
    batch["packages"][0], texts["PKG-00"])
check("repair: short rationale grown into 60-1500", 60 <= len(bad["rationale"]) <= 1500,
      str(len(bad["rationale"])))
check("repair: fabricated evidence ref dropped", "NOT-IN-DOCS-XYZ" not in bad["evidenceRefs"])
check("repair: >=2 verbatim refs recovered",
      len(bad["evidenceRefs"]) >= 2 and all(r in texts["PKG-00"] for r in bad["evidenceRefs"]))
long_rat = q10_a2a.repair_rationale("x" * 4000, "hold_invoice", ["A", "B"],
                                    {"vendorName": "v", "invoiceNumber": "i",
                                     "amountMinor": 1, "currency": "INR"})
check("repair: over-long rationale clipped to <=1500", len(long_rat) <= 1500, str(len(long_rat)))
check("repair: decimal string amount rescaled to minor units",
      bad["facts"]["amountMinor"] == 1234050, str(bad["facts"]["amountMinor"]))
check("repair: integer amountMinor left alone",
      q10_a2a.coerce_minor(123456, 0) == 123456
      and q10_a2a.coerce_minor("5000", 0) == 5000
      and q10_a2a.coerce_minor(1234.5, 0) == 123450)
check("repair: currency uppercased", bad["facts"]["currency"] == "INR")

# -------------------------------------------------------- idempotency

CALLS["n"] = 0
r2 = client.post("/a2a/message:send", json=send_body(make_batch(), "m-1"), headers=ALICE)
check("identical resend -> same task id", sent_task(r2)["id"] == TASK_ID)
check("identical resend -> byte-identical task", sent_task(r2) == task)

reordered = send_body(make_batch(), "m-1")
reordered["message"] = json.loads(json.dumps(reordered["message"], sort_keys=True))
reordered["configuration"] = {"acceptedOutputModes": [], "returnImmediately": True,
                              "historyLength": 3}
r3 = client.post("/a2a/message:send", json=reordered, headers=ALICE)
check("reordered keys + flipped returnImmediately -> same task", sent_task(r3) == task)
check("replays made zero model calls", CALLS["n"] == 0, str(CALLS["n"]))

changed = send_body(make_batch("BATCH-CHANGED"), "m-1")
r4 = client.post("/a2a/message:send", json=changed, headers=ALICE)
check("same messageId + changed content -> 409", r4.status_code == 409, r4.text[:120])
check("409 carries IDEMPOTENCY_CONFLICT", "IDEMPOTENCY_CONFLICT" in r4.text, r4.text[:200])
check("conflict did not mutate the original",
      client.get(f"/a2a/tasks/{TASK_ID}", headers=ALICE).json() == task)

CALLS["n"] = 0
same_pkgs = client.post("/a2a/message:send",
                        json=send_body(make_batch("BATCH-2"), "m-new"), headers=ALICE)
check("new task with same packages -> 200", same_pkgs.status_code == 200)
check("package cache makes a fresh identical batch free", CALLS["n"] == 0, str(CALLS["n"]))
OTHER_TASK = sent_task(same_pkgs)["id"]
check("different batch -> different task id", OTHER_TASK != TASK_ID)

# ---------------------------------------------------------- tenant safety

check("cross-principal GET -> 404", client.get(f"/a2a/tasks/{TASK_ID}", headers=BOB).status_code == 404)
missing = client.get(f"/a2a/tasks/task_{uuid.uuid4().hex}", headers=BOB)
check("unknown id and foreign id are indistinguishable",
      missing.status_code == 404 and missing.json() == client.get(
          f"/a2a/tasks/{TASK_ID}", headers=BOB).json(), missing.text[:120])
check("cross-principal 404 body leaks no id", TASK_ID not in
      client.get(f"/a2a/tasks/{TASK_ID}", headers=BOB).text)
bob_list = client.get("/a2a/tasks", headers=BOB).json()["tasks"]
check("cross-principal list is empty", bob_list == [], str(len(bob_list)))
check("cross-principal cancel -> 404",
      client.post(f"/a2a/tasks/{TASK_ID}:cancel", headers=BOB).status_code == 404)
alice_list = client.get("/a2a/tasks", headers=ALICE).json()["tasks"]
check("owner list returns own tasks only",
      {t["id"] for t in alice_list} == {TASK_ID, OTHER_TASK}, str(len(alice_list)))


def cont_body(msg_id, results, task_id=TASK_ID, ctx=CTX_ID, batch_id="BATCH-1"):
    return {"message": {"messageId": msg_id, "taskId": task_id, "contextId": ctx,
                        "role": "ROLE_USER",
                        "parts": [{"mediaType": q10_a2a.MODE_RESULTS,
                                   "data": {"batchId": batch_id, "results": results}}]}}


def results_for(props, accept_first=8):
    out = []
    for i, p in enumerate(props):
        out.append({"packageId": p["packageId"], "actionId": p["actionId"],
                    "action": p["action"],
                    "outcome": "ACCEPTED" if i < accept_first else "REJECTED",
                    "receiptNonce": f"nonce-{uuid.uuid4().hex[:12]}"})
    return out


# ------------------------------------------------- continuation rejection

RES = results_for(props)
bad_action_id = copy.deepcopy(RES)
bad_action_id[0]["actionId"] = "act_forged"
r = client.post("/a2a/message:send", json=cont_body("c-bad1", bad_action_id), headers=ALICE)
check("mismatched actionId rejected", r.status_code == 400 and "ACTION_ID_MISMATCH" in r.text,
      r.text[:150])

bad_action = copy.deepcopy(RES)
bad_action[0]["action"] = "settle_invoice" if bad_action[0]["action"] != "settle_invoice" else "hold_invoice"
r = client.post("/a2a/message:send", json=cont_body("c-bad2", bad_action), headers=ALICE)
check("changed action rejected", r.status_code == 400 and "ACTION_MISMATCH" in r.text, r.text[:150])

r = client.post("/a2a/message:send", json=cont_body("c-bad3", RES, batch_id="WRONG"), headers=ALICE)
check("mismatched batchId rejected", r.status_code == 400 and "BATCH_MISMATCH" in r.text, r.text[:150])

r = client.post("/a2a/message:send", json=cont_body("c-bad4", RES, ctx="ctx_wrong"), headers=ALICE)
check("mismatched contextId rejected", r.status_code == 400, r.text[:150])

bad_pkg = copy.deepcopy(RES)
bad_pkg[0]["packageId"] = "PKG-ZZ"
r = client.post("/a2a/message:send", json=cont_body("c-bad5", bad_pkg), headers=ALICE)
check("unknown packageId rejected", r.status_code == 400 and "PACKAGE_MISMATCH" in r.text,
      r.text[:150])

r = client.post("/a2a/message:send", json=cont_body("c-bad6", RES), headers=BOB)
check("cross-principal continuation -> 404", r.status_code == 404, r.text[:150])

check("task still INPUT_REQUIRED after rejected continuations",
      client.get(f"/a2a/tasks/{TASK_ID}", headers=ALICE).json()["status"]["state"]
      == "TASK_STATE_INPUT_REQUIRED")

# ------------------------------------------------------ valid continuation

CALLS["n"] = 0
r = client.post("/a2a/message:send", json=cont_body("c-ok", RES), headers=ALICE)
check("valid continuation -> 200", r.status_code == 200, r.text[:200])
done = sent_task(r)
check("state COMPLETED", done["status"]["state"] == "TASK_STATE_COMPLETED",
      done["status"]["state"])
check("proposals artifact kept", len(get_artifact(done, q10_a2a.MODE_PROPOSALS)) == 1)
receipts = get_artifact(done, q10_a2a.MODE_RECEIPTS)
check("exactly one receipts artifact part", len(receipts) == 1)
execs = receipts[0]["executions"]
check("executions contain accepted results only", len(execs) == 8, str(len(execs)))
accepted_ids = {r_["packageId"] for r_ in RES if r_["outcome"] == "ACCEPTED"}
rejected_ids = {r_["packageId"] for r_ in RES if r_["outcome"] == "REJECTED"}
check("no rejected package executed",
      {e["packageId"] for e in execs} == accepted_ids
      and not ({e["packageId"] for e in execs} & rejected_ids))
by_id = {p["packageId"]: p for p in props}
nonces = {r_["packageId"]: r_["receiptNonce"] for r_ in RES}
check("each execution binds proposal + grader nonce exactly",
      all(e["actionId"] == by_id[e["packageId"]]["actionId"]
          and e["action"] == by_id[e["packageId"]]["action"]
          and e["facts"] == by_id[e["packageId"]]["facts"]
          and e["evidenceRefs"] == by_id[e["packageId"]]["evidenceRefs"]
          and e["receiptNonce"] == nonces[e["packageId"]] for e in execs))
check("continuation recorded in history",
      any(m.get("messageId") == "c-ok" for m in done["history"]))
check("rejected proposals still visible in history",
      any(any(p.get("data", {}).get("results") for p in m.get("parts", [])
              if isinstance(p, dict))
          for m in done["history"] if m.get("messageId") == "c-ok"))
check("continuation made zero model calls", CALLS["n"] == 0, str(CALLS["n"]))
check("lifecycle reached COMPLETED via INPUT_REQUIRED",
      done["status"]["state"] == "TASK_STATE_COMPLETED"
      and len(done["artifacts"]) == 2)

# --------------------------------------------------------- immutability

r = client.post("/a2a/message:send", json=cont_body("c-ok", RES), headers=ALICE)
check("replayed continuation -> same completed task",
      r.status_code == 200 and sent_task(r) == done,
      r.text[:150])
r = client.post("/a2a/message:send", json=cont_body("c-ok2", results_for(props, 12)), headers=ALICE)
check("second different continuation rejected", r.status_code == 409, r.text[:150])
check("completed task unchanged",
      client.get(f"/a2a/tasks/{TASK_ID}", headers=ALICE).json() == done)
r = client.post(f"/a2a/tasks/{TASK_ID}:cancel", headers=ALICE)
check("cancel after COMPLETED -> 409", r.status_code == 409, r.text[:150])
check("cancel race never produced both", (
    client.get(f"/a2a/tasks/{TASK_ID}", headers=ALICE).json()["status"]["state"]
    == "TASK_STATE_COMPLETED") and len(get_artifact(done, q10_a2a.MODE_RECEIPTS)) == 1)

# ------------------------------------------------------------- cancellation

r = client.post(f"/a2a/tasks/{OTHER_TASK}:cancel", headers=ALICE)
check("cancel from nonterminal -> 200", r.status_code == 200, r.text[:150])
canceled = r.json()
check("cancel returns a BARE Task (not wrapped in {'task'})",
      "task" not in canceled and bool(canceled["id"]) and bool(canceled["status"]["state"]),
      str(sorted(canceled))[:160])
check("state CANCELED", canceled["status"]["state"] == "TASK_STATE_CANCELED")
check("canceled task has no receipts artifact",
      len(get_artifact(canceled, q10_a2a.MODE_RECEIPTS)) == 0)
r = client.post("/a2a/message:send",
                json=cont_body("c-after-cancel", RES, task_id=OTHER_TASK,
                               ctx=canceled["contextId"], batch_id="BATCH-2"),
                headers=ALICE)
check("continuation after cancel rejected as terminal",
      r.status_code == 409 and "TASK_TERMINAL" in r.text, r.text[:150])
check("second cancel -> 409",
      client.post(f"/a2a/tasks/{OTHER_TASK}:cancel", headers=ALICE).status_code == 409)

# ---------------------------------------------------------- schema guards

r = client.post("/a2a/message:send",
                json={"message": {"messageId": "m-bad", "role": "ROLE_USER",
                                  "parts": [{"mediaType": q10_a2a.MODE_BATCH,
                                             "data": {"batchId": "B", "packages": []}}]}},
                headers=ALICE)
check("empty packages -> 422", r.status_code == 422, r.text[:150])
r = client.post("/a2a/message:send", json={"message": {"role": "ROLE_USER", "parts": []}},
                headers=ALICE)
check("missing messageId -> 400", r.status_code == 400, r.text[:150])
r = client.post("/a2a/message:send",
                json=cont_body("c-orphan", RES, task_id="task_doesnotexist"), headers=ALICE)
check("continuation for unknown task -> 404", r.status_code == 404, r.text[:150])

# ------------------------------------------------------------ persistence

q10_a2a._conn = None  # simulate a process restart against the same DB file
reloaded = client.get(f"/a2a/tasks/{TASK_ID}", headers=ALICE)
check("task survives a fresh DB connection (persisted, not in-memory)",
      reloaded.status_code == 200 and reloaded.json() == done, reloaded.text[:150])

# ------------------------------------------------- model outage fallback

import llm  # noqa: E402


async def dead_chat_json(messages, **kwargs):
    CALLS["n"] += 1
    raise llm.LLMUnavailable("401: token expired")


q10_a2a.chat_json = dead_chat_json
CALLS["n"] = 0
r = client.post("/a2a/message:send",
                json=send_body(make_batch("BATCH-OUT", prefix="OUT"), "m-outage"),
                headers=ALICE)
check("model outage still returns 200 (never 500)", r.status_code == 200, r.text[:200])
outage = sent_task(r)
check("outage: task reaches INPUT_REQUIRED",
      outage["status"]["state"] == "TASK_STATE_INPUT_REQUIRED", outage["status"]["state"])
oprops = get_artifact(outage, q10_a2a.MODE_PROPOSALS)[0]["proposals"]
check("outage: all 12 packages still proposed", len(oprops) == 12, str(len(oprops)))
check("outage: every action is a valid enum member",
      all(p["action"] in q10_a2a.ACTIONS for p in oprops))
check("outage: NEVER blindly settles",
      all(p["action"] != "settle_invoice" for p in oprops),
      str(sorted({p["action"] for p in oprops})))
otexts = {p["packageId"]: q10_a2a.pkg_text(p)
          for p in make_batch("BATCH-OUT", prefix="OUT")["packages"]}
check("outage: evidence refs still verbatim and >=2",
      all(len(p["evidenceRefs"]) >= 2
          and all(ref in otexts[p["packageId"]] for ref in p["evidenceRefs"])
          for p in oprops))
check("outage: rationales still 60-1500 and name the action",
      all(60 <= len(p["rationale"]) <= 1500 and p["action"] in p["rationale"]
          for p in oprops))
check("outage: facts still schema-valid",
      all(isinstance(p["facts"]["amountMinor"], int) and p["facts"]["currency"]
          and p["facts"]["invoiceNumber"] for p in oprops))
check("outage: conservative actions still discriminate, not one blanket value",
      len({p["action"] for p in oprops}) >= 2, str(sorted({p["action"] for p in oprops})))
oid = outage["id"]
ores = [{"packageId": p["packageId"], "actionId": p["actionId"], "action": p["action"],
         "outcome": "ACCEPTED", "receiptNonce": f"n-{i}"} for i, p in enumerate(oprops)]
r = client.post("/a2a/message:send",
                json=cont_body("c-outage", ores, task_id=oid,
                               ctx=outage["contextId"], batch_id="BATCH-OUT"),
                headers=ALICE)
check("outage: receipt lifecycle still completes",
      r.status_code == 200 and sent_task(r)["status"]["state"] == "TASK_STATE_COMPLETED",
      r.text[:150])
check("outage: receipts artifact still exact",
      len(get_artifact(sent_task(r), q10_a2a.MODE_RECEIPTS)[0]["executions"]) == 12)
q10_a2a.chat_json = fake_chat_json

# --------------------------------------------------- concurrent duplicates

import asyncio  # noqa: E402

import httpx  # noqa: E402


async def _concurrent():
    slow = q10_a2a.chat_json

    async def slower(messages, **kwargs):
        await asyncio.sleep(0.2)          # widen the race window
        return await slow(messages, **kwargs)

    q10_a2a.chat_json = slower
    CALLS["n"] = 0
    fresh = make_batch("BATCH-RACE", prefix="RACE")   # never seen by the cache
    body_a = send_body(fresh, "m-race")
    body_b = send_body(copy.deepcopy(fresh), "m-race")
    body_b["configuration"] = {"returnImmediately": True}   # ignored semantically
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://t") as ac:
        return await asyncio.gather(*[
            ac.post("/a2a/message:send", json=b, headers=ALICE)
            for b in (body_a, body_b, body_a, body_b, body_a)
        ])


races = asyncio.run(_concurrent())
check("concurrent duplicates all 200", all(x.status_code == 200 for x in races),
      str([x.status_code for x in races]))
check("concurrent duplicates return one identical task",
      len({json.dumps(x.json(), sort_keys=True) for x in races}) == 1,
      str({x.json().get("id") for x in races}))
check("concurrent duplicates invoked the model once", CALLS["n"] == 1, str(CALLS["n"]))
q10_a2a.chat_json = fake_chat_json

# ------------------------------------------------------ live model sanity

print("\n-- live model check --")
try:
    import asyncio

    import llm

    if not llm.available():
        print("  skipped: no AIPIPE_TOKEN/LLM_API_KEY configured")
    else:
        q10_a2a.chat_json = llm.chat_json
        live_pkgs = [make_package(f"LIVE-{i:02d}", k) for i, k in enumerate(KINDS)]
        got = asyncio.run(q10_a2a.decide_packages(live_pkgs, "BATCH-LIVE", "R-4.2"))
        hits = 0
        for pkg, kind, d in zip(live_pkgs, KINDS, got):
            ok = d["action"] == EXPECTED[kind]
            hits += ok
            print(f"  {pkg['packageId']} expected={EXPECTED[kind]:<16} got={d['action']:<16}"
                  f" {'ok' if ok else 'MISS'}  refs={d['evidenceRefs']}")
        text0 = q10_a2a.pkg_text(live_pkgs[0])
        check("live: evidence refs verbatim",
              all(r in q10_a2a.pkg_text(p) for p, d in zip(live_pkgs, got)
                  for r in d["evidenceRefs"]))
        check("live: rationale length valid",
              all(60 <= len(d["rationale"]) <= 1500 for d in got))
        check("live: >=4/5 semantic actions correct", hits >= 4, f"{hits}/5")
except Exception as exc:  # a provider outage must not fail the suite silently
    print(f"  live check error: {type(exc).__name__}: {exc}")
    FAIL.append("live model check")

print(f"\n{len(PASS)} passed, {len(FAIL)} failed")
if FAIL:
    print("failed:", FAIL)
sys.exit(1 if FAIL else 0)
