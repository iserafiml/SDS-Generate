"""
Add stub records to data/raw_material_db.json for every CAS that appears in
the rebuilt rm_index but is not yet in the chemical DB.

A stub has the full record shape with empty hazard/tox/regulatory fields and
no `_enrichment` stamp, so `db_enrichment.needs_enrichment()` returns True and
the chemical is AI-enriched the first time it is used in a product (then
cached). This makes the ~240-material picker actually backed by the DB.

Idempotent. Run:  python3 sync_db_stubs.py
"""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

BASE = Path(__file__).parent
DB = BASE / "data" / "raw_material_db.json"
IDX = BASE / "data" / "rm_index.json"


def _stub(cas: str, name: str) -> dict:
    return {
        "cas": cas,
        "name": name,
        # AI enrichment fills ghs_triggers as pure-substance GHS generic
        # concentration limits, so the classifier applies the grade's
        # active_fraction (raw% -> pure%). Curated records omit this flag and
        # keep their as-supplied thresholds unchanged.
        "threshold_basis": "pure",
        "ghs_triggers": {},
        "oels": [],
        "toxicology": {},
        "aquatic_toxicology": {"acute": [], "chronic": []},
        "persistence": "",
        "bioaccumulation": "",
        "mobility": "",
        "iarc_classification": "Not Applicable",
        "ntp_classification": "Not Applicable",
        "regulatory": {
            "tsca_listed": False, "sara_302": False, "sara_302_tpq_lbs": "",
            "sara_313": False, "cercla_listed": False, "cercla_rq_lbs": "",
            "rcra_code": "", "caa_112r": False, "prop_65": False,
            "prop_65_warning": "", "rtk_states": [],
        },
    }


def main() -> None:
    records = json.loads(DB.read_text(encoding="utf-8"))
    have = {r["cas"] for r in records}
    idx = json.loads(IDX.read_text(encoding="utf-8"))

    # Best display name per CAS (prefer a non-empty, non-RM-code name).
    name_by_cas: dict[str, str] = {}
    for rm, v in idx.items():
        cas = v.get("cas")
        if cas and cas not in name_by_cas and v.get("name"):
            name_by_cas[cas] = v["name"]

    new = sorted(c for c in name_by_cas if c not in have)
    for cas in new:
        records.append(_stub(cas, name_by_cas[cas]))

    # Migrate stub-origin records created before the basis flag existed:
    # an empty ghs_triggers means no curated thresholds to regress, so it is
    # safe to mark them pure-substance based.
    migrated = 0
    for r in records:
        if not r.get("ghs_triggers") and "threshold_basis" not in r:
            r["threshold_basis"] = "pure"
            migrated += 1

    fd, tmp = tempfile.mkstemp(dir=str(DB.parent), prefix=".rmdb_", suffix=".json")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(records, f, ensure_ascii=False, indent=2)
        os.replace(tmp, DB)
    except Exception:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise

    print(f"Added {len(new)} stub records, migrated {migrated} to "
          f"threshold_basis=pure (DB now {len(records)} chemicals).")
    if new:
        print("New CAS:", ", ".join(new[:12]) + (" ..." if len(new) > 12 else ""))


if __name__ == "__main__":
    main()
