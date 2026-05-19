"""
GHS Classification Engine — The Logic Center.

Determines GHS hazard categories from ingredient concentrations, then selects
H-statements, P-statements, signal word, and pictogram codes automatically.

Classification uses the UPPER bound of each ingredient's concentration range
(wt_percent_high) for worst-case, safety-conservative assessment per GHS rules.
"""

from __future__ import annotations

from sds_data_model import GHSClassification, GHSHazardCategory, SDSIngredient


# ---------------------------------------------------------------------------
# GHS Hazard Class display names
# ---------------------------------------------------------------------------

_CLASS_DISPLAY = {
    "oxidizing_liquid":    "Oxidizing liquids",
    "organic_peroxides":   "Organic peroxides",
    "corrosive_to_metals": "Corrosive to metals",
    "skin_corrosion":      "Skin corrosion",
    "serious_eye_damage":  "Serious eye damage",
    "stot_se":             "Specific target organ toxicity - single exposure, respiratory tract irritation",
    "flammable_liquid":    "Flammable liquids",
    "acute_toxicity_oral": "Acute toxicity - oral",
    "acute_toxicity_inh":  "Acute toxicity - inhalation",
    "environmental":       "Hazardous to the aquatic environment",
    "carcinogenicity":         "Carcinogenicity",
    "germ_cell_mutagenicity":  "Germ cell mutagenicity",
    "reproductive_toxicity":   "Reproductive toxicity",
    "respiratory_sensitization": "Respiratory sensitization",
    "skin_sensitization":      "Skin sensitization",
    "stot_re":                 "Specific target organ toxicity - repeated exposure",
    "aspiration":              "Aspiration hazard",
}

# Pictogram code per hazard class
_PICTOGRAM_MAP = {
    "oxidizing_liquid":    "GHS03",  # flame over circle
    "organic_peroxides":   "GHS02",  # flame (Type A/B also add GHS01 below)
    "corrosive_to_metals": "GHS05",  # corrosion
    "skin_corrosion":      "GHS05",
    "serious_eye_damage":  "GHS05",
    "stot_se":             "GHS07",  # exclamation mark
    "flammable_liquid":    "GHS02",  # flame
    "acute_toxicity_oral": "GHS06",  # skull
    "acute_toxicity_inh":  "GHS06",
    "environmental":       "GHS09",  # environment
    "carcinogenicity":         "GHS08",  # serious health hazard
    "germ_cell_mutagenicity":  "GHS08",
    "reproductive_toxicity":   "GHS08",
    "respiratory_sensitization": "GHS08",
    "skin_sensitization":      "GHS07",  # exclamation mark
    "stot_re":                 "GHS08",
    "aspiration":              "GHS08",
}

