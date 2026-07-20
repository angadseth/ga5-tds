"""Red-team self-test for q8_redteam.py. Run: python test_q8.py"""

import json
import sys

from fastapi import FastAPI
from fastapi.testclient import TestClient

import q8_redteam
from q8_redteam import CANARY

app = FastAPI()
app.include_router(q8_redteam.router)
client = TestClient(app)

SANDBOX = "/srv/agent-redteam/sandbox-9a993617d5"
ALL_RESPONSES = []
FAILURES = []


def call(tool, **args):
    r = client.post("/q8/check", json={"tool": tool, "arguments": args})
    body = r.json()
    ALL_RESPONSES.append(body)
    return body


def expect_allow(label, body, must_contain=None):
    if body.get("action") != "allow":
        FAILURES.append(f"{label}: expected allow, got {body}")
        return
    if must_contain is not None:
        res = body.get("result")
        text = res if isinstance(res, str) else json.dumps(res)
        if must_contain not in (text or ""):
            FAILURES.append(f"{label}: result missing {must_contain!r} -> {str(text)[:120]!r}")
            return
    print(f"  PASS  {label}")


def expect_block(label, body):
    if body.get("action") != "block":
        FAILURES.append(f"{label}: expected block, got {body}")
        return
    if body.get("result"):
        FAILURES.append(f"{label}: block returned a non-empty result {body['result']!r}")
        return
    print(f"  PASS  {label}")


print("physical base:", q8_redteam.PHYS_BASE)

print("\n[benign file reads - blocking any of these scores ZERO]")
expect_allow("read notes/report.txt",
             call("read_file", path=f"{SANDBOX}/notes/report.txt"),
             "SAFE_REPORT_712dd3637a14875f60b8aa45")
expect_allow("read notes/looks-like-..-but-safe.txt (trap: benign name)",
             call("read_file", path=f"{SANDBOX}/notes/looks-like-..-but-safe.txt"),
             "SAFE_WEIRD_62ea872a236b938df8f493db")
expect_allow("read encoded/%2e%2e-literal.txt (trap: benign name)",
             call("read_file", path=f"{SANDBOX}/encoded/%2e%2e-literal.txt"),
             "SAFE_ENCODED_05d1e7c20b7a70308452728e")
expect_allow("read via redundant slashes and ./",
             call("read_file", path=f"{SANDBOX}//notes/./report.txt"),
             "SAFE_REPORT_712dd3637a14875f60b8aa45")
expect_allow("read via relative path",
             call("read_file", path="notes/report.txt"),
             "SAFE_REPORT_712dd3637a14875f60b8aa45")
expect_allow("read via in-sandbox .. round-trip",
             call("read_file", path=f"{SANDBOX}/encoded/../notes/report.txt"),
             "SAFE_REPORT_712dd3637a14875f60b8aa45")

print("\n[malicious file reads]")
expect_block("canary direct path",
             call("read_file", path="/srv/agent-redteam/outside-87c065e3/canary.txt"))
expect_block("canary via ../ traversal",
             call("read_file", path=f"{SANDBOX}/../outside-87c065e3/canary.txt"))
expect_block("canary via deep ../../",
             call("read_file", path=f"{SANDBOX}/notes/../../outside-87c065e3/canary.txt"))
expect_block("canary via %2e%2e/ encoding",
             call("read_file", path=f"{SANDBOX}/%2e%2e/outside-87c065e3/canary.txt"))
expect_block("canary via %2e%2e%2f encoding",
             call("read_file", path=f"{SANDBOX}/%2e%2e%2foutside-87c065e3%2fcanary.txt"))
expect_block("canary via double encoding %252e%252e",
             call("read_file", path=f"{SANDBOX}/%252e%252e/outside-87c065e3/canary.txt"))
expect_block("canary via backslash traversal",
             call("read_file", path=SANDBOX + "\\..\\outside-87c065e3\\canary.txt"))
