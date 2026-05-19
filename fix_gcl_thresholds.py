"""
One-time corrective migration: snap AI-seeded health-hazard trigger
thresholds to the authoritative GHS/CLP generic concentration limits.

Earlier enrichment copied a uniform ~0.1 % example threshold for every
health class, which over-classifies mixtures at low concentrations
(e.g. reproductive toxicity should trigger at 0.3 %, not 0.1 %). This
rewrites threshold_pct for the seven health classes by category using
db_enrichment.HEALTH_GCL. Physical/curated triggers (skin_corrosion,
serious_eye_damage, oxidizing_liquid, acute_toxicity_*, environmental,
stot_se) are left untouched — no regression on validated data.

Deterministic and free (no API). Run:  python3 fix_gcl_thresholds.py
"""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

from db_enrichment import HEALTH_GCL

DB = Path(__file__).parent / "data" / "raw_material_db.json"


def main() -> None:
    records = json.loads(DB.read_text(encoding="utf-8"))
    changes = []

    for r in records:
        trig = r.get("ghs_triggers") or {}
        for cls, spec in trig.items():
            if cls not in HEALTH_GCL or not isinstance(spec, dict):
                continue
            cat = str(spec.get("category", "")).strip()
            correct = HEALTH_GCL[cls].get(cat)
            if correct is None:
                continue
            old = spec.get("threshold_pct")
            try:
                if float(old) != float(correct):
                    spec["threshold_pct"] = correct
                    changes.append((r["cas"], cls, cat, old, correct))
            except (TypeError, ValueError):
                spec["threshold_pct"] = correct
                changes.append((r["cas"], cls, cat, old, correct))

    fd, tmp = tempfile.mkstemp(dir=str(DB.parent), prefix=".tmp_", suffix=".json")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(records, f, ensure_ascii=False, indent=2)
        os.replace(tmp, DB)
    except Exception:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise

    print(f"Corrected {len(changes)} health-trigger thresholds "
          f"across {len({c[0] for c in changes})} chemicals.")
    for cas, cls, cat, old, new in changes[:40]:
        print(f"  {cas:14s} {cls:26s} {cat:3s} {old} -> {new}")
    if len(changes) > 40:
        print(f"  ... (+{len(changes) - 40} more)")


if __name__ == "__main__":
    main()