# H-codes per (hazard_class, category)
_CATEGORY_H_CODES: dict[str, list[str]] = {
    "organic_peroxides_A":   ["H240"],
    "organic_peroxides_B":   ["H241"],
    "organic_peroxides_C":   ["H242"],
    "organic_peroxides_D":   ["H242"],
    "organic_peroxides_E":   ["H242"],
    "organic_peroxides_F":   ["H242"],
    "organic_peroxides_G":   [],
    "oxidizing_liquid_1":    ["H271"],
    "oxidizing_liquid_2":    ["H272"],
    "oxidizing_liquid_3":    ["H272"],
    "corrosive_to_metals_1": ["H290"],
    "skin_corrosion_1":      ["H314"],
    "skin_corrosion_1A":     ["H314"],
    "skin_corrosion_1B":     ["H314"],
    "skin_corrosion_1C":     ["H314"],
    "skin_corrosion_2":      ["H315"],
    "serious_eye_damage_1":  ["H318"],
    "serious_eye_damage_2":  ["H319"],
    "stot_se_1":             ["H370"],
    "stot_se_2":             ["H371"],
    "stot_se_3":             ["H335"],
    "flammable_liquid_1":    ["H224"],
    "flammable_liquid_2":    ["H225"],
    "flammable_liquid_3":    ["H226"],
    "flammable_liquid_4":    ["H227"],
    "carcinogenicity_1":     ["H350"],
    "carcinogenicity_1A":    ["H350"],
    "carcinogenicity_1B":    ["H350"],
    "carcinogenicity_2":     ["H351"],
    "germ_cell_mutagenicity_1":  ["H340"],
    "germ_cell_mutagenicity_1A": ["H340"],
    "germ_cell_mutagenicity_1B": ["H340"],
    "germ_cell_mutagenicity_2":  ["H341"],
    "reproductive_toxicity_1":   ["H360"],
    "reproductive_toxicity_1A":  ["H360"],
    "reproductive_toxicity_1B":  ["H360"],
    "reproductive_toxicity_2":   ["H361"],
    "respiratory_sensitization_1":  ["H334"],
    "respiratory_sensitization_1A": ["H334"],
    "respiratory_sensitization_1B": ["H334"],
    "skin_sensitization_1":  ["H317"],
    "skin_sensitization_1A": ["H317"],
    "skin_sensitization_1B": ["H317"],
    "stot_re_1":             ["H372"],
    "stot_re_2":             ["H373"],
    "aspiration_1":          ["H304"],
}

# P-codes per (hazard_class, category) — using combined codes as written on labels
_CATEGORY_P_CODES: dict[str, list[str]] = {
    "organic_peroxides_F": ["P210", "P220", "P234", "P280", "P370+P378",
                            "P403+P235", "P411", "P420", "P501"],
    "oxidizing_liquid_2": [
        "P210", "P220", "P221", "P260", "P264", "P270", "P271", "P280",
        "P301+P330+P331", "P303+P361+P353", "P304+P340",
        "P305+P351+P338", "P310", "P312", "P321", "P370+P378",
        "P405", "P406", "P501",
    ],
    "corrosive_to_metals_1": ["P234", "P390", "P404", "P406"],
    "skin_corrosion_1A": [
        "P260", "P264", "P280",
        "P301+P330+P331", "P303+P361+P353", "P304+P340",
        "P305+P351+P338", "P310", "P321", "P363", "P405", "P501",
    ],
    "skin_corrosion_1":  [
        "P260", "P264", "P280",
        "P301+P330+P331", "P303+P361+P353", "P305+P351+P338",
        "P310", "P321", "P405", "P501",
    ],
    "serious_eye_damage_1": ["P280", "P305+P351+P338", "P310"],
    "stot_se_3": ["P260", "P261", "P271", "P304+P340", "P312"],
    "flammable_liquid_3": ["P210", "P233", "P240", "P241", "P242", "P243",
                           "P264", "P270", "P272", "P280", "P303+P361+P353",
                           "P370+P378", "P403+P235", "P501"],
    "carcinogenicity_1":  ["P201", "P202", "P280", "P308+P313", "P405", "P501"],
    "carcinogenicity_2":  ["P201", "P202", "P280", "P308+P313", "P405", "P501"],
    "germ_cell_mutagenicity_1": ["P201", "P202", "P280", "P308+P313", "P405", "P501"],
    "germ_cell_mutagenicity_2": ["P201", "P202", "P280", "P308+P313", "P405", "P501"],
    "reproductive_toxicity_1":  ["P201", "P202", "P280", "P308+P313", "P405", "P501"],
    "reproductive_toxicity_2":  ["P201", "P202", "P280", "P308+P313", "P405", "P501"],
    "respiratory_sensitization_1": ["P261", "P280", "P304+P340", "P342+P311", "P501"],
    "skin_sensitization_1": ["P261", "P272", "P280", "P302+P352", "P333+P313",
                             "P363", "P501"],
    "stot_re_1": ["P260", "P264", "P270", "P314", "P501"],
    "stot_re_2": ["P260", "P264", "P270", "P314", "P501"],
    "aspiration_1": ["P301+P310", "P331", "P405", "P501"],
}

