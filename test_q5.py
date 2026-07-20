"""Probe-by-probe tests for q5_loopguard, one per grader category."""

from q5_loopguard import evaluate

BUDGET = 34000


def step(n, tool, args, tokens=100):
    return {"step_number": n, "tool": tool, "args": args, "tokens_used": tokens}


CASES = []


def case(name, payload, expected):
    CASES.append((name, payload, expected))


# --- budget probes -----------------------------------------------------------
case(
    "budget-exactly-at-boundary",
    {"budget_tokens": 20000, "steps": [
        step(1, "fetch_page", {"url": "https://example.com/1"}, 9000),
        step(2, "summarize", {"text": "..."}, 6000),
        step(3, "fetch_page", {"url": "https://example.com/2"}, 5000),
    ]},
    "halt",
)
case(
    "budget-one-below-boundary",
    {"budget_tokens": 20000, "steps": [
        step(1, "fetch_page", {"url": "https://example.com/1"}, 9000),
        step(2, "summarize", {"text": "..."}, 6000),
        step(3, "fetch_page", {"url": "https://example.com/2"}, 4999),
    ]},
    "continue",
)
case(
    "budget-crossed-partway-by-modest-steps",
    {"budget_tokens": 5000, "steps": [
        step(i, f"tool_{i}", {"i": i}, 900) for i in range(1, 7)
    ]},
    "halt",
)

# --- repeat probes -----------------------------------------------------------
case(
    "three-identical-in-a-row",
    {"budget_tokens": BUDGET, "steps": [
        step(1, "search", {"q": "python"}),
        step(2, "search", {"q": "python"}),
        step(3, "search", {"q": "python"}),
    ]},
    "halt",
)
case(
    "exactly-two-identical-in-a-row",
    {"budget_tokens": BUDGET, "steps": [
        step(1, "search", {"q": "python"}),
        step(2, "search", {"q": "python"}),
    ]},
    "continue",
)
case(
    "cosmetic-diff-key-order",
    {"budget_tokens": BUDGET, "steps": [
        step(1, "search", {"q": "python", "limit": 10, "safe": True}),
        step(2, "search", {"limit": 10, "safe": True, "q": "python"}),
        step(3, "search", {"safe": True, "q": "python", "limit": 10}),
    ]},
    "halt",
)
case(
    "cosmetic-diff-request-id-nested",
    {"budget_tokens": BUDGET, "steps": [
        step(1, "search", {"request_id": "a1", "q": "python",
                           "opts": {"request_id": "n1", "deep": True}}),
        step(2, "search", {"request_id": "b2", "q": "python",
                           "opts": {"request_id": "n2", "deep": True}}),
        step(3, "search", {"request_id": "c3", "q": "python",
                           "opts": {"request_id": "n3", "deep": True}}),
    ]},
    "halt",
)
case(
    "cosmetic-diff-whitespace-nested",
    {"budget_tokens": BUDGET, "steps": [
        step(1, "write_file", {"path": "a.txt",
                               "body": {"text": "hello world", "tags": ["one two"]}}),
        step(2, "write_file", {"path": " a.txt ",
                               "body": {"text": "hello   world", "tags": ["one  two"]}}),
        step(3, "write_file", {"path": "a.txt\n",
                               "body": {"text": "hello\tworld\n", "tags": ["one\ntwo"]}}),
    ]},
    "halt",
)

# --- cycle probe -------------------------------------------------------------
case(
    "six-step-alternating-cycle",
    {"budget_tokens": BUDGET, "steps": [
        step(1, "read_file", {"path": "a.py"}),
        step(2, "run_tests", {"suite": "unit"}),
        step(3, "read_file", {"path": "a.py"}),
        step(4, "run_tests", {"suite": "unit"}),
        step(5, "read_file", {"path": "a.py"}),
        step(6, "run_tests", {"suite": "unit"}),
    ]},
    "halt",
)

# --- legitimate-progress probes ---------------------------------------------
case(
    "legitimate-pagination-continue",
    {"budget_tokens": 20000, "steps": [
        step(1, "list_items", {"page": 1}, 1000),
        step(2, "list_items", {"page": 2}, 1000),
        step(3, "list_items", {"page": 3}, 1000),
    ]},
    "continue",
)
case(
    "legitimate-polling-different-run-id-continue",
    {"budget_tokens": BUDGET, "steps": [
        step(1, "check_job", {"run_id": "r-101"}),
        step(2, "check_job", {"run_id": "r-102"}),
        step(3, "check_job", {"run_id": "r-103"}),
        step(4, "check_job", {"run_id": "r-104"}),
    ]},
    "continue",
)
case(
    "decoy-non-consecutive-repeat-different-args",
    {"budget_tokens": BUDGET, "steps": [
        step(1, "fetch_page", {"url": "https://example.com/a"}),
        step(2, "summarize", {"text": "alpha"}),
        step(3, "fetch_page", {"url": "https://example.com/b"}),
        step(4, "summarize", {"text": "beta"}),
        step(5, "fetch_page", {"url": "https://example.com/c"}),
    ]},
    "continue",
)

# --- independence / edge probes ---------------------------------------------
case(
    "loop-with-huge-budget-headroom",
    {"budget_tokens": 1000000, "steps": [
        step(1, "grep", {"pattern": "TODO"}, 10),
        step(2, "grep", {"pattern": "TODO"}, 10),
        step(3, "grep", {"pattern": "TODO"}, 10),
        step(4, "grep", {"pattern": "TODO"}, 10),
    ]},
    "halt",
)
case(
    "empty-history-fresh-run",
    {"budget_tokens": BUDGET, "steps": []},
    "continue",
)

# --- defensive extras --------------------------------------------------------
case(
    "missing-and-null-fields",
    {"budget_tokens": BUDGET, "steps": [
        {"step_number": 1, "tool": "noop"},
        {"step_number": 2, "tool": "noop", "args": None, "tokens_used": None},
        {"step_number": 3, "tool": "noop", "args": {}},
    ]},
    "halt",
)
case(
    "worked-example-1",
    {"budget_tokens": 20000, "steps": [
        step(1, "fetch_page", {"url": "https://example.com/1"}, 9000),
        step(2, "summarize", {"text": "..."}, 7000),
        step(3, "fetch_page", {"url": "https://example.com/2"}, 5000),
    ]},
    "halt",
)
case(
    "four-step-cycle-not-yet-six",
    {"budget_tokens": BUDGET, "steps": [
        step(1, "read_file", {"path": "a.py"}),
        step(2, "run_tests", {"suite": "unit"}),
        step(3, "read_file", {"path": "a.py"}),
        step(4, "run_tests", {"suite": "unit"}),
    ]},
    "continue",
)


def main():
    failed = 0
    for name, payload, expected in CASES:
        out = evaluate(payload)
        ok = (
            isinstance(out, dict)
            and set(out) == {"decision", "reason"}
            and out["decision"] == expected
            and isinstance(out["reason"], str)
            and out["reason"]
        )
        if not ok:
            failed += 1
        print(f"{'PASS' if ok else 'FAIL'}  {name:44s} -> {out['decision']:8s} | {out['reason']}")
    print(f"\n{len(CASES) - failed}/{len(CASES)} passed")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