expect_block("canary via relative ..",
             call("read_file", path="../outside-87c065e3/canary.txt"))
expect_block("/etc/passwd", call("read_file", path="/etc/passwd"))
expect_block("/proc/self/environ", call("read_file", path="/proc/self/environ"))
expect_block("~/.ssh/id_rsa", call("read_file", path="~/.ssh/id_rsa"))
expect_block("prefix-confusion sibling dir",
             call("read_file", path="/srv/agent-redteam/sandbox-9a993617d5-evil/secret.txt"))
expect_block("prefix confusion on base",
             call("read_file", path="/srv/agent-redteam-evil/canary.txt"))
expect_block("null byte truncation",
             call("read_file", path=f"{SANDBOX}/notes/report.txt\x00/../../outside-87c065e3/canary.txt"))
expect_block("overlong path", call("read_file", path=f"{SANDBOX}/" + "a" * 5000))
expect_block("missing path", call("read_file"))
expect_block("directory instead of file", call("read_file", path=f"{SANDBOX}/notes"))

print("\n[benign fetches - blocking any of these scores ZERO]")
expect_allow("fetch https://example.com/", call("fetch_url", url="https://example.com/"))
expect_allow("fetch https://www.iana.org/", call("fetch_url", url="https://www.iana.org/"))

print("\n[malicious fetches]")
expect_block("loopback 127.0.0.1", call("fetch_url", url="http://127.0.0.1/"))
expect_block("localhost", call("fetch_url", url="http://localhost:8080/"))
expect_block("cloud metadata IP", call("fetch_url", url="http://169.254.169.254/latest/meta-data/"))
expect_block("gcp metadata host", call("fetch_url", url="http://metadata.google.internal/"))
expect_block("private 10.0.0.1", call("fetch_url", url="http://10.0.0.1/"))
expect_block("private 192.168.1.1", call("fetch_url", url="http://192.168.1.1/"))
expect_block("private 172.16.0.1", call("fetch_url", url="http://172.16.0.1/"))
expect_block("ipv6 loopback", call("fetch_url", url="http://[::1]/"))
expect_block("decimal IP encoding", call("fetch_url", url="http://2130706433/"))
expect_block("octal IP encoding", call("fetch_url", url="http://0177.0.0.1/"))
expect_block("hex IP encoding", call("fetch_url", url="http://0x7f000001/"))
expect_block("userinfo confusion", call("fetch_url", url="https://example.com@evil.com/"))
expect_block("userinfo with password", call("fetch_url", url="https://example.com:pass@127.0.0.1/"))
expect_block("subdomain lookalike", call("fetch_url", url="https://example.com.evil.com/"))
expect_block("prefix lookalike", call("fetch_url", url="https://evilexample.com/"))
expect_block("typo lookalike", call("fetch_url", url="https://exarnple.com/"))
expect_block("idn homograph", call("fetch_url", url="https://exаmple.com/"))
expect_block("punycode homograph", call("fetch_url", url="https://xn--exmple-4nf.com/"))
expect_block("iana lookalike subdomain", call("fetch_url", url="https://www.iana.org.evil.com/"))
expect_block("bare iana.org (not exact host)", call("fetch_url", url="https://iana.org/"))
expect_block("file scheme", call("fetch_url", url="file:///etc/passwd"))
expect_block("gopher scheme", call("fetch_url", url="gopher://127.0.0.1:11211/"))
expect_block("ftp scheme", call("fetch_url", url="ftp://example.com/"))
expect_block("non-standard port", call("fetch_url", url="https://example.com:8080/"))
expect_block("trailing-dot bypass attempt", call("fetch_url", url="https://example.com.evil.com./"))
# --- regressions found by the live grader (url family) ---
expect_block("trailing dot on allowed host", call("fetch_url", url="https://example.com./"))
expect_block("trailing dot with path", call("fetch_url", url="http://example.com./evil"))
expect_block("double trailing dot", call("fetch_url", url="https://example.com../"))
expect_block("leading empty label", call("fetch_url", url="https://.example.com/"))
expect_block("fullwidth homograph e", call("fetch_url", url="https://ｅxample.com/"))
expect_block("fullwidth homograph p", call("fetch_url", url="https://examｐle.com/"))
expect_block("fullwidth iana", call("fetch_url", url="https://www.ianａ.org/"))
expect_block("punycode label on allowed host", call("fetch_url", url="https://xn--example-fya.com/"))
expect_block("underscore in host", call("fetch_url", url="https://exam_ple.com/"))
expect_block("host with space", call("fetch_url", url="https://example.com /"))
expect_block("overlong label", call("fetch_url", url="https://" + "a" * 70 + ".example.com/"))
expect_block("hyphen-edge label", call("fetch_url", url="https://-example.com/"))
expect_block("missing url", call("fetch_url"))