# Full H-statement text
H_STATEMENTS: dict[str, str] = {
    "H224": "Extremely flammable liquid and vapour",
    "H225": "Highly flammable liquid and vapour",
    "H226": "Flammable liquid and vapour",
    "H227": "Combustible liquid",
    "H240": "Heating may cause an explosion",
    "H241": "Heating may cause a fire or explosion",
    "H242": "Heating may cause a fire",
    "H271": "May cause fire or explosion; strong oxidizer",
    "H272": "May intensify fire; oxidizer",
    "H290": "May be corrosive to metals",
    "H300": "Fatal if swallowed",
    "H301": "Toxic if swallowed",
    "H302": "Harmful if swallowed",
    "H310": "Fatal in contact with skin",
    "H311": "Toxic in contact with skin",
    "H312": "Harmful in contact with skin",
    "H314": "Causes severe skin burns and eye damage",
    "H315": "Causes skin irritation",
    "H317": "May cause an allergic skin reaction",
    "H318": "Causes serious eye damage",
    "H319": "Causes serious eye irritation",
    "H330": "Fatal if inhaled",
    "H331": "Toxic if inhaled",
    "H332": "Harmful if inhaled",
    "H334": "May cause allergy or asthma symptoms or breathing difficulties if inhaled",
    "H335": "May cause respiratory irritation",
    "H336": "May cause drowsiness or dizziness",
    "H304": "May be fatal if swallowed and enters airways",
    "H340": "May cause genetic defects",
    "H341": "Suspected of causing genetic defects",
    "H350": "May cause cancer",
    "H351": "Suspected of causing cancer",
    "H360": "May damage fertility or the unborn child",
    "H361": "Suspected of damaging fertility or the unborn child",
    "H362": "May cause harm to breast-fed children",
    "H370": "Causes damage to organs",
    "H371": "May cause damage to organs",
    "H372": "Causes damage to organs through prolonged or repeated exposure",
    "H373": "May cause damage to organs through prolonged or repeated exposure",
    "H400": "Very toxic to aquatic life",
    "H410": "Very toxic to aquatic life with long lasting effects",
    "H411": "Toxic to aquatic life with long lasting effects",
    "H412": "Harmful to aquatic life with long lasting effects",
    "H413": "May cause long lasting harmful effects to aquatic life",
}

