"""Print one compact block per ask from a battery JSON.

Run: python artifacts/bakeoff-digest.py artifacts/bakeoff-<tag>.json [needle] [width]
needle filters questions by substring; width truncates the answer (default 320).
"""

import json
import sys
from pathlib import Path

path = sys.argv[1]
needle = (sys.argv[2] if len(sys.argv) > 2 else "").lower()
width = int(sys.argv[3]) if len(sys.argv) > 3 else 320

data = json.loads(Path(path).read_text(encoding="utf-8"))
for r in data:
    if needle and needle not in r["question"].lower():
        continue
    resp = r["response"]
    cite = resp["citations"][0]["chunk_id"] if resp["citations"] else "-"
    ans = " ".join((resp.get("answer") or "").split())
    print(f"Q: {r['question']}")
    print(f"   {cite} refused={int(resp['refused'])} | {ans[:width]}")
    print()
