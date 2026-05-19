"""
Shared "add a raw material to the library" logic.

Used by both the CLI (add_material.py) and the web button
(POST /api/add_material). Adding a material:
  1. picks the next free RM number (or uses a supplied one),
  2. resolves a CAS via PubChem when none is given (flagged needs_review;
     an LLM is never used to guess a CAS),
  3. derives active_fraction from the supplied strength / trade name,
  4. atomically appends to data/rm_index.json,
  5. creates a pure-substance stub in data/raw_material_db.json so the
     chemical is "In DB" and AI-enriched on first use.

Returns a summary dict; raises ValueError on bad input.
"""

from __future__ import annotations

import json
import os
import re
import tempfile
from pathlib import Path

# Reuse the reviewed-and-verified resolver/cleaner.
from resolve_missing_cas import _OVERRIDE, _clean, _pubchem_cas

BASE = Path(__file__).parent
IDX = BASE / "data" / "rm_index.json"
DB = BASE / "data" / "raw_material_db.json"

_RMNUM = re.compile(r"^RM(\d+)$", re.I)
_PCT = re.compile(r"(\d+(?:\.\d+)?)\s*%")
_CAS = re.compile(r"^\d{2,7}-\d{2}-\d$")


def _atomic_write(path: Path, data) -> None:
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=".tmp_", suffix=".json")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        os.replace(tmp, path)
    except Exception:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise


def _next_rm(idx: dict) -> str:
    nums = [int(m.group(1)) for k in idx if (m := _RMNUM.match(k))]
    return f"RM{(max(nums) + 1) if nums else 1:04d}"


def _strength(name: str, strength_pct) -> tuple[float, str]:
    if isinstance(strength_pct, (int, float)) and 0 < strength_pct <= 100:
        return float(strength_pct), "manual"
    m = _PCT.search(name or "")
    if m:
        v = float(m.group(1))
        if 0 < v <= 100:
            return v, "name"
    if re.search(r"\bglacial\b", name or "", re.I):
        return 100.0, "name"
    return 100.0, "default"


def _stub(cas: str, name: str) -> dict:
    return {
        "cas": cas, "name": name,
        "threshold_basis": "pure",
        "ghs_triggers": {}, "oels": [], "toxicology": {},
        "aquatic_toxicology": {"acute": [], "chronic": []},
        "persistence": "", "bioaccumulation": "", "mobility": "",
        "iarc_classification": "Not Applicable",
        "ntp_classification": "Not Applicable",
        "regulatory": {
            "tsca_listed": False, "sara_302": False, "sara_302_tpq_lbs": "",
            "sara_313": False, "cercla_listed": False, "cercla_rq_lbs": "",
            "rcra_code": "", "caa_112r": False, "prop_65": False,
            "prop_65_warning": "", "rtk_states": [],
        },
    }


def add_material(name: str, cas: str = "", strength_pct=None,
                 rm: str | None = None, synonyms: str = "") -> dict:
    name = (name or "").strip()
    if not name:
        raise ValueError("Material name is required.")
    cas = (cas or "").strip()

    idx = json.loads(IDX.read_text(encoding="utf-8"))

    rm = (rm or "").strip().upper() or _next_rm(idx)
    if rm in idx:
        raise ValueError(f"{rm} already exists ({idx[rm].get('name')}).")

    if cas:
        if not _CAS.match(cas):
            raise ValueError(f"'{cas}' is not a valid CAS number format.")
        cas_source, needs_review = "manual", False
    else:
        cand = _clean(name).lower()
        cas = next((ov for ok, ov in _OVERRIDE.items()
                    if cand == ok or cand.startswith(ok)), "")
        if not cas:
            cas = _pubchem_cas(_clean(name)) or _pubchem_cas(name)
        cas_source = "pubchem-auto" if cas else "unresolved"
        needs_review = True

    strength, ssrc = _strength(name, strength_pct)
    idx[rm] = {
        "cas": cas,
        "cas_all": [cas] if cas else [],
        "name": name,
        "synonyms": synonyms.strip(),
        "active_fraction": round(strength / 100.0, 4),
        "strength_pct": strength,
        "strength_source": ssrc,
        "needs_review": needs_review,
        "cas_source": cas_source,
    }
    _atomic_write(IDX, idx)

    stub_added = False
    if cas:
        records = json.loads(DB.read_text(encoding="utf-8"))
        if cas not in {r["cas"] for r in records}:
            records.append(_stub(cas, name))
            _atomic_write(DB, records)
            stub_added = True

    return {
        "rm": rm, "cas": cas, "name": name,
        "active_fraction": idx[rm]["active_fraction"],
        "strength_pct": strength, "strength_source": ssrc,
        "cas_source": cas_source, "needs_review": needs_review,
        "stub_added": stub_added,
    }


if __name__ == "__main__":
    import sys
    print(add_material(*sys.argv[1:]))