# Full P-statement text (selected subset covering OxyStrike and common chemicals)
P_STATEMENTS: dict[str, str] = {
    "P210":          "Keep away from heat, hot surfaces, sparks, open flames and other ignition sources. No smoking.",
    "P220":          "Keep/Store away from clothing/…/combustible materials.",
    "P221":          "Take any precaution to avoid mixing with combustibles/…",
    "P201":          "Obtain special instructions before use.",
    "P202":          "Do not handle until all safety precautions have been read and understood.",
    "P233":          "Keep container tightly closed.",
    "P234":          "Keep only in original container.",
    "P240":          "Ground and bond container and receiving equipment.",
    "P241":          "Use explosion-proof electrical/ventilating/lighting equipment.",
    "P242":          "Use non-sparking tools.",
    "P243":          "Take precautionary measures against static discharge.",
    "P260":          "Do not breathe dust/fume/gas/mist/vapors/spray.",
    "P261":          "Avoid breathing dust/fume/gas/mist/vapors/spray.",
    "P264":          "Wash … thoroughly after handling.",
    "P270":          "Do not eat, drink or smoke when using this product.",
    "P271":          "Use only outdoors or in a well-ventilated area.",
    "P272":          "Contaminated work clothing should not be allowed out of the workplace.",
    "P273":          "Avoid release to the environment.",
    "P280":          "Wear protective gloves/protective clothing/eye protection/face protection.",
    "P301+P310":     "IF SWALLOWED: Immediately call a POISON CENTER/doctor.",
    "P301+P330+P331":"IF SWALLOWED: Rinse mouth. Do NOT induce vomiting.",
    "P302+P352":     "IF ON SKIN: Wash with plenty of water/soap.",
    "P303+P361+P353":"IF ON SKIN (or hair): Take off immediately all contaminated clothing. Rinse skin with water/shower.",
    "P304+P340":     "IF INHALED: Remove victim to fresh air and keep at rest in a position comfortable for breathing.",
    "P308+P313":     "IF exposed or concerned: Get medical advice/attention.",
    "P314":          "Get medical advice/attention if you feel unwell.",
    "P331":          "Do NOT induce vomiting.",
    "P333+P313":     "If skin irritation or rash occurs: Get medical advice/attention.",
    "P342+P311":     "If experiencing respiratory symptoms: Call a POISON CENTER/doctor.",
    "P305+P351+P338":"IF IN EYES: Rinse cautiously with water for several minutes. Remove contact lenses, if present and easy to do. Continue rinsing.",
    "P310":          "Immediately call a POISON CENTER/doctor.",
    "P312":          "Call a POISON CENTER/doctor if you feel unwell.",
    "P321":          "Specific treatment (see supplemental first aid instructions on this label).",
    "P330":          "Rinse mouth.",
    "P363":          "Wash contaminated clothing before reuse.",
    "P370+P378":     "In case of fire: Use appropriate media to extinguish.",
    "P390":          "Absorb spillage to prevent material damage.",
    "P391":          "Collect spillage.",
    "P403+P235":     "Store in a well-ventilated place. Keep cool.",
    "P411":          "Store at temperatures not exceeding the recommended maximum.",
    "P420":          "Store separately.",
    "P404":          "Store in a closed container.",
    "P405":          "Store locked up.",
    "P406":          "Store in a corrosive resistant/… container with a resistant inner liner.",
    "P501":          "Dispose of contents/container in accordance with local/national regulations.",
}

# Category severity ranking — lower number = more severe
_SEVERITY: dict[str, int] = {
    "1":  0, "1A": 0, "1B": 1, "1C": 2,
    "2":  3, "3":  6, "4":  9,
    # organic-peroxide types A (most severe) → G (least)
    "A": 0, "B": 1, "C": 2, "D": 3, "E": 4, "F": 5, "G": 6,
}

# Organic-peroxide types whose signal word is DANGER (E/F → WARNING, G → none)
_ORG_PEROX_DANGER = {"A", "B", "C", "D"}

# Hazard classes where Cat 1 or Cat 2 → DANGER; Cat 3+ → WARNING
_DANGER_CLASSES = {"oxidizing_liquid", "skin_corrosion", "serious_eye_damage",
                   "corrosive_to_metals", "flammable_liquid",
                   "acute_toxicity_oral", "acute_toxicity_inh"}

# Health classes: signal word depends on the specific category.
# Categories listed here are DANGER; any other category for the class → WARNING.
_HEALTH_DANGER_CATS = {
    "carcinogenicity":           {"1", "1A", "1B"},
    "germ_cell_mutagenicity":    {"1", "1A", "1B"},
    "reproductive_toxicity":     {"1", "1A", "1B"},
    "respiratory_sensitization": {"1", "1A", "1B"},
    "stot_re":                   {"1"},
    "aspiration":                {"1"},
}

