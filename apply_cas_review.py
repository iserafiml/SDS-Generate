"""
Apply the human-reviewed CAS list (data/sources/cas_resolved_review.txt)
back into data/rm_index.json.

Parses EVERY ``RM####  name  -> value`` line in the file (all sections —
AUTO-RESOLVED, PROPRIETARY, UNRESOLVED), tolerating tabs / extra spaces /
comma- or semicolon-separated multi-CAS. The value after ``->`` may be:
  - one or more CAS numbers  -> cas (first) + cas_all, confirmed, no review
  - "non harz" / "non haz" / "none" -> declared non-hazardous, no CAS
Lines without ``->`` are left unchanged.

Run:  python3 apply_cas_review.py && python3 sync_db_stubs.py
"""

from __future__ import annotations

import json
import re
from pathlib import Path

BASE = Path(__file__).parent
IDX = BASE / "data" / "rm_index.json"
REVIEW = BASE / "data" / "sources" / "cas_resolved_review.txt"

_LINE = re.compile(r"^\s*(RM[\w.\-]+)\s+.*?->\s*(.+?)\s*$")
_CAS = re.compile(r"\d{2,7}-\d{2}-\d")
_NONHAZ = {"non harz", "non haz", "nonharz", "non-haz", "nonhazardous",
           "non-hazardous", "none", "n/a", "na"}


def main() -> None:
    idx = json.loads(IDX.read_text(encoding="utf-8"))
    confirmed = nonhaz = changed = skipped = 0
    notes = []

    for ln in REVIEW.read_text(encoding="utf-8").splitlines():
        m = _LINE.match(ln)
        if not m:
            continue
        rm, rhs = m.group(1).strip(), m.group(2).strip()
        if rm not in idx:
            notes.append(f"  ! {rm} not in rm_index — skipped")
            continue
        rec = idx[rm]
        cas_all = _CAS.findall(rhs)

        if cas_all:
            if cas_all[0] != rec.get("cas"):
                changed += 1
            rec["cas"] = cas_all[0]
            rec["cas_all"] = cas_all
            rec["cas_source"] = "confirmed"
            rec["needs_review"] = False
            confirmed += 1
            if len(cas_all) > 1:
                notes.append(f"  multi-CAS {rm}: {cas_all} (primary {cas_all[0]})")
        elif rhs.lower() in _NONHAZ:
            rec["cas"] = ""
            rec["cas_all"] = []
            rec["cas_source"] = "non-hazardous"
            rec["needs_review"] = False
            nonhaz += 1
        else:
            skipped += 1
            notes.append(f"  ? {rm}: unrecognised value '{rhs}' — left as-is")

    IDX.write_text(json.dumps(idx, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Confirmed CAS: {confirmed} (changed {changed}) | "
          f"non-hazardous: {nonhaz} | unrecognised: {skipped}")
    for n in notes:
        print(n)


if __name__ == "__main__":
    main()
