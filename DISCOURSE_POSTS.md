# GA5 Discourse posts — ready to paste

Two blockers that appear to be grader-side. Both posts are evidence-first (not complaints),
which is the tone most likely to get a useful answer.

---

## POST 1 — Q11 (q-agent-trace-integrity-server): grader never posts receipts

**Title:** GA5 Q11 Incident-Response — grader never POSTs to /v2/incidents/{runId}/receipts

My deployed incident agent returns a valid `status:"waiting"` turn-1 response on every
`POST /v2/incidents`:
- `diagnosis.rootCause` ∈ `allowedRootCauses`, with 2 real evidence IDs
- one-to-three `dispatches`, each a catalog tool, arguments satisfying every
  `inputSchema.required`, `phase:"diagnostic"`, `attempt:1`, and a `traceparent` whose span ID
  matches a CLIENT span in my OTLP
- the two validation probes answer correctly (unsupported profile → 422, same runId + changed
  content → 409)

But across **every** Check/Save since 2026-07-20, my server access logs show the grader only
ever hits two paths:
```
GET  /v2/incidents/{runId}     (existence pre-check)
POST /v2/incidents             (creates the run, gets my waiting+dispatches response)
```
There has **never** been a single `POST /v2/incidents/{runId}/receipts`. A full verification is
exactly 7 `POST /v2/incidents` (6 stable + 1 fresh audit) followed by the 422 and 409 probes,
then it stops. I confirmed this holds whether the runs are brand-new (GET → 404) or already
persisted from a prior Check (GET → 200), and with both the trimmed 5-key waiting response and
the full envelope.

Since the score is capped at 0 by "if the grader observes no valid fresh action attempt, the
score is zero," and the only way an action is observed is the receipt round-trip, I'm stuck at
0/4 despite a well-formed turn-1. **Is there a precondition that gates the receipt phase, or is
the receipt transport not firing for this question?** Happy to share a runId + timestamp.

**Additional evidence (update):**
- The Check response's category breakdown is `proposal 0/7, semantics 0/7, topology 0-1/7,
  correlation 0/7, lifecycle 4/7, durability 0/7, redaction 7/7`. The non-zero **redaction 7/7 and
  lifecycle 4/7 prove the grader does parse and score my turn-1 output** — so this is not a
  total-reject/unreachable-endpoint case. The zeroed categories are exactly the ones that can only
  be earned after the receipt round-trip (proposal confirmation, action semantics, correlation,
  durable terminal state).
- I verified my receipt endpoint end-to-end from an external client through the same public URL:
  `POST /v2/incidents` → take the returned `dispatches` → `POST /v2/incidents/{runId}/receipts` with
  matching `outcomes` returns **HTTP 200** and correctly advances the run to the approval/effect
  stage, and that request **is** recorded in my access logs. So the endpoint, routing, and lifecycle
  all work — the grader simply never sends the receipt during Check/Save.
- The spec says Check "replays one identical audit receipt", but no receipt POST (original or replay)
  ever appears. This is the crux: the documented receipt phase does not initiate for my submission.

---

## POST 2 — Q9 (q-taint-aware-agent-executor-server): only send_approved_notice is ever exact

**Title:** GA5 Q9 Mailroom — only send_approved_notice scores exact; other five archetypes never accepted

My mailroom agent passes every engineering category (`details` from the grader:
`shapeErrors:0, replayPassed, commitReplayPassed, stableCorePassed, conflictPassed,
receiptValidationPassed, unsafe:false`), so the whole remaining score is dossier exactness.

Reading the per-dossier `receipts[].accepted` from the commit request, **only
`send_approved_notice` is ever accepted (13/13)**; `create_draft`, `update_internal_record`,
`request_confirmation`, `quarantine_item`, and `no_action` are 0-accepted across every run.

For the accepted archetype I confirmed the rule by a controlled experiment: its evidence must be
**exactly** the minimal set of lines that supply every emitted value — dropping a line or adding
one flips it to rejected. I applied that same rule faithfully to the other five (frozen schema,
verbatim values, minimal covering evidence, public order id rather than the internal case id),
and they stay rejected.

`quarantine_item` is the clearest case: its target and reasonCode are frozen constants and the
only free value is `artifactId`, yet it is rejected for **every** combination of
`artifactId ∈ {ATT-id, sourceId, artifact lineId, injection lineId}` and evidence ∈ eight sets I
tried (including the signed "Untrusted-content rule" policy line). Since there is almost nothing
to construct, this looks like the grader's expected **action** differs from mine — even though
the operative clause and the action definitions make quarantine look correct.

**Is the intended action for these archetypes different from the obvious reading (e.g. a
lethal-trifecta trap where the safe answer is request_confirmation/no_action), or am I missing a
value rule?** The feedback line only says "improve semantic action choice, minimal
arguments/evidence" without a category breakdown.
