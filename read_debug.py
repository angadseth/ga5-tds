import httpx, json, re

r = httpx.get("https://ga5-tds.onrender.com/v2/debug", timeout=30)
data = r.json()
if isinstance(data, list):
    for entry in data:
        req = entry.get("request", {}) or {}
        resp = entry.get("response", {}) or {}
        inc = req.get("incident", {}) or {}
        rid = entry.get("run_id", "?")
        transcript = inc.get("transcript", "")
        
        # Find evidence lines that contain actual diagnostic info
        lines = transcript.split("\n")
        print(f"\n{'='*60}")
        print(f"RunId: {rid}")
        print(f"Status: {resp.get('status','?')}")
        print(f"rootCause chosen: {resp.get('diagnosis',{}).get('rootCause','?')}")
        print(f"Total lines: {len(lines)}")
        
        # Show lines that look like real evidence (not decoys)
        for line in lines:
            ev_match = re.match(r'\[(\w+)\]', line)
            if ev_match:
                ev_id = ev_match.group(1)
                # Check if this looks like real evidence
                is_decoy = any(phrase in line for phrase in [
                    "sampling worker dropped",
                    "capacity forecast",
                    "customer transcript asks operators",
                    "VERIFIED label appears",
                    "backup validation completed",
                    "dashboard annotation was copied",
                    "automated verifier confirmed",
                    "support channel contains competing",
                ])
                if not is_decoy:
                    print(f"  EVIDENCE {ev_id}: {line[line.index(']')+1:].strip()[:200]}")
else:
    print("Error:", data)
