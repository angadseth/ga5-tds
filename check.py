"""Run one GA5 Check without the browser.

    python check.py q10 | q9 | q11 | q3 ...

quizSign is recovered from Chrome Profile 1's Local Storage leveldb, so no
copy-paste from devtools is needed while that session is alive.
"""
import json
import re
import sys
import time
import urllib.error
import urllib.request

EMAIL = "24f2004141@ds.study.iitm.ac.in"
LEVELDB = (r"C:\Users\24f20\AppData\Local\Google\Chrome\User Data"
           r"\Profile 1\Local Storage\leveldb\003060.ldb")

QUESTIONS = {
    "q3": ("q-agent-tool-guardrail-server", "v1", 4,
           "https://q3-vercel.vercel.app/q3/check"),
    "q9": ("q-taint-aware-agent-executor-server", "v2", 4,
           "https://ga5-tds.onrender.com/q9/mailroom"),
    "q10": ("q-a2a-durable-delegate-server", "v2", 4,
            "https://ga5-tds.onrender.com/a2a/"),
    "q11": ("q-agent-trace-integrity-server", "v2", 4,
            "https://q11-vercel.vercel.app"),
}

HEADERS = {
    "content-type": "application/json",
    "user-agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                   "(KHTML, like Gecko) Chrome/140.0.0.0 Safari/537.36"),
    "accept": "*/*",
    "origin": "https://exam.sanand.workers.dev",
    "referer": "https://exam.sanand.workers.dev/",
}


def quiz_sign():
    blob = open(LEVELDB, "rb").read().decode("utf-8", "replace")
    return re.search(r'"quizSign":"([^"]+)"', blob).group(1)


def main(key, url=None):
    question, version, weight, default_url = QUESTIONS[key]
    body = json.dumps({
        "email": EMAIL, "quizSign": quiz_sign(), "response": url or default_url,
        "weight": weight, "questionId": question, "version": version,
    }).encode()
    request = urllib.request.Request(
        "https://exam.sanand.workers.dev/backendVerify", body, HEADERS)
    started = time.time()
    try:
        with urllib.request.urlopen(request, timeout=300) as response:
            out = json.loads(response.read())
    except urllib.error.HTTPError as exc:
        print("HTTP", exc.code, exc.read()[:500].decode("utf-8", "replace"))
        return
    print(f"{key}: score {out.get('score')}  ({time.time() - started:.0f}s)")
    print(out.get("message", "")[:1500])
    details = out.get("details") or {}
    if details:
        print(json.dumps(details, indent=1)[:3000])


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2] if len(sys.argv) > 2 else None)
