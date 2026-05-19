"""
AI enrichment layer for the chemical database.

Most records in data/raw_material_db.json have `ghs_triggers` and a `regulatory`
skeleton but no `oels`, `toxicology`, `aquatic_toxicology`, persistence/
bioaccumulation/mobility, or curated IARC/NTP/Prop-65 data. That is why
Sections 8/11/12/15 of generated SDSs come out blank and the California
Prop 65 warning for substances like cobalt sulfate is missed.

`enrich_chemical()` fills only the empty fields of one record via Claude and
returns the updated record plus a flag indicating whether anything changed.
`persist_db()` writes the in-memory CAS-indexed dict back to the JSON file
(as a list, preserving the original structure) using an atomic replace.

A record is only ever sent to Claude once: after a successful pass it is
stamped with `_ai_enriched: true` so subsequent generations are free and
hand-curated edits are never overwritten.
"""

from __future__ import annotations

import json
import os
import tempfile
from datetime import date, datetime
from pathlib import Path

# Enrichment provenance / re-verification policy.
#   - Bump SCHEMA_VERSION when the enrichment shape changes (forces a one-time
#     re-verify of every record so new fields get populated).
#   - A record is re-sent to Claude when its stored enrichment is older than
#     REVERIFY_AFTER_DAYS, was produced by a different model, or predates the
#     current schema. The long TTL tracks regulatory drift (Prop 65 / IARC /
#     OEL updates ~ yearly) — re-asking the same model more often than that
#     adds cost and nondeterminism without improving accuracy.
ENRICHMENT_SCHEMA_VERSION = 2
CURRENT_MODEL = "claude-sonnet-4-6"
REVERIFY_AFTER_DAYS = 365

# Data fields that are filled per-field only when empty (protects curated data
# such as the hand-entered peracetic-acid record).
_DATA_FIELDS = (
    "oels",
    "toxicology",
    "aquatic_toxicology",
    "persistence",
    "bioaccumulation",
    "mobility",
)

_REG_KEYS = (
    "tsca_listed", "sara_302", "sara_302_tpq_lbs", "sara_313",
    "cercla_listed", "cercla_rq_lbs", "rcra_code", "caa_112r",
    "prop_65", "prop_65_warning", "rtk_states",
)


def _is_empty(value) -> bool:
    if value is None:
        return True
    if isinstance(value, str):
        return value.strip() == ""
    if isinstance(value, (list, dict)):
        return len(value) == 0
    return False


def _aquatic_empty(value) -> bool:
    if not isinstance(value, dict):
        return True
    return not value.get("acute") and not value.get("chronic")


def _regulatory_is_skeleton(reg: dict) -> bool:
    """True when the regulatory block is the uncurated default (all off).

    Curated records (e.g. peracetic acid has sara_302=True) fail this test and
    are preserved untouched.
    """
    if not isinstance(reg, dict) or not reg:
        return True
    return not any([
        reg.get("sara_302"), reg.get("sara_313"), reg.get("cercla_listed"),
        reg.get("cercla_rq_lbs"), reg.get("caa_112r"), reg.get("prop_65"),
        reg.get("prop_65_warning"), reg.get("rtk_states"),
    ])


def _enrichment_age_days(meta: dict) -> float:
    try:
        d = datetime.fromisoformat(meta["date"]).date()
        return (date.today() - d).days
    except Exception:
        return 1e9          # unparseable → treat as very old


def needs_enrichment(record: dict) -> bool:
    """Whether this record should be (re-)sent to Claude.

    Re-verification is driven by provenance, not by re-asking on a short timer:
    a record is refreshed only when its enrichment is missing, hand-unlocked
    and stale (> REVERIFY_AFTER_DAYS), produced by a different model, or
    predates the current schema version. Records marked `_locked` (curated /
    reviewed) are never overwritten.
    """
    if record.get("_locked"):
        return False

    meta = record.get("_enrichment")
    if not isinstance(meta, dict):
        # Legacy boolean stamp → re-verify once to attach metadata + new
        # schema fields (e.g. health-hazard GHS triggers added in v2).
        return True

    if meta.get("v") != ENRICHMENT_SCHEMA_VERSION:
        return True
    if meta.get("model") != CURRENT_MODEL:
        return True
    if _enrichment_age_days(meta) > REVERIFY_AFTER_DAYS:
        return True
    return False