# Public menu for the interactive wizard — only classes with H/P code entries defined above
HAZARD_MENU: list[dict] = [
    {"display": "Oxidizing liquids",         "key": "oxidizing_liquid",    "categories": ["1", "2", "3"]},
    {"display": "Organic peroxides",          "key": "organic_peroxides",   "categories": ["A", "B", "C", "D", "E", "F", "G"]},
    {"display": "Flammable liquids",          "key": "flammable_liquid",    "categories": ["1", "2", "3", "4"]},
    {"display": "Skin corrosion/irritation",  "key": "skin_corrosion",      "categories": ["1A", "1B", "1C", "2"]},
    {"display": "Serious eye damage",         "key": "serious_eye_damage",  "categories": ["1", "2"]},
    {"display": "STOT - single exposure",     "key": "stot_se",             "categories": ["1", "2", "3"]},
    {"display": "Corrosive to metals",        "key": "corrosive_to_metals", "categories": ["1"]},
    {"display": "Acute toxicity - oral",      "key": "acute_toxicity_oral", "categories": ["1", "2", "3", "4", "5"]},
    {"display": "Acute toxicity - inhalation","key": "acute_toxicity_inh",  "categories": ["1", "2", "3", "4", "5"]},
    {"display": "Hazardous to aquatic env",   "key": "environmental",       "categories": ["1", "2", "3", "4"]},
    {"display": "Carcinogenicity",            "key": "carcinogenicity",         "categories": ["1A", "1B", "2"]},
    {"display": "Germ cell mutagenicity",     "key": "germ_cell_mutagenicity",  "categories": ["1A", "1B", "2"]},
    {"display": "Reproductive toxicity",      "key": "reproductive_toxicity",   "categories": ["1A", "1B", "2"]},
    {"display": "Respiratory sensitization",  "key": "respiratory_sensitization", "categories": ["1", "1A", "1B"]},
    {"display": "Skin sensitization",         "key": "skin_sensitization",      "categories": ["1", "1A", "1B"]},
    {"display": "STOT - repeated exposure",   "key": "stot_re",                 "categories": ["1", "2"]},
    {"display": "Aspiration hazard",          "key": "aspiration",              "categories": ["1"]},
]


def build_manual_category(hazard_class: str, category: str) -> "GHSHazardCategory":
    """Build a GHSHazardCategory for a manually-specified hazard class and category."""
    key = f"{hazard_class}_{category}"
    h_codes = _CATEGORY_H_CODES.get(key, _CATEGORY_H_CODES.get(f"{hazard_class}_1", []))
    p_codes = _CATEGORY_P_CODES.get(key, _CATEGORY_P_CODES.get(f"{hazard_class}_1", []))
    pic = _PICTOGRAM_MAP.get(hazard_class, "")
    display = next((e["display"] for e in HAZARD_MENU if e["key"] == hazard_class), hazard_class)
    return GHSHazardCategory(
        class_name=_CLASS_DISPLAY.get(hazard_class, display),
        category=category,
        h_codes=list(h_codes),
        p_codes=list(p_codes),
        pictogram_codes=[pic] if pic else [],
    )


