"""Run one Q9 Check and print the grader's verdict.

Usage:  python run_check.py <quizSign>

The quizSign comes from any Check request in devtools -> Network -> right-click
-> Copy as cURL. Cloudflare answers 403 error 1010 without a user-agent, so the
browser headers below are not optional.
"""
import json
import sys
import urllib.request

EMAIL = "24f2004141@ds.study.iitm.ac.in"
URL = "https://ga5-tds.onrender.com/q9/mailroom"
QUESTION = "q-taint-aware-agent-executor-server"

HEADERS = {
    "content-type": "application/json",
    "user-agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                   "(KHTML, like Gecko) Chrome/140.0.0.0 Safari/537.36"),
    "accept": "*/*",
    "origin": "https://exam.sanand.workers.dev",
    "referer": "https://exam.sanand.workers.dev/",
}


def main(sign):
    body = json.dumps({
        "email": EMAIL, "quizSign": sign, "response": URL,
        "weight": 4, "questionId": QUESTION, "version": "v2",
    }).encode()
    req = urllib.request.Request(
        "https://exam.sanand.workers.dev/backendVerify", body, HEADERS)
    with urllib.request.urlopen(req, timeout=240) as r:
        out = json.loads(r.read())
    print(json.dumps(out, indent=2)[:4000])


if __name__ == "__main__":
    if len(sys.argv) < 2:
        sys.exit("usage: python run_check.py <quizSign>")
    main(sys.argv[1])