# Schema example shown to the model (the one curated record in the DB).
_SCHEMA_EXAMPLE = {
    "oels": [{"authority": "ACGIH", "type": "STEL", "value": "0.4", "unit": "ppm"}],
    "toxicology": {
        "oral_ld50": {"route": "oral", "species": "Rat", "result": "LD50 Rat: 80 mg/kg"},
        "dermal_ld50": {"route": "dermal", "species": "Rabbit", "result": "LD50 Rabbit: 60 mg/kg"},
        "inhalation_lc50": {"route": "inhalation", "species": "Rat", "result": "LC50 Rat: 0.2 mg/L (4 hr [aerosol])"},
        "skin_result": "Causes severe skin burns.",
        "eye_result": "Causes serious eye damage.",
        "stot_result": "",
    },
    "aquatic_toxicology": {
        "acute": [{"type": "Fish", "organism": "Oncorhynchus mykiss", "metric": "LC50",
                   "value": "0.53 mg/L", "duration_hr": 96, "endpoint": ""}],
        "chronic": [{"type": "Aquatic Invertebrates", "organism": "Daphnia magna",
                     "metric": "NOEC", "value": "0.012 mg/L", "duration_days": 21, "endpoint": ""}],
    },
    "persistence": "The substance is readily biodegradable in water...",
    "bioaccumulation": "The substance is not expected to bioaccumulate [BCF: 1.61].",
    "mobility": "The substance is highly mobile (Koc: 1.5 L/kg).",
    "iarc_classification": "Not Applicable",
    "ntp_classification": "Not Applicable",
    "regulatory": {
        "tsca_listed": True, "sara_302": True, "sara_302_tpq_lbs": "500",
        "sara_313": True, "cercla_listed": False, "cercla_rq_lbs": "",
        "rcra_code": "", "caa_112r": True, "prop_65": False,
        "prop_65_warning": "", "rtk_states": ["MA", "NJ", "NY", "PA"],
    },
    "ghs_health_triggers": {
        "carcinogenicity":           {"threshold_pct": 0.1, "category": "1B"},
        "germ_cell_mutagenicity":    {"threshold_pct": 0.1, "category": "2"},
        "reproductive_toxicity":     {"threshold_pct": 0.1, "category": "1B"},
        "respiratory_sensitization": {"threshold_pct": 0.1, "category": "1"},
        "skin_sensitization":        {"threshold_pct": 0.1, "category": "1"},
        "stot_re":                   {"threshold_pct": 1.0, "category": "2"},
        "aspiration":                {"threshold_pct": 10.0, "category": "1"},
    },
}

# GHS health-hazard classes the classifier understands (used to merge enrichment
# output into a record's ghs_triggers so they reach Section 2 + pictograms).
_HEALTH_TRIGGER_KEYS = (
    "carcinogenicity", "germ_cell_mutagenicity", "reproductive_toxicity",
    "respiratory_sensitization", "skin_sensitization", "stot_re", "aspiration",
)

_SYSTEM_PROMPT = (
    "You are a regulatory toxicology data specialist compiling authoritative "
    "Safety Data Sheet reference data for a single pure chemical substance. "
    "Draw on ACGIH/OSHA/NIOSH exposure limits, ECHA/GESTIS toxicology, OECD "
    "ecotoxicology, IARC and NTP monographs, the EPA TSCA/SARA/CERCLA/RCRA/CAA "
    "lists, and the California OEHHA Proposition 65 list. "
    "Return ONLY one valid JSON object with EXACTLY these keys: oels, "
    "toxicology, aquatic_toxicology, persistence, bioaccumulation, mobility, "
    "iarc_classification, ntp_classification, regulatory, ghs_health_triggers. "
    "Match the example schema exactly (same nested keys and value types; all "
    "leaf values that are not booleans/numbers/arrays are strings). "
    "Critical rules: (1) Only state data you are confident is correct for THIS "
    "CAS. (2) If a value is genuinely unknown or not applicable, use an empty "
    "string / empty list / \"Not Applicable\" — never invent numbers. "
    "(3) For known carcinogens give the real IARC group (e.g. \"Group 2B\") "
    "and set regulatory.prop_65=true with a prop_65_warning naming the "
    "chemical and effect when it is on the California Prop 65 list "
    "(cobalt and cobalt compounds, for example, are listed as carcinogens). "
    "(4) Format toxicology result strings like \"LD50 Rat: 325 mg/kg\". "
    "(5) ghs_health_triggers: include ONLY the health-hazard classes this "
    "substance actually carries under GHS/OSHA HCS 2012 (omit the rest "
    "entirely — do NOT include classes that do not apply). For each included "
    "class give its GHS sub-category (carcinogenicity/mutagenicity/"
    "reproductive_toxicity: \"1A\"/\"1B\"/\"2\"; sensitizers: \"1\"/\"1A\"/"
    "\"1B\"; stot_re: \"1\"/\"2\"; aspiration: \"1\") and threshold_pct = the "
    "GHS mixture generic concentration limit (carcinogen/mutagen/repro Cat 1 = "
    "0.1, Cat 2 = 1.0; respiratory & skin sensitizer = 0.1; STOT-RE Cat 1 = "
    "1.0, Cat 2 = 10.0; aspiration = 10.0). A cobalt(II) salt, for example, "
    "has carcinogenicity 1B at 0.1. No markdown, no commentary."
)


