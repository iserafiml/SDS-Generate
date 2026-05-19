"""
Best-effort CAS backfill for rm_index entries that still lack a CAS.

Single, recognizable substances are resolved against PubChem
(name → CID → first CAS-format synonym — verified accurate on a known
sample). Every auto-resolved CAS is flagged `needs_review: True` with
`cas_source: "pubchem-auto"` so a human confirms it before it drives a
real SDS — we never trust an unverified CAS in a safety document and we
never let an LLM guess one.

Fragrances / dyes / colorants are skipped (per instruction) and proprietary
trade blends are left without a CAS (they have none — use manual hazards).

Only empty `cas` fields are touched. Re-run `sync_db_stubs.py` afterwards.

Run:  python3 resolve_missing_cas.py
"""

from __future__ import annotations

import json
import re
import time
from pathlib import Path

import requests

BASE = Path(__file__).parent
IDX = BASE / "data" / "rm_index.json"
REVIEW = BASE / "data" / "sources" / "cas_resolved_review.txt"

_CAS = re.compile(r"^\d{2,7}-\d{2}-\d$")
_SKIP = re.compile(
    r"fragrance|dye|colou?r|permalon|rhodamine|keyacid|tricoblanc|caramel|"
    r"pigment|FD&C|D&C|scent|perfume|aroma|lavender|lavander|sea water|"
    r"cherry|citrus|floral|berry|melon|vanilla|musk|white tea", re.I)
_BLEND = re.compile(
    r"northquest|accusol|versaflex|probac|colamulse|tetranyl|nachurs|"
    r"greased lightening|all clean|sa-1000|opacifier|defoaming agent|"
    r"acid inhibitor|humi-flex|e-cryl|aquatreat|crown l60b|alcoguard|"
    r"accosoft|rheocare", re.I)
_GRADE = re.compile(
    r"(\d+(\.\d+)?\s*%|\btech(nical)? grade\b|\bfood grade\b|\bfg\b|\btg\b|"
    r"\bpowder\b|\bgranular\b|\bgranules?\b|\bcry\b|\bcrystal[s]?\b|\bliquid\b|"
    r"\bbulk\b|\blow metal[s]?\b|\bnd\b|\busp\b|\bfcc\b|\breagent\b|"
    r"\banhyd(rous)?\b|\bsolution\b|\baqueous\b|\bsoln\b|\(.*?\))", re.I)
# Supplier / sourcing tails: "..., Cal Chem provided", "provided by RMC", etc.
_SUPPLIER = re.compile(
    r"[,\-]?\s*(\(?\s*cal\s*chem.*$|provided.*$|by\s+rmc.*$|\bglob\d+.*$)", re.I)
# Brand suffix words that follow a generic chemical name.
_BRAND = re.compile(r"\b(sorbogem|sorbo|extract|killer)\b.*$", re.I)


def _normspell(s: str) -> str:
    return (s.replace("sulphite", "sulfite").replace("sulphate", "sulfate")
             .replace("Sulphite", "sulfite").replace("Sulphate", "sulfate"))


# Well-known substances PubChem name-search resolves poorly/ambiguously.
_OVERRIDE = {
    "xylene": "1330-20-7",
    "sodium persulfate": "7775-27-1",
    "potassium metabisulfite": "16731-55-8",
    "sodium hexametaphosphate": "10124-56-8",
    "sodium bisulfite": "7631-90-5",
    "sodium acetate": "127-09-3",
    "potassium chloride": "7447-40-7",
    "citric acid": "77-92-9",
    "edta acid": "60-00-4",
    "phosphoric acid": "7664-38-2",
    "calcium nitrite": "13780-06-8",
    "potassium hydroxide": "1310-58-3",
    "sorbitol": "50-70-4",
    "chitosan": "9012-76-4",
    "iodine": "7553-56-2",
}

_S = requests.Session()
_S.headers["User-Agent"] = "sds-generator-cas-resolver/1.0"


def _clean(name: str) -> str:
    n = _normspell(name)
    n = re.sub(r"[;/].*$", "", n)             # drop after ; or /
    n = _SUPPLIER.sub("", n)
    n = _BRAND.sub("", n)
    n = _GRADE.sub("", n)
    n = re.sub(r"[,\-]+\s*$", "", n).strip()
    return re.sub(r"\s{2,}", " ", n).strip()


def _pubchem_cas(name: str) -> str:
    try:
        r = _S.get("https://pubchem.ncbi.nlm.nih.gov/rest/pug/compound/name/"
                   f"{requests.utils.quote(name)}/cids/JSON", timeout=15)
        if r.status_code != 200:
            return ""
        cids = r.json().get("IdentifierList", {}).get("CID", [])
        if not cids:
            return ""
        sy = _S.get("https://pubchem.ncbi.nlm.nih.gov/rest/pug/compound/cid/"
                    f"{cids[0]}/synonyms/JSON", timeout=15).json()
        syns = (sy.get("InformationList", {}).get("Information", [{}])[0]
                  .get("Synonym", []))
        for x in syns:
            if _CAS.match(x):
                return x
    except Exception:
        return ""
    return ""


def main() -> None:
    idx = json.loads(IDX.read_text(encoding="utf-8"))
    resolved, skipped, blend, unresolved = [], [], [], []

    for rm, v in idx.items():
        if v.get("cas"):
            continue
        name = (v.get("name") or "").strip()
        syn = (v.get("synonyms") or "").strip()
        blob = f"{name} {syn}"

        if _SKIP.search(blob) or rm.upper().startswith("RM93"):
            v["cas_source"] = "skipped-colorant"
            skipped.append((rm, name))
            continue
        if _BLEND.search(blob) or name.upper() == rm.upper() or not name:
            v["cas_source"] = "proprietary-no-cas"
            v["needs_review"] = True
            blend.append((rm, name or "(no name)"))
            continue

        cleaned = _clean(name)
        cas = ""
        key = cleaned.lower().strip()
        for ok, ov in _OVERRIDE.items():        # curated, unambiguous
            if key == ok or key.startswith(ok):
                cas = ov
                break
        if not cas:
            for cand in (cleaned, name, _clean(syn) if syn else ""):
                if cand:
                    cas = _pubchem_cas(cand)
                    if cas:
                        break
                time.sleep(0.25)

        if cas:
            v["cas"] = cas
            v["cas_all"] = [cas]
            v["cas_source"] = "pubchem-auto"
            v["needs_review"] = True            # human must confirm
            resolved.append((rm, name, cas))
        else:
            v["cas_source"] = "unresolved"
            v["needs_review"] = True
            unresolved.append((rm, name))
        time.sleep(0.25)

    IDX.write_text(json.dumps(idx, ensure_ascii=False, indent=2), encoding="utf-8")

    # Report from the FULL final state (not just this run's actions) so the
    # list is complete and accurate no matter how many times this is run.
    auto = sorted((rm, v["name"], v["cas"]) for rm, v in idx.items()
                  if v.get("cas_source") == "pubchem-auto" and v.get("cas"))
    prop = sorted((rm, v["name"]) for rm, v in idx.items()
                  if v.get("cas_source") == "proprietary-no-cas")
    unr = sorted((rm, v["name"]) for rm, v in idx.items()
                 if v.get("cas_source") == "unresolved")
    skip_l = sorted((rm, v["name"]) for rm, v in idx.items()
                    if v.get("cas_source") == "skipped-colorant")
    curated = sorted((rm, v["name"]) for rm, v in idx.items()
                     if v.get("cas") and v.get("cas_source") not in
                     ("pubchem-auto",))

    lines = [
        f"CAS backfill (full state): auto-resolved {len(auto)} | "
        f"proprietary/no-CAS {len(prop)} | unresolved {len(unr)} | "
        f"colorant-skipped {len(skip_l)} | "
        f"already-had-CAS {len(curated)}",
        "",
        "== AUTO-RESOLVED via PubChem/override — CONFIRM BEFORE PRODUCTION ==",
        *[f"  {rm}  {nm}  ->  {c}" for rm, nm, c in auto],
        "",
        "== PROPRIETARY / BLEND (no single CAS — use manual hazards) ==",
        *[f"  {rm}  {nm}" for rm, nm in prop],
        "",
        "== UNRESOLVED (mixtures/extracts — manual lookup or manual hazards) ==",
        *[f"  {rm}  {nm}" for rm, nm in unr],
    ]
    REVIEW.write_text("\n".join(lines), encoding="utf-8")
    print(lines[0])
    print(f"Review list: {REVIEW}")


if __name__ == "__main__":
    main()
