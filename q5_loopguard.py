"""Q5 - Agent Harness: Run Budget & Loop Guard.

Stateless policy engine. Given a token budget and the ordered history of steps
already executed this run, decide whether the agent may take its next step.

Two independent halt conditions:
  1. budget: sum(tokens_used) >= budget_tokens
  2. loop:   3+ identical trailing calls, or a 2-step A/B cycle covering 6+
             trailing steps

Args are canonicalized before comparison: key order ignored, whitespace inside
string values normalized, and any field named ``request_id`` dropped -- all
recursively, at every nesting depth.
"""

import json
import re
from typing import Any

from fastapi import APIRouter

router = APIRouter()

_WS = re.compile(r"\s+")

# Trailing identical calls needed before we call it a loop. Two is not enough.
_REPEAT_THRESHOLD = 3
# Trailing steps an A/B/A/B alternation must cover before we call it a loop.
_CYCLE_THRESHOLD = 6


def _to_int(value: Any) -> int:
    """Best-effort int coercion; anything unusable counts as 0."""
    if isinstance(value, bool) or value is None:
        return 0
    try:
        return int(value)
    except (TypeError, ValueError):
        try:
            return int(float(value))
        except (TypeError, ValueError):
            return 0


def canonicalize(value: Any) -> Any:
    """Recursively strip cosmetic differences from a JSON-ish value."""
    if isinstance(value, dict):
        out = {}
        for key, item in value.items():
            name = str(key)
            if name.strip() == "request_id":
                continue
            out[name] = canonicalize(item)
        return {k: out[k] for k in sorted(out)}
    if isinstance(value, (list, tuple)):
        return [canonicalize(item) for item in value]
    if isinstance(value, str):
        return _WS.sub(" ", value).strip()
    return value


def step_key(step: Any) -> str:
    """Canonical identity of a step: its tool plus its meaningful args."""
    if not isinstance(step, dict):
        step = {}
    tool = step.get("tool")
    tool = _WS.sub(" ", str(tool if tool is not None else "")).strip()
    args = step.get("args")
    if args is None:
        args = {}
    return json.dumps(
        {"tool": tool, "args": canonicalize(args)},
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )


def _trailing_repeat(keys: list) -> int:
    """How many consecutive steps at the end of the run share one identity."""
    if not keys:
        return 0
    last = keys[-1]
    count = 0
    for key in reversed(keys):
        if key != last:
            break
        count += 1
    return count


def _trailing_cycle(keys: list) -> int:
    """Length of the trailing A/B/A/B alternation between two distinct states."""
    if len(keys) < 2 or keys[-1] == keys[-2]:
        return 0
    length = 2
    for i in range(len(keys) - 3, -1, -1):
        if keys[i] != keys[i + 2]:
            break
        length += 1
    return length


def evaluate(payload: Any) -> dict:
    """Return the {decision, reason} verdict for one request body."""
    if not isinstance(payload, dict):
        payload = {}

    budget = _to_int(payload.get("budget_tokens"))

    raw_steps = payload.get("steps")
    steps = [s for s in raw_steps if isinstance(s, dict)] if isinstance(raw_steps, list) else []

    # Budget first: the run has spent its fuel regardless of what it was doing.
    used = sum(_to_int(s.get("tokens_used")) for s in steps)
    if budget > 0 and used >= budget:
        return {
            "decision": "halt",
            "reason": f"Cumulative tokens_used ({used}) has reached the budget ({budget}).",
        }

    if not steps:
        return {
            "decision": "continue",
            "reason": "No steps taken yet; fresh run is within budget.",
        }

    keys = [step_key(s) for s in steps]

    repeat = _trailing_repeat(keys)
    if repeat >= _REPEAT_THRESHOLD:
        tool = steps[-1].get("tool") or "the same tool"
        return {
            "decision": "halt",
            "reason": (
                f"Loop detected: '{tool}' called {repeat} times in a row with "
                "functionally identical args (ignoring key order, whitespace and request_id)."
            ),
        }

    cycle = _trailing_cycle(keys)
    if cycle >= _CYCLE_THRESHOLD:
        first = steps[-2].get("tool") or "A"
        second = steps[-1].get("tool") or "B"
        return {
            "decision": "halt",
            "reason": (
                f"Loop detected: 2-step cycle ({first} -> {second}) repeating "
                f"across the last {cycle} steps with no progress."
            ),
        }

    remaining = budget - used
    return {
        "decision": "continue",
        "reason": (
            f"Under budget ({used}/{budget} tokens used, {remaining} left) and no "
            "repeat or cycle in the trailing steps; the run is making progress."
        ),
    }


@router.post("/q5/check")
async def check(body: dict) -> dict:
    return evaluate(body)