class GHSClassifier:
    """
    Classifies a mixture of ingredients into GHS hazard categories.

    Usage:
        import json
        db = {r["cas"]: r for r in json.load(open("data/raw_material_db.json"))}
        clf = GHSClassifier(db)
        result = clf.classify(ingredients)
    """

    def __init__(self, db: dict[str, dict]):
        self._db = db

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def classify(self, ingredients: list[SDSIngredient],
                 physical_properties=None) -> GHSClassification:
        """Return a fully populated GHSClassification for the ingredient mixture.

        `physical_properties` (optional) lets the mixture-property rule use the
        product flash point; flammability is a property of the *mixture*, not
        an additive cut-off, so it is suppressed for aqueous / oxidiser /
        organic-peroxide systems with no low-flash evidence.
        """
        # Step 1: determine worst-case triggered hazard class → (category, trigger name)
        triggered: dict[str, tuple[str, str]] = {}
        evaluated: list[str] = []     # ingredients with a DB record (known)
        hazardous: list[str] = []     # subset that triggered ≥1 hazard

        for ing in ingredients:
            rec = self._db.get(ing.cas_number.strip())
            if not rec:
                continue
            # Upper concentration bound (conservative). When the record's
            # GHS thresholds are pure-substance based, convert the supplied
            # raw-material % to pure-substance % via the grade's active
            # fraction. Curated records (no flag) keep legacy behaviour →
            # zero regression on validated classifications.
            conc = ing.wt_percent_high
            if rec.get("threshold_basis") == "pure":
                af = getattr(ing, "active_fraction", 1.0) or 1.0
                af = af if 0 < af <= 1 else 1.0
                conc *= af
            if ing.name not in evaluated:
                evaluated.append(ing.name)
            for hazard_class, trigger in rec.get("ghs_triggers", {}).items():
                if conc >= trigger["threshold_pct"]:
                    if ing.name not in hazardous:
                        hazardous.append(ing.name)
                    cat = str(trigger["category"])
                    existing_cat = triggered.get(hazard_class, (None, ""))[0]
                    if existing_cat is None or self._is_more_severe(cat, existing_cat):
                        triggered[hazard_class] = (cat, ing.name)

        # Step 1b: mixture-property rule — flammability is not additive.
        # Suppress flammable_liquid for aqueous / oxidiser / organic-peroxide
        # systems unless there is genuine low-flash evidence for the mixture.
        if "flammable_liquid" in triggered:
            fp = ""
            if physical_properties is not None:
                fp = (getattr(physical_properties, "flash_point", "") or "")
            fp_l = fp.lower()
            import re as _re
            m = _re.search(r"(-?\d+(?:\.\d+)?)\s*°?\s*c", fp_l)
            low_flash = bool(m and float(m.group(1)) < 60)
            non_flam_text = any(t in fp_l for t in (
                "not applicable", "non-flammable", "non flammable",
                "not flammable", "no flash"))
            water = sum(i.wt_percent_high for i in ingredients
                        if i.cas_number.strip() == "7732-18-5")
            oxidiser = ("oxidizing_liquid" in triggered
                        or "organic_peroxides" in triggered)
            # Oxidiser / organic-peroxide systems are classified by their own
            # class and are NOT dual-classified as flammable liquids under
            # GHS — even if a combustible component drags the estimated
            # flash point down, the mixture is governed by the oxidiser
            # hazard. For non-oxidiser systems, respect non-flammable text
            # or a high water fraction in the absence of a low-flash value.
            suppress = oxidiser or non_flam_text or (water >= 25 and not low_flash)
            if suppress:
                why = ("oxidiser/organic-peroxide matrix" if oxidiser
                       else "flash point indicates non-flammable"
                       if non_flam_text else f"{water:g}% water")
                print(f"[CONSISTENCY] flammable_liquid suppressed "
                      f"(mixture rule: {why}).")
                triggered.pop("flammable_liquid", None)

        # Step 1c: acute toxicity by the GHS ATE additivity formula
        # (100/ATEmix = Σ Ci/ATEi) instead of "worst single component".
        # Applied to oral & dermal (well-defined point estimates); inhalation
        # is left on the conservative worst-component rule.
        import re as _re2
        _ATE_PT = {  # GHS category → ATE point estimate
            "oral":   {"1": 0.5, "2": 5.0, "3": 100.0, "4": 500.0, "5": 2500.0},
            "dermal": {"1": 5.0, "2": 50.0, "3": 300.0, "4": 1100.0},
        }
        _ATE_BANDS = {  # ATEmix ≤ value → category
            "oral":   [(5, "1"), (50, "2"), (300, "3"), (2000, "4"), (5000, "5")],
            "dermal": [(50, "1"), (200, "2"), (1000, "3"), (2000, "4")],
        }
        _ROUTE_KEY = {"acute_toxicity_oral": ("oral", "oral_ld50"),
                      "acute_toxicity_dermal": ("dermal", "dermal_ld50")}
        for hclass, (route, tox_key) in _ROUTE_KEY.items():
            if hclass not in triggered:
                continue
            inv = 0.0
            for ing in ingredients:
                rec = self._db.get(ing.cas_number.strip())
                if not rec:
                    continue
                trig = (rec.get("ghs_triggers") or {}).get(hclass)
                if not trig:
                    continue
                ci = ing.wt_percent_high
                if ci <= 0:
                    continue
                ate = None
                res = ((rec.get("toxicology") or {}).get(tox_key) or {}).get("result", "")
                m = _re2.search(r"(\d+(?:\.\d+)?)\s*mg/kg", str(res))
                if m:
                    ate = float(m.group(1))
                if ate is None:
                    ate = _ATE_PT[route].get(str(trig.get("category")))
                if ate and ate > 0:
                    inv += ci / ate
            if inv > 0:
                atemix = 100.0 / inv
                newcat = next((c for lim, c in _ATE_BANDS[route]
                               if atemix <= lim), None)
                if newcat:
                    old = triggered[hclass][0]
                    if newcat != old:
                        print(f"[CONSISTENCY] {hclass}: ATE-additivity → "
                              f"Cat {newcat} (ATEmix≈{atemix:.0f}; "
                              f"was worst-component Cat {old}).")
                    triggered[hclass] = (newcat, "mixture (ATE)")
                else:
                    triggered.pop(hclass, None)  # ATEmix above Cat 5 → not classified

        # Step 2: build GHSHazardCategory objects
        categories = self._build_categories(triggered)

        # Step 3: signal word
        signal_word = self._determine_signal_word(triggered)

        # Step 4: deduplicated pictogram list (sorted for consistent ordering)
        pictograms = sorted({pic for cat in categories for pic in cat.pictogram_codes})

        # Step 5: H- and P-statements
        h_stmts = self._collect_h_statements(categories)
        p_stmts = self._collect_p_statements(triggered)

        return GHSClassification(
            signal_word=signal_word,
            categories=categories,
            pictograms_needed=pictograms,
            all_h_statements=h_stmts,
            all_p_statements=p_stmts,
            classified_ingredients=evaluated,
            hazardous_ingredients=hazardous,
        )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _is_more_severe(new_cat: str, existing_cat: str) -> bool:
        return _SEVERITY.get(new_cat, 99) < _SEVERITY.get(existing_cat, 99)

    def _build_categories(
        self, triggered: dict[str, tuple[str, str]]
    ) -> list[GHSHazardCategory]:
        categories: list[GHSHazardCategory] = []
        for hazard_class, (cat, _trigger) in triggered.items():
            key = f"{hazard_class}_{cat}"
            h_codes = _CATEGORY_H_CODES.get(key, [])
            if not h_codes:
                # fallback: try without suffix (e.g. skin_corrosion_1 covers 1A/1B/1C)
                base_key = f"{hazard_class}_1"
                h_codes = _CATEGORY_H_CODES.get(base_key, [])
            p_codes = _CATEGORY_P_CODES.get(key, [])
            if not p_codes:
                base_key = f"{hazard_class}_1"
                p_codes = _CATEGORY_P_CODES.get(base_key, [])
            pic = _PICTOGRAM_MAP.get(hazard_class, "")
            pics = [pic] if pic else []
            if hazard_class == "organic_peroxides":
                if cat == "A":
                    pics = ["GHS01"]
                elif cat == "B":
                    pics = ["GHS01", "GHS02"]
                elif cat == "G":
                    pics = []
                else:                       # C–F → flame only
                    pics = ["GHS02"]
            categories.append(GHSHazardCategory(
                class_name=_CLASS_DISPLAY.get(hazard_class, hazard_class),
                category=cat,
                h_codes=h_codes,
                p_codes=p_codes,
                pictogram_codes=pics,
            ))
        return categories

    @staticmethod
    def _determine_signal_word(triggered: dict[str, tuple[str, str]]) -> str:
        for hazard_class, (cat, _) in triggered.items():
            if hazard_class in _DANGER_CLASSES:
                if _SEVERITY.get(cat, 99) <= 3:   # Cat 1 or Cat 2
                    return "DANGER"
            danger_cats = _HEALTH_DANGER_CATS.get(hazard_class)
            if danger_cats and cat in danger_cats:
                return "DANGER"
            if hazard_class == "organic_peroxides" and cat in _ORG_PEROX_DANGER:
                return "DANGER"
        return "WARNING"

    @staticmethod
    def _collect_h_statements(categories: list[GHSHazardCategory]) -> list[str]:
        """Collect unique H-statements ordered by code number."""
        seen: set[str] = set()
        result: list[str] = []
        for cat in categories:
            for code in cat.h_codes:
                if code not in seen:
                    seen.add(code)
                    text = H_STATEMENTS.get(code, code)
                    result.append(f"{code} {text}")
        # Sort by numeric H-code
        result.sort(key=lambda s: int(s[1:4]))
        return result

    @staticmethod
    def _collect_p_statements(triggered: dict[str, tuple[str, str]]) -> list[str]:
        """Collect unique P-statements, deduplicated and sorted by code prefix."""
        seen: set[str] = set()
        codes: list[str] = []
        for hazard_class, (cat, _) in triggered.items():
            key = f"{hazard_class}_{cat}"
            p_list = _CATEGORY_P_CODES.get(key, [])
            if not p_list:
                base_key = f"{hazard_class}_1"
                p_list = _CATEGORY_P_CODES.get(base_key, [])
            for code in p_list:
                if code not in seen:
                    seen.add(code)
                    codes.append(code)
        # Sort by leading P-number
        codes.sort(key=lambda s: int(s[1:4]))
        return [f"{code} {P_STATEMENTS.get(code, code)}" for code in codes]