def enrich_chemical(client, record: dict, *, model: str = CURRENT_MODEL) -> tuple[dict, bool]:
    """Fill empty fields of `record` via Claude. Returns (record, changed)."""
    if not needs_enrichment(record):
        return record, False

    syn = record.get("synonyms") or []
    user_msg = (
        f"CAS Number: {record.get('cas', '')}\n"
        f"Chemical Name: {record.get('name', '')}\n"
        f"Synonyms: {', '.join(syn) if syn else '(none)'}\n\n"
        "Schema example (structure only — values must be specific to the CAS "
        "above):\n"
        f"{json.dumps(_SCHEMA_EXAMPLE, ensure_ascii=False)}\n\n"
        "Return the JSON object for this substance now."
    )

    try:
        resp = client.messages.create(
            model=model,
            max_tokens=2600,
            system=[{
                "type": "text",
                "text": _SYSTEM_PROMPT,
                "cache_control": {"type": "ephemeral"},
            }],
            messages=[{"role": "user", "content": user_msg}],
        )
        raw = resp.content[0].text.strip()
        start, end = raw.find("{"), raw.rfind("}")
        data = json.loads(raw[start:end + 1] if start != -1 and end > start else raw)
    except Exception as e:  # noqa: BLE001 — enrichment must never break generation
        print(f"[WARNING] DB enrichment failed for {record.get('cas')}: {e}")
        return record, False

    changed = False

    # Per-field fill: only when the existing field is empty (protects curated data).
    for f in _DATA_FIELDS:
        incoming = data.get(f)
        if incoming in (None, "", [], {}):
            continue
        cur = record.get(f)
        is_empty = _aquatic_empty(cur) if f == "aquatic_toxicology" else _is_empty(cur)
        if is_empty:
            record[f] = incoming
            changed = True

    # IARC / NTP: replace the uncurated "Not Applicable" / missing default.
    for f in ("iarc_classification", "ntp_classification"):
        incoming = data.get(f)
        if isinstance(incoming, str) and incoming.strip() \
                and record.get(f, "") in ("", "Not Applicable"):
            if incoming.strip() != record.get(f, ""):
                record[f] = incoming.strip()
                changed = True

    # Regulatory: replace the whole block only if it is the uncurated skeleton.
    inc_reg = data.get("regulatory")
    if isinstance(inc_reg, dict) and _regulatory_is_skeleton(record.get("regulatory", {})):
        merged = dict(record.get("regulatory") or {})
        for k in _REG_KEYS:
            if k in inc_reg:
                merged[k] = inc_reg[k]
        if merged != record.get("regulatory"):
            record["regulatory"] = merged
            changed = True

    # Merge health-hazard GHS triggers so carcinogenicity, sensitization, etc.
    # reach Section 2 + pictograms via the normal classifier path. Only add a
    # class the record does not already declare (never override curated triggers).
    inc_health = data.get("ghs_health_triggers")
    if isinstance(inc_health, dict):
        trig = record.setdefault("ghs_triggers", {})
        for cls in _HEALTH_TRIGGER_KEYS:
            spec = inc_health.get(cls)
            if cls in trig or not isinstance(spec, dict):
                continue
            try:
                trig[cls] = {
                    "threshold_pct": float(spec["threshold_pct"]),
                    "category": str(spec["category"]),
                }
                changed = True
            except (KeyError, TypeError, ValueError):
                continue

    # Stamp provenance (date + model + schema version). Always report dirty so
    # the stamp persists; remove the legacy boolean flag on migration.
    record.pop("_ai_enriched", None)
    record["_enrichment"] = {
        "date": date.today().isoformat(),
        "model": model,
        "v": ENRICHMENT_SCHEMA_VERSION,
    }
    return record, True

# `changed` is computed for diagnostics only; a completed pass always persists.


def persist_db(db_index: dict[str, dict], path: str | Path) -> None:
    """Write the CAS-indexed dict back to `path` as a JSON list (atomic)."""
    records = list(db_index.values())
    path = Path(path)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=".rmdb_", suffix=".json")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(records, f, ensure_ascii=False, indent=2)
        os.replace(tmp, path)
    except Exception:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise
