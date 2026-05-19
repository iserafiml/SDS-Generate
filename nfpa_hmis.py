"""
Best-effort NFPA 704 and HMIS III ratings derived from the GHS
classification.

IMPORTANT: NFPA 704 / HMIS are NOT formally defined by GHS. This is the
industry-standard heuristic correlation also used by commercial SDS
authoring tools — conservative, and meant to be reviewed / overridable,
not an authoritative substitute for an NFPA/HMIS assessment.

derive() → {
  "nfpa": {"health":int, "flammability":int, "instability":int, "special":str},
  "hmis": {"health":int, "flammability":int, "physical":int, "chronic":bool},
  "derived": True,
}
"""

from __future__ import annotations

import re

_CHRONIC = {
    "carcinogenicity", "germ cell mutagenicity", "reproductive toxicity",
    "respiratory sensitization", "skin sensitization",
    "specific target organ toxicity - repeated exposure",
}
_SEV = {"1": 0, "1A": 0, "1B": 1, "1C": 2, "2": 3, "3": 6, "4": 9, "5": 12}


def _cat_map(name: str, cats: dict) -> int:
    """Highest (most severe) category number seen for a class name token."""
    return cats.get(name, 99)


def _flammability(classes: dict, flash_point: str) -> int:
    """NFPA/HMIS flammability 0-4 from GHS flammable-liquid category, else
    the flash point if a number is available."""
    cat = classes.get("flammable liquids")
    if cat:
        return {"1": 4, "2": 3, "3": 2, "4": 1}.get(cat, 0)
    m = re.search(r"(-?\d+(?:\.\d+)?)\s*°?\s*c", (flash_point or "").lower())
    if m:
        fp = float(m.group(1))
        if fp < 22.8:
            return 3 if fp >= -5 else 4
        if fp < 37.8:
            return 3
        if fp < 60:
            return 2
        if fp < 93.3:
            return 2
        return 1
    return 0


def _health(classes: dict) -> int:
    h = 0
    ato = classes.get("acute toxicity - oral")
    ati = classes.get("acute toxicity - inhalation")
    atd = classes.get("acute toxicity - dermal")
    for c in (ato, ati, atd):
        if c == "1":
            h = max(h, 4)
        elif c == "2":
            h = max(h, 3)
        elif c == "3":
            h = max(h, 3)
        elif c == "4":
            h = max(h, 2)
    if "skin corrosion" in classes or "serious eye damage" in classes:
        h = max(h, 3)
    se = classes.get("specific target organ toxicity - single exposure, "
                     "respiratory tract irritation") or classes.get("stot_se")
    if se == "1":
        h = max(h, 3)
    elif se == "2":
        h = max(h, 2)
    elif se == "3":
        h = max(h, 1)
    if any(k in classes for k in _CHRONIC):
        h = max(h, 2)
    return h


def derive(classification, physical_properties=None) -> dict:
    # class_name (lower) -> most severe category string
    classes: dict[str, str] = {}
    for cat in getattr(classification, "categories", []) or []:
        key = (cat.class_name or "").strip().lower()
        cur = classes.get(key)
        if cur is None or _SEV.get(str(cat.category), 99) < _SEV.get(str(cur), 99):
            classes[key] = str(cat.category)

    flash = getattr(physical_properties, "flash_point", "") if physical_properties else ""
    health = _health(classes)
    flam = _flammability(classes, flash)

    is_ox = any("oxidiz" in k for k in classes)
    # NFPA instability: no self-reactive/explosive data available → 0.
    nfpa_inst = 0
    special = "OX" if is_ox else ""
    # HMIS physical hazard: oxidiser is the main signal we can infer.
    hmis_phys = 0
    if is_ox:
        ox_cat = next((v for k, v in classes.items() if "oxidiz" in k), "3")
        hmis_phys = {"1": 3, "2": 2, "3": 1}.get(str(ox_cat), 1)

    chronic = any(k in classes for k in _CHRONIC)

    return {
        "nfpa": {"health": health, "flammability": flam,
                 "instability": nfpa_inst, "special": special},
        "hmis": {"health": health, "flammability": flam,
                 "physical": hmis_phys, "chronic": chronic},
        "derived": True,
    }


def parse_override(nfpa_s: str, hmis_s: str) -> dict | None:
    """Parse manual overrides like '3-0-2 OX' / '3*-0-1'. Returns None if
    both blank so the caller falls back to derive()."""
    nfpa_s = (nfpa_s or "").strip()
    hmis_s = (hmis_s or "").strip()
    if not nfpa_s and not hmis_s:
        return None
    out = derive(type("X", (), {"categories": []})())  # zeroed scaffold

    def _nums(s):
        return [int(x) for x in re.findall(r"\d", s)][:3]

    if nfpa_s:
        n = _nums(nfpa_s)
        if len(n) >= 1: out["nfpa"]["health"] = n[0]
        if len(n) >= 2: out["nfpa"]["flammability"] = n[1]
        if len(n) >= 3: out["nfpa"]["instability"] = n[2]
        sp = re.search(r"\b(OX|OXY|W|SA)\b", nfpa_s, re.I)
        out["nfpa"]["special"] = sp.group(0).upper() if sp else ""
    if hmis_s:
        n = _nums(hmis_s)
        if len(n) >= 1: out["hmis"]["health"] = n[0]
        if len(n) >= 2: out["hmis"]["flammability"] = n[1]
        if len(n) >= 3: out["hmis"]["physical"] = n[2]
        out["hmis"]["chronic"] = "*" in hmis_s
        out["nfpa"]["health"] = out["nfpa"]["health"] or n[0] if n else out["nfpa"]["health"]
    out["derived"] = False
    return out


if __name__ == "__main__":
    class _C:  # boiler-like: corrosive + carcinogen, non-flammable
        categories = [
            type("X", (), {"class_name": "Skin corrosion", "category": "1"})(),
            type("X", (), {"class_name": "Serious eye damage", "category": "1"})(),
            type("X", (), {"class_name": "Carcinogenicity", "category": "1B"})(),
            type("X", (), {"class_name": "Acute toxicity - oral", "category": "4"})(),
        ]
    import json
    print(json.dumps(derive(_C()), indent=2))
