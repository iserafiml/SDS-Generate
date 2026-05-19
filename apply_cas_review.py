"""
Apply the human-reviewed CAS list back into data/rm_index.json.

Parses the AUTO-RESOLVED section of data/sources/cas_resolved_review.txt
(which the reviewer may have edited). For each RM:
  - if the CAS differs from the index, update cas/cas_all (and a DB stub
    will be created by sync_db_stubs for any new CAS);
  - mark cas_source="confirmed" and needs_review=False either way.

Only RMs listed in that section are touched. Run:
  python3 apply_cas_review.py && python3 sync_db_stubs.py
"""

from __future__ import annotations

import json
import re
from pathlib import Path

BASE = Path(__file__).parent
IDX = BASE / "data" / "rm_index.json"
REVIEW = BASE / "data" / "sources" / "cas_resolved_review.txt"

_LINE = re.compile(r"^\s*(RM[\w.\-]+)\s+.*?->\s*([0-9;\-\s]+?)\s*$")


def main() -> None:
    idx = json.loads(IDX.read_text(encoding="utf-8"))
    text = REVIEW.read_text(encoding="utf-8")

    section = text.split("AUTO-RESOLVED", 1)[-1].split("== PROPRIETARY", 1)[0]
    changed, confirmed, missing = [], 0, []

    for ln in section.splitlines():
        m = _LINE.match(ln)
        if not m:
            continue
        rm = m.group(1).strip()
        cas_field = m.group(2).strip()
        cas_all = re.findall(r"\d{2,7}-\d{2}-\d", cas_field)
        if rm not in idx:
            missing.append(rm)
            continue
        rec = idx[rm]
        if cas_all and cas_all[0] != rec.get("cas"):
            changed.append((rm, rec.get("cas"), cas_all[0]))
            rec["cas"] = cas_all[0]
            rec["cas_all"] = cas_all
        rec["cas_source"] = "confirmed"
        rec["needs_review"] = False
        confirmed += 1

    IDX.write_text(json.dumps(idx, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Confirmed {confirmed} RMs | CAS changed: {len(changed)} | "
          f"not-found RMs: {len(missing)}")
    for rm, old, new in changed:
        print(f"  {rm}: {old or '(none)'} -> {new}")
    if missing:
        print("  not found in index:", ", ".join(missing))


if __name__ == "__main__":
    main()
