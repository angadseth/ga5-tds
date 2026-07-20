"""Reproduce the grader's battery shape: many probes at once, against the
live endpoint. HTTP_STATUS errors here mean the service falls over under
concurrency rather than misclassifying anything."""
import asyncio
import sys
import time

import httpx

B = sys.argv[1] if len(sys.argv) > 1 else "https://ga5-tds.onrender.com"
SB = "/srv/agent-redteam/sandbox-9a993617d5"

PROBES = (
    [{"tool": "read_file", "arguments": {"path": p}} for p in [
        f"{SB}/notes/report.txt",
        f"{SB}/notes/looks-like-..-but-safe.txt",
        f"{SB}/encoded/%2e%2e-literal.txt",
        "/srv/agent-redteam/outside-87c065e3/canary.txt",
        f"{SB}/../outside-87c065e3/canary.txt",
        "/etc/passwd",
    ]] +
    [{"tool": "fetch_url", "arguments": {"url": u}} for u in [
        "https://example.com/", "https://www.iana.org/", "http://example.com/",
        "https://example.com/index.html", "https://www.iana.org/domains/reserved",
        "http://127.0.0.1/", "http://169.254.169.254/", "https://example.com@evil.example/",
        "https://example.com.evil.example/", "file:///etc/passwd",
        "http://[::1]/", "http://2130706433/", "https://xn--xample-2of.com/",
        "http://metadata.google.internal/", "https://evil.example/",
    ]]
) * 2


async def main():
    t0 = time.time()
    async with httpx.AsyncClient(timeout=30) as c:
        async def one(i, p):
            s = time.time()
            try:
                r = await c.post(f"{B}/q8/check", json=p)
                return i, r.status_code, round(time.time() - s, 2), None
            except Exception as exc:
                return i, None, round(time.time() - s, 2), type(exc).__name__
        res = await asyncio.gather(*(one(i, p) for i, p in enumerate(PROBES)))

    errs = [r for r in res if r[1] != 200]
    times = sorted(r[2] for r in res)
    print(f"{len(PROBES)} concurrent probes in {round(time.time()-t0,1)}s")
    print(f"non-200 or failed: {len(errs)}")
    for i, code, dt, exc in errs[:12]:
        print(f"   #{i} status={code} {dt}s {exc or ''}  {str(PROBES[i]['arguments'])[:60]}")
    print(f"latency  min={times[0]}s  median={times[len(times)//2]}s  max={times[-1]}s")


asyncio.run(main())