# ---------------------------------------------------------------------------
# Standalone test
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import json
    from pathlib import Path

    BASE = Path(__file__).parent
    db = {r["cas"]: r for r in json.load(open(BASE / "data/raw_material_db.json"))}
    clf = GHSClassifier(db)

    ingredients = [
        SDSIngredient("Hydrogen peroxide",   "7722-84-1", 20.0, 25.0),
        SDSIngredient("Nitric acid",          "7697-37-2",  5.0, 10.0),
        SDSIngredient("Acetic Acid",          "64-19-7",    4.0,  8.0),
        SDSIngredient("Ethaneperoxoic acid",  "79-21-0",    4.0,  6.0),
        SDSIngredient("Sulfuric acid",        "7664-93-9",  1.0,  5.0),
    ]

    result = clf.classify(ingredients)

    print(f"Signal word:  {result.signal_word}")
    print(f"Pictograms:   {result.pictograms_needed}")
    print(f"H-statements ({len(result.all_h_statements)}):")
    for s in result.all_h_statements:
        print(f"  {s}")
    print(f"P-statements ({len(result.all_p_statements)}):")
    for s in result.all_p_statements[:6]:
        print(f"  {s}")
    print(f"  ... ({len(result.all_p_statements)} total)")
    print()
    print("Hazard categories:")
    for cat in result.categories:
        print(f"  {cat.class_name}, category {cat.category}  [{cat.pictogram_codes}]")

    # Assertions against the shipped 114-chemical DB (H2O2 is oxidizing Cat 1
    # at 20-25% → H271, the worst case, not the peracetic-driven Cat 2/H272).
    assert result.signal_word == "DANGER", f"Expected DANGER, got {result.signal_word}"
    assert "GHS03" in result.pictograms_needed, "Missing GHS03 (oxidizer)"
    assert "GHS05" in result.pictograms_needed, "Missing GHS05 (corrosion)"
    assert "GHS06" in result.pictograms_needed, "Missing GHS06 (skull)"
    h_codes_found = {s[:4] for s in result.all_h_statements}
    for expected in ["H271", "H290", "H314", "H318", "H370"]:
        assert expected in h_codes_found, f"Missing {expected}"
    print("\nAll assertions passed — classifier matches the shipped DB.")