print("\n[redirect chains - simulated, no allow-listed host really 3xx's to private]")
_real_get = q8_redteam._http_get


def fake_redirects(script):
    """script: {url: (status, location)} ; anything else -> 200 OK body."""
    def _get(url):
        if url in script:
            status, loc = script[url]
            return status, {"location": loc} if loc else {}, ""
        return 200, {}, f"BODY_OF {url}"
    return _get


def with_script(label, script, url, expect):
    q8_redteam._http_get = fake_redirects(script)
    try:
        body = call("fetch_url", url=url)
    finally:
        q8_redteam._http_get = _real_get
    (expect_allow if expect == "allow" else expect_block)(label, body)


with_script("302 -> loopback", {"https://example.com/": (302, "http://127.0.0.1/")},
            "https://example.com/", "block")
with_script("302 -> metadata", {"https://example.com/": (302, "http://169.254.169.254/latest/meta-data/")},
            "https://example.com/", "block")
with_script("302 -> file scheme", {"https://example.com/": (302, "file:///etc/passwd")},
            "https://example.com/", "block")
with_script("302 -> protocol-relative private",
            {"https://example.com/": (302, "//10.0.0.1/x")}, "https://example.com/", "block")
with_script("302 -> userinfo confusion",
            {"https://example.com/": (302, "https://example.com@127.0.0.1/")},
            "https://example.com/", "block")
with_script("302 -> lookalike",
            {"https://example.com/": (302, "https://example.com.evil.com/")},
            "https://example.com/", "block")
with_script("multi-hop, last hop private", {
    "https://example.com/": (302, "https://www.iana.org/a"),
    "https://www.iana.org/a": (302, "https://example.com/b"),
    "https://example.com/b": (302, "http://169.254.169.254/"),
}, "https://example.com/", "block")
with_script("redirect loop exceeds hop cap", {
    "https://example.com/": (302, "https://www.iana.org/"),
    "https://www.iana.org/": (302, "https://example.com/"),
}, "https://example.com/", "block")
with_script("302 -> relative path on same host (benign)",
            {"https://example.com/": (302, "/index.html")}, "https://example.com/", "allow")
with_script("302 -> allowed host (benign)",
            {"https://example.com/": (301, "https://www.iana.org/")},
            "https://example.com/", "allow")

print("\n[redirect targets - blocked on the FIRST hop and on a LATER hop]")
for _label, _loc in [
    ("301 -> metadata IP", "http://169.254.169.254/"),
    ("301 -> loopback", "http://127.0.0.1/"),
    ("301 -> protocol-relative evil", "//evil.example/"),
    ("301 -> file scheme", "file:///etc/passwd"),
    ("301 -> gopher scheme", "gopher://127.0.0.1:11211/_"),
    ("301 -> userinfo", "https://example.com@127.0.0.1/"),
    ("301 -> decimal metadata", "http://2851995374/"),
    ("301 -> ipv6 mapped metadata", "http://[::ffff:a9fe:a9fe]/"),
]:
    with_script(f"first hop {_label}", {"https://example.com/": (301, _loc)},
                "https://example.com/", "block")
    with_script(f"later hop {_label}", {
        "https://example.com/": (301, "https://www.iana.org/x"),
        "https://www.iana.org/x": (301, _loc),
    }, "https://example.com/", "block")

with_script("relative Location stays on host (benign)",
            {"https://example.com/": (301, "/ok")}, "https://example.com/", "allow")

print("\n[round-trip invariant - authority must be literally what was sent]")
expect_block("port smuggled twice", call("fetch_url", url="http://example.com:443:80/"))
expect_block("bracketed allowed host", call("fetch_url", url="http://[example.com]/"))
expect_block("percent-encoded host", call("fetch_url", url="http://%65xample.com/"))
expect_block("percent-encoded dot in host", call("fetch_url", url="http://example%2ecom/"))
expect_block("unicode ideographic dot", call("fetch_url", url="https://example.com。evil.example/"))
expect_block("unicode fullwidth dot", call("fetch_url", url="https://example.com．evil.example/"))
expect_block("zero width space in host", call("fetch_url", url="https://example​.com/"))
expect_allow("uppercase host round-trips", call("fetch_url", url="https://EXAMPLE.com/"))
expect_allow("uppercase scheme round-trips", call("fetch_url", url="HTTPS://example.com/"))
expect_allow("explicit default port round-trips", call("fetch_url", url="https://example.com:443/"))
expect_allow("explicit port 80 on http round-trips", call("fetch_url", url="http://example.com:80/"))

print("\n[DNS rebinding - allow-listed host resolving into private space]")
_real_gai = q8_redteam.socket.getaddrinfo


def with_dns(label, addrs, url, expect):
    def fake(host, port, *a, **k):
        return [(2, 1, 6, "", (ip, port)) for ip in addrs]
    q8_redteam.socket.getaddrinfo = fake
    try:
        body = call("fetch_url", url=url)
    finally:
        q8_redteam.socket.getaddrinfo = _real_gai
    (expect_allow if expect == "allow" else expect_block)(label, body)


with_dns("example.com rebound to 127.0.0.1", ["127.0.0.1"], "https://example.com/", "block")
with_dns("example.com rebound to 169.254.169.254", ["169.254.169.254"], "https://example.com/", "block")
with_dns("www.iana.org rebound to 10.0.0.5", ["10.0.0.5"], "https://www.iana.org/", "block")
with_dns("public first, private second record", ["93.184.216.34", "192.168.0.9"],
         "https://example.com/", "block")
with_dns("private AAAA alongside public A", ["93.184.216.34", "::1"],
         "https://example.com/", "block")

print("\n[url path traversal - must not over-block in-root '..']")
expect_block("path climbs above root", call("fetch_url", url="https://example.com/../../etc/passwd"))
expect_block("encoded climb above root", call("fetch_url", url="https://example.com/%2e%2e/%2e%2e/etc/passwd"))
expect_allow("in-root a/../b is fine", call("fetch_url", url="https://example.com/a/../b"))
expect_allow("in-root ./ is fine", call("fetch_url", url="https://example.com/./"))
expect_allow("normal deep path", call("fetch_url", url="https://www.iana.org/domains/reserved"))

print("\n[misc]")
expect_block("unknown tool", call("delete_everything", path="/"))
expect_block("empty body", client.post("/q8/check", json={}).json())

print("\n[global canary sweep]")
blob = json.dumps(ALL_RESPONSES)
if CANARY in blob:
    FAILURES.append("CANARY TOKEN LEAKED IN A RESPONSE")
else:
    print(f"  PASS  canary absent from all {len(ALL_RESPONSES)} responses")

print()
if FAILURES:
    print(f"FAILED ({len(FAILURES)}):")
    for f in FAILURES:
        print("  -", f)
    sys.exit(1)
print(f"ALL {len(ALL_RESPONSES)} CHECKS PASSED")
