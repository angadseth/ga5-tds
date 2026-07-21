"""Pull the grader's per-dossier verdicts for the last Check and attribute them
to the probe buckets.

The commit request the grader sends carries `receipts[].accepted` for every
proposal, so one Check run measures every hypothesis the corpus was split
across. Run this straight after a Check, BEFORE any redeploy - `/tmp/ga5.db`
holds the captures and every deploy wipes it.
"""
import collections
import json
import os
import sys
import urllib.request

KEY = "ga5cap-8a1707d9605ce94f255c8c6e"
BASE = "https://ga5-tds.onrender.com/debug/capture"
OUT = "captured_q9f"


def get(url):
    with urllib.request.urlopen(url, timeout=120) as r:
        return json.loads(r.read())


def main():
    os.makedirs(OUT, exist_ok=True)
    index = get("%s?key=%s&path=/q9/mailroom&limit=200" % (BASE, KEY))
    rows = index if isinstance(index, list) else index.get("items", [])
    print("captures:", len(rows))
    blobs = []
    for row in rows:
        cid = row.get("id") if isinstance(row, dict) else row
        blob = get("%s/%s?key=%s" % (BASE, cid, KEY))
        with open(os.path.join(OUT, "q9_%s.json" % cid), "w", encoding="utf-8") as fh:
            json.dump(blob, fh, ensure_ascii=False)
        blobs.append(blob)

    props, acc, doss = {}, {}, {}
    for d in blobs:
        req = d.get("request") or {}
        if req.get("operation") == "propose" and "dossiers" in req:
            for x in req["dossiers"]:
                doss[x["dossierId"]] = x
        if d.get("status") == 200 and req.get("operation") == "propose":
            for p in (d.get("response") or {}).get("proposals", []):
                props[p["dossierId"]] = p
        if req.get("operation") == "commit":
            for x in req.get("receipts", []):
                acc[x["dossierId"]] = x["accepted"]

    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    os.environ.setdefault("GA5_DB", os.path.join(os.environ.get("TEMP", "/tmp"),
                                                 "q9read.db"))
    import q9_mailroom as q9

    tally = collections.Counter()
    for did, p in props.items():
        if did not in acc:
            continue
        tally[(p["action"], q9._variant(did), acc[did])] += 1
    print()
    for k in sorted(tally):
        print("  %-24s bucket%d  accepted=%-5s n=%d" % (k[0], k[1], k[2], tally[k]))
    print()
    ok = sum(1 for v in acc.values() if v)
    print("ACCEPTED %d / %d" % (ok, len(acc)))


if __name__ == "__main__":
    main()
