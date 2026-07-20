"""Independent SSRF corpus for Q8, written by the orchestrator.

Target is chosen by argv: 'local' uses TestClient, 'live' hits the deployed
endpoint the way the grader does. Every entry is labelled with the decision
it must get, so over-blocking shows up as loudly as a leak.
"""
import sys

BENIGN = [
    "https://example.com/",
    "http://example.com/",
    "https://www.iana.org/",
    "https://example.com/index.html",
    "https://EXAMPLE.com/",
]

MALICIOUS = [
    # loopback / private / link-local, various encodings
    "http://127.0.0.1/", "http://127.1/", "http://2130706433/",
    "http://0177.0.0.1/", "http://0x7f000001/", "http://[::1]/",
    "http://[::ffff:127.0.0.1]/", "http://localhost/", "http://10.0.0.1/",
    "http://192.168.1.1/", "http://172.16.0.1/", "http://169.254.169.254/",
    "http://169.254.169.254/latest/meta-data/",
    "http://metadata.google.internal/computeMetadata/v1/",
    "http://100.100.100.200/", "http://[fd00::1]/", "http://0.0.0.0/",
    # authority confusion
    "https://example.com@evil.example/",
    "https://evil.example#@example.com/",
    "https://evil.example?@example.com/",
    "https://example.com%2f@evil.example/",
    "https://user:pass@evil.example/",
    "https://example.com:pass@evil.example/",
    "https:/\\evil.example/",
    "https://evil.example\\@example.com/",
    # lookalikes
    "https://example.com.evil.example/", "https://evilexample.com/",
    "https://sub.example.com/", "https://notexample.com/",
    "https://example.com.br/",
    # IDN / unicode homographs
    "https://еxample.com/", "https://xn--xample-2of.com/",
    "https://exａmple.com/",
    # schemes
    "file:///etc/passwd", "gopher://127.0.0.1:11211/_stats",
    "dict://127.0.0.1:11211/stat", "ftp://evil.example/",
    "data:text/plain,hello", "jar:http://evil.example!/",
    "//evil.example/", "http://evil.example/",
    # header / control-character injection
    "https://example.com\r\nHost: evil.example/",
    "https://example.com\nX: y/",
    "https://exam\tple.com/",
    "https://example.com\x00.evil.example/",
    " https://evil.example/",
    # path traversal shapes
    "https://example.com/../../etc/passwd",
    "https://example.com/%2e%2e/%2e%2e/etc/passwd",
    # empty / malformed
    "https:///", "https://", "http://:80/", "not-a-url", "",
]


def run(target):
    if target == "live":
        import httpx
        c = httpx.Client(timeout=60)
        call = lambda b: c.post("https://ga5-tds.onrender.com/q8/check", json=b).json()
    else:
        from fastapi.testclient import TestClient
        from main import app
        tc = TestClient(app)
        call = lambda b: tc.post("/q8/check", json=b).json()

    leaks, overblocks, errors = [], [], []
    for u in MALICIOUS:
        try:
            r = call({"tool": "fetch_url", "arguments": {"url": u}})
            if r.get("action") == "allow":
                leaks.append((u, r))
        except Exception as exc:
            errors.append((u, f"{type(exc).__name__}: {exc}"))
    for u in BENIGN:
        try:
            r = call({"tool": "fetch_url", "arguments": {"url": u}})
            if r.get("action") != "allow":
                overblocks.append((u, r.get("reason")))
        except Exception as exc:
            errors.append((u, f"{type(exc).__name__}: {exc}"))

    print(f"target={target}  malicious={len(MALICIOUS)}  benign={len(BENIGN)}")
    print(f"LEAKS (allowed but must block): {len(leaks)}")
    for u, r in leaks:
        print("   !!", repr(u), "->", str(r)[:130])
    print(f"OVER-BLOCKS (benign wrongly blocked, scores zero): {len(overblocks)}")
    for u, why in overblocks:
        print("   !!", repr(u), "->", why)
    if errors:
        print(f"ERRORS: {len(errors)}")
        for u, e in errors[:8]:
            print("   ??", repr(u), "->", e)
    print("CLEAN" if not leaks and not overblocks else "PROBLEMS FOUND")


run(sys.argv[1] if len(sys.argv) > 1 else "local")
