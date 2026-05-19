"""
SDS Generator — Main Orchestrator.

Combines:
  1. GHSClassifier  — auto-classifies hazard categories from ingredient concentrations
  2. raw_material_db — enriches product with OELs, toxicology, aquatic data, regulatory
  3. Claude API     — generates narrative first-aid and firefighting text
  4. Rule-based     — builds transport information from classification results

Usage:
    gen = SDSGenerator("data/raw_material_db.json", "config/api_config.json")
    sds_doc = gen.generate(sds_from_oxystrike())
    build_sds_pdf(sds_doc, "output/OxyStrike_SDS.pdf", load_brand())
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import anthropic

from brand_config import load_brand
from db_enrichment import enrich_chemical, needs_enrichment, persist_db
from ghs_classifier import GHSClassifier
from sds_data_model import (
    AquaticToxRecord,
    ManufacturerInfo,
    OELEntry,
    RegulatoryListing,
    SDSDocument,
    SDSIngredient,
    SDSPhysicalProperties,
    SDSProduct,
    ToxicologyRecord,
    TransportInfo,
)


def _extract_json(raw: str) -> str:
    """Extract the first {...} JSON object from a string, stripping code fences."""
    start = raw.find("{")
    end = raw.rfind("}")
    if start != -1 and end != -1 and end > start:
        return raw[start:end + 1]
    return raw


class SDSGenerator:
    """
    Orchestrates SDS data assembly:
      - GHS classification from ingredient concentrations
      - Toxicological / regulatory data from raw_material_db.json
      - Narrative text from Claude Sonnet 4.6
      - Rule-based transport classification
    """

    def __init__(self, db_path: str | Path, api_config_path: str | Path):
        # Load chemical database, indexed by CAS number
        self._db_path = Path(db_path)
        with open(db_path, encoding="utf-8") as f:
            records = json.load(f)
        self._db: dict[str, dict] = {r["cas"]: r for r in records}

        # Anthropic client
        with open(api_config_path, encoding="utf-8") as f:
            cfg = json.load(f)
        self._client = anthropic.Anthropic(api_key=cfg["api_key"])

        # Classifier receives the same DB dict
        self._classifier = GHSClassifier(self._db)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def generate(self, product: SDSProduct, progress_cb=None) -> SDSDocument:
        """Fully populate an SDSProduct and return a ready-to-render SDSDocument."""
        def _cb(pct: int, msg: str):
            if progress_cb is not None:
                progress_cb(pct, msg)

        # 1. AI-enrich any DB records that lack toxicology/OEL/regulatory data
        #    (incl. carcinogenicity/sensitization GHS triggers), then write the
        #    filled records back so the cost is paid only once. Must run BEFORE
        #    classification so enriched health-hazard triggers reach Section 2.
        _cb(15, "AI-enriching chemical data (first time per chemical)...")
        self._ai_enrich_db(product)

        # 2. GHS classification (sees enriched ghs_triggers)
        _cb(30, "Running GHS classification...")
        product.classification = self._classifier.classify(
            product.ingredients, product.physical_properties)

        # 3. Enrich product from chemical database
        _cb(40, "Enriching from chemical database...")
        self._enrich_from_db(product)

        # 4. Claude API — narrative sections
        _cb(50, "Generating first aid text (Claude API)...")
        self._generate_first_aid(product)
        _cb(60, "Generating firefighting text (Claude API)...")
        self._generate_firefighting(product)
        _cb(70, "Generating handling/storage/PPE text (Claude API)...")
        self._generate_handling_storage_ppe(product)
        _cb(80, "Estimating physical properties (Claude API)...")
        self._generate_physical_properties(product)

        # 5. Transport classification (rule-based)
        _cb(88, "Building transport classification...")
        if not product.transport:
            product.transport = self._build_transport(product)

        # 6. Consistency cross-check (log contradictions)
        self._consistency_pass(product)

        # 7. NFPA / HMIS — auto-derive unless a manual override was supplied
        import nfpa_hmis
        if not product.nfpa and not product.hmis:
            r = nfpa_hmis.derive(product.classification,
                                  product.physical_properties)
            product.nfpa, product.hmis = r["nfpa"], r["hmis"]

        # 8. Meta fields
        _cb(95, "Finalizing document...")
        product.generated_date = date.today().isoformat()
        if not product.preparation_date:
            product.preparation_date = date.today().strftime("%m.%d.%Y")

        return SDSDocument(product=product)

    # ------------------------------------------------------------------
    # Database enrichment
    # ------------------------------------------------------------------

    def _lookup_db(self, cas: str) -> dict | None:
        return self._db.get(cas.strip())

    def _ai_enrich_db(self, product: SDSProduct) -> None:
        """For each ingredient in the DB, fill missing toxicology/OEL/aquatic/
        regulatory data via Claude (once) and persist it back to the JSON file.
        """
        dirty = False
        for ing in product.ingredients:
            rec = self._lookup_db(ing.cas_number)
            if not rec or not needs_enrichment(rec):
                continue
            _, changed = enrich_chemical(self._client, rec)
            dirty = dirty or changed
        if dirty:
            try:
                persist_db(self._db, self._db_path)
            except Exception as e:  # noqa: BLE001 — never fail generation on a write
                print(f"[WARNING] Could not persist enriched DB: {e}")

    def _enrich_from_db(self, product: SDSProduct) -> None:
        """Populate OELs, toxicology, aquatic, regulatory, and carcinogenicity fields."""
        skin_results: list[str] = []
        eye_results: list[str] = []
        stot_results: list[str] = []
        iarc_parts: list[str] = []
        ntp_parts: list[str] = []
        oel_seen: set[tuple] = set()

        for ing in product.ingredients:
            rec = self._lookup_db(ing.cas_number)
            if not rec:
                continue

            # OEL entries (deduplicate by authority+substance+type)
            for oel in rec.get("oels", []):
                key = (ing.cas_number, oel["authority"], oel["type"])
                if key not in oel_seen:
                    oel_seen.add(key)
                    product.control_parameters.append(OELEntry(
                        substance_name=rec["name"],
                        cas=rec["cas"],
                        authority=oel["authority"],
                        oel_type=oel["type"],
                        value=oel["value"],
                        unit=oel["unit"],
                    ))

            # Toxicology records
            tox = rec.get("toxicology", {})
            for route_key, route_data in tox.items():
                if not isinstance(route_data, dict):
                    continue
                if route_key in ("skin_result", "eye_result", "stot_result"):
                    continue
                product.toxicology_records.append(ToxicologyRecord(
                    substance=rec["name"],
                    route=route_data.get("route", route_key),
                    species=route_data.get("species", ""),
                    result=route_data.get("result", ""),
                ))
            if tox.get("skin_result"):
                skin_results.append(f"{rec['name']}: {tox['skin_result']}")
            if tox.get("eye_result"):
                eye_results.append(f"{rec['name']}: {tox['eye_result']}")
            if tox.get("stot_result"):
                stot_results.append(f"{rec['name']}: {tox['stot_result']}")

            # Aquatic toxicology
            aq = rec.get("aquatic_toxicology", {})
            for entry in aq.get("acute", []):
                dur = f"{entry.get('duration_hr', '')} hr" if entry.get("duration_hr") else ""
                ep = f" [{entry['endpoint']}]" if entry.get("endpoint") else ""
                product.aquatic_tox_records.append(AquaticToxRecord(
                    substance=rec["name"],
                    organism_type=entry["type"],
                    organism=entry["organism"],
                    metric=entry["metric"],
                    value=f"{entry['value']} ({dur}){ep}",
                    endpoint=entry.get("endpoint", ""),
                ))
            for entry in aq.get("chronic", []):
                dur = (f"{entry.get('duration_days', '')} d"
                       if entry.get("duration_days") else "")
                ep = f" [{entry['endpoint']}]" if entry.get("endpoint") else ""
                product.chronic_tox_records.append(AquaticToxRecord(
                    substance=rec["name"],
                    organism_type=entry["type"],
                    organism=entry["organism"],
                    metric=entry["metric"],
                    value=f"{entry['value']} ({dur}){ep}",
                    endpoint=entry.get("endpoint", ""),
                ))

            # Persistence / bioaccumulation / mobility per ingredient
            if rec.get("persistence"):
                product.persistence_degradability.append((rec["name"], rec["persistence"]))
            if rec.get("bioaccumulation"):
                product.bioaccumulation.append((rec["name"], rec["bioaccumulation"]))
            if rec.get("mobility"):
                product.mobility.append((rec["name"], rec["mobility"]))

            # Carcinogenicity
            iarc = rec.get("iarc_classification", "Not Applicable")
            ntp = rec.get("ntp_classification", "Not Applicable")
            if iarc not in ("Not Applicable", ""):
                iarc_parts.append(f"{rec['name']}: {iarc}")
            if ntp not in ("Not Applicable", ""):
                ntp_parts.append(f"{rec['name']}: {ntp}")

            # Regulatory listings
            reg = rec.get("regulatory", {})
            product.regulatory_listings.append(RegulatoryListing(
                substance_name=rec["name"],
                cas=rec["cas"],
                tsca_listed=bool(reg.get("tsca_listed")),
                sara_302=bool(reg.get("sara_302")),
                sara_302_tpq_lbs=str(reg.get("sara_302_tpq_lbs") or ""),
                sara_313=bool(reg.get("sara_313")),
                cercla_listed=bool(reg.get("cercla_listed")),
                cercla_rq_lbs=str(reg.get("cercla_rq_lbs") or ""),
                rcra_code=str(reg.get("rcra_code") or ""),
                caa_112r=bool(reg.get("caa_112r")),
                prop_65=bool(reg.get("prop_65")),
                prop_65_warning=str(reg.get("prop_65_warning") or ""),
                rtk_states=list(reg.get("rtk_states") or []),
            ))

        # Consolidate skin/eye/stot narrative
        if skin_results:
            product.skin_corrosion_result = "Causes severe skin burns and eye damage.\n" + "\n".join(skin_results)
        if eye_results:
            product.eye_damage_result = "Causes serious eye damage.\n" + "\n".join(eye_results)
        if stot_results:
            product.stot_single = "May cause respiratory irritation.\n" + "\n".join(stot_results)

        # Carcinogenicity narrative
        if iarc_parts:
            product.carcinogenicity_iarc = "International Agency for Research on Cancer (IARC):\n" + "\n".join(iarc_parts)
        else:
            product.carcinogenicity_iarc = "No listed IARC carcinogens."
        if ntp_parts:
            product.carcinogenicity_ntp = "National Toxicology Program (NTP):\n" + "\n".join(ntp_parts)
        else:
            product.carcinogenicity_ntp = "No listed NTP carcinogens."

        # Prop 65 aggregate warning
        prop65_ings = [rl for rl in product.regulatory_listings if rl.prop_65]
        if prop65_ings:
            names = ", ".join(rl.substance_name for rl in prop65_ings)
            product.prop_65_warning_text = (
                f"WARNING: This product can expose you to {names}, which is/are "
                "known to the State of California to cause cancer and/or "
                "reproductive harm. For more information go to "
                "www.P65Warnings.ca.gov"
            )

        # Default values for non-DB fields
        if not product.mutagenicity:
            product.mutagenicity = "Based on available data, the classification criteria are not met."
        if not product.reproductive_toxicity:
            product.reproductive_toxicity = "Based on available data, the classification criteria are not met."
        if not product.stot_repeated:
            product.stot_repeated = "Based on available data, the classification criteria are not met."
        if not product.aspiration_hazard:
            product.aspiration_hazard = "Based on available data, the classification criteria are not met."
        if not product.sensitisation:
            product.sensitisation = "Based on available data, the classification criteria are not met."
        if not product.pbt_vpvb:
            product.pbt_vpvb = (
                "This product does not contain any substances assessed to be a PBT or vPvB."
            )

    # ------------------------------------------------------------------
    # Claude API — first aid narrative (Section 4)
    # ------------------------------------------------------------------

    def _generate_first_aid(self, product: SDSProduct) -> None:
        """Call Claude to generate GHS-compliant first aid text for all exposure routes."""
        # If already populated (e.g. from factory function), skip
        if product.first_aid_inhalation and product.first_aid_skin:
            return

        ing_names = [ing.name for ing in product.ingredients]
        h_codes = [s[:4] for s in product.classification.all_h_statements]

        system_prompt = (
            "You are a senior GHS-compliant SDS technical writer with expertise in "
            "OSHA HCS 2012. Write concise, accurate first aid instructions for "
            "chemical products. Return ONLY a valid JSON object with these exact keys: "
            "inhalation, skin, eye, ingestion, general_notes, doctor_notes. "
            "Each value is a plain text string (no markdown). "
            "Be specific to the chemistry — do not write generic boilerplate."
        )
        user_msg = (
            f"Product: {product.product_name}\n"
            f"Signal word: {product.classification.signal_word}\n"
            f"H-codes: {', '.join(h_codes)}\n"
            f"Ingredients: {', '.join(ing_names)}\n\n"
            "Write first aid instructions for each route of exposure. "
            "For inhalation: include oxygen and artificial respiration if needed. "
            "For skin: urgent rinsing, remove contaminated clothing. "
            "For eye: immediate 15-minute rinsing, seek ophthalmologist. "
            "For ingestion: DO NOT induce vomiting, rinse mouth, seek emergency care. "
            "Return JSON only."
        )

        try:
            resp = self._client.messages.create(
                model="claude-sonnet-4-6",
                max_tokens=1500,
                system=[{
                    "type": "text",
                    "text": system_prompt,
                    "cache_control": {"type": "ephemeral"},
                }],
                messages=[{"role": "user", "content": user_msg}],
            )
            raw = resp.content[0].text.strip()
            raw = _extract_json(raw)
            data = json.loads(raw)
            product.first_aid_inhalation = data.get("inhalation", "")
            product.first_aid_skin       = data.get("skin", "")
            product.first_aid_eye        = data.get("eye", "")
            product.first_aid_ingestion  = data.get("ingestion", "")
            product.first_aid_general    = data.get("general_notes", "Show this Safety Data Sheet to the doctor in attendance.")
            product.first_aid_doctor_notes = data.get("doctor_notes", "Treat symptomatically.")
        except Exception as e:
            print(f"[WARNING] First aid generation failed: {e}. Using defaults.")
            product.first_aid_inhalation = (
                "If inhaled, remove person to fresh air and place in a position comfortable "
                "for breathing. If breathing is difficult, administer oxygen. If breathing has "
                "stopped, provide artificial respiration. Seek immediate medical attention."
            )
            product.first_aid_skin = (
                "Remove contaminated clothing and shoes immediately. Rinse skin with copious "
                "amounts of water for at least 15 minutes. Treatment is urgent — seek emergency "
                "medical treatment. Launder contaminated clothing before reuse."
            )
            product.first_aid_eye = (
                "Immediately rinse eyes with plenty of gently flowing lukewarm water for at least "
                "15 minutes. Remove contact lenses if present and easy to do so. Protect unexposed "
                "eye. Seek immediate medical attention, preferably from an ophthalmologist."
            )
            product.first_aid_ingestion = (
                "If swallowed, DO NOT induce vomiting unless told to do so by a physician or "
                "poison control center. Rinse mouth with water. Never give anything by mouth to "
                "an unconscious person. Seek immediate medical attention."
            )
            product.first_aid_general = "Show this Safety Data Sheet to the doctor in attendance."
            product.first_aid_doctor_notes = "Treat symptomatically."

    # ------------------------------------------------------------------
    # Claude API — firefighting narrative (Section 5)
    # ------------------------------------------------------------------

    def _generate_firefighting(self, product: SDSProduct) -> None:
        """Call Claude to generate firefighting instructions for Section 5."""
        if product.extinguishing_media:
            return

        ing_names = [ing.name for ing in product.ingredients]
        hazard_classes = [cat.class_name for cat in product.classification.categories]

        system_prompt = (
            "You are a senior GHS SDS technical writer. Generate firefighting information "
            "for a chemical product. Return ONLY a valid JSON object with these keys: "
            "extinguishing_media, unsuitable_extinguishing_media, specific_hazards, "
            "firefighter_ppe, special_precautions. Plain text strings, no markdown."
        )
        user_msg = (
            f"Product: {product.product_name}\n"
            f"Hazard classes: {', '.join(hazard_classes) or 'None classified'}\n"
            f"Ingredients: {', '.join(ing_names)}\n\n"
            "Base firefighting guidance strictly on the hazard classes and "
            "ingredient chemistry above. Do NOT assume the product is oxidizing, "
            "flammable, or otherwise hazardous unless that is implied by the "
            "listed hazard classes or ingredients. Return JSON only."
        )

        try:
            resp = self._client.messages.create(
                model="claude-sonnet-4-6",
                max_tokens=1200,
                system=[{
                    "type": "text",
                    "text": system_prompt,
                    "cache_control": {"type": "ephemeral"},
                }],
                messages=[{"role": "user", "content": user_msg}],
            )
            raw = resp.content[0].text.strip()
            raw = _extract_json(raw)
            data = json.loads(raw)
            product.extinguishing_media          = data.get("extinguishing_media", "")
            product.unsuitable_extinguishing_media = data.get("unsuitable_extinguishing_media", "")
            product.firefighting_hazards         = data.get("specific_hazards", "")
            product.firefighting_ppe             = data.get("firefighter_ppe", "")
            product.firefighting_precautions     = data.get("special_precautions", "")
        except Exception as e:
            print(f"[WARNING] Firefighting generation failed: {e}. Using defaults.")
            product.extinguishing_media = (
                "Use extinguishing media appropriate for the surrounding fire. Water "
                "mist/fog, carbon dioxide, dry chemical or alcohol-resistant foam."
            )
            product.unsuitable_extinguishing_media = "Do not use a direct high-pressure water jet on the product."
            product.firefighting_hazards = (
                "Thermal decomposition may produce irritating/toxic fumes/gases. "
                "Containers may build pressure and rupture when exposed to heat."
            )
            product.firefighting_ppe = (
                "Fire-fighters should wear appropriate protective equipment and self-contained "
                "breathing apparatus (SCBA) with a full-face piece operated in positive pressure mode."
            )
            product.firefighting_precautions = (
                "Do not get water inside containers. Avoid contact with skin, eyes, hair and "
                "clothing. Move containers from fire area if safe to do so. Use water spray/fog "
                "for cooling fire exposed containers."
            )

    # ------------------------------------------------------------------
    # Claude API — handling / storage / PPE / spill / stability (Sec 6,7,8,10)
    # ------------------------------------------------------------------

    _HSP_DEFAULTS = {
        "spill_personal_precautions": (
            "Evacuate unnecessary personnel. Ventilate the area. Wear recommended "
            "personal protective equipment (see Section 8). Avoid contact with skin, "
            "eyes and clothing. Avoid breathing mist, vapor, dust, fume and spray. "
            "Do not walk through spilled material."),
        "spill_environmental_precautions": (
            "Prevent further leakage or spillage if safe to do so. Prevent from "
            "reaching drains, sewers and waterways. Discharge into the environment "
            "must be avoided."),
        "spill_containment_cleanup": (
            "Do not touch damaged containers or spilled material unless wearing "
            "appropriate personal protective clothing. Stop the leak if it can be "
            "done without risk. Contain and collect spillage with non-combustible "
            "absorbent material and place in a suitable container for disposal in "
            "accordance with all applicable regulations (see Section 13)."),
        "handling_precautions": (
            "Use appropriate personal protective equipment (see Section 8). Use only "
            "with adequate ventilation. Avoid contact with skin, eyes and clothing. "
            "Avoid breathing mist/vapor/spray/dust. Do not eat, drink or smoke when "
            "handling. Wash thoroughly after handling. Keep containers tightly "
            "closed when not in use. Keep away from incompatible materials "
            "(see Section 10)."),
        "storage_conditions": (
            "Store in a cool, dry, well-ventilated location out of direct sunlight. "
            "Keep container tightly closed. Keep away from food and beverages. "
            "Protect from freezing and physical damage. Store away from incompatible "
            "materials (see Section 10)."),
        "engineering_controls": (
            "Provide adequate ventilation to maintain airborne concentrations below "
            "the applicable workplace exposure limits. Emergency eye wash stations "
            "and safety showers should be available in the immediate vicinity of use "
            "or handling."),
        "ppe_respiratory": (
            "If engineering controls do not maintain airborne concentrations below "
            "the applicable exposure limits, a respirator approved by recognized "
            "national standards (or equivalent) must be worn."),
        "ppe_hand": (
            "Chemical-resistant, impervious gloves approved by the appropriate "
            "standards. Gloves must be inspected prior to use."),
        "ppe_eye": (
            "Safety glasses with side shields or chemical splash goggles. Consider a "
            "face shield where splashing is possible."),
        "ppe_skin": (
            "Wear suitable chemical-resistant protective clothing and footwear "
            "appropriate to the task and risk."),
        "hygienic_measures": (
            "When handling chemical products, do not eat, drink or smoke. Wash hands "
            "after handling, before breaks and at the end of the workday. Wash "
            "contaminated clothing before reuse."),
        "reactivity": "Not reactive under recommended handling and storage conditions.",
        "chemical_stability": "Stable under recommended handling and storage conditions.",
        "hazardous_reactions": (
            "Hazardous reactions are not anticipated under recommended conditions of "
            "handling and storage."),
        "conditions_to_avoid": (
            "Extreme heat, incompatible materials, and conditions inconsistent with "
            "recommended storage."),
        "incompatible_materials": "Strong acids and strong oxidizing agents.",
        "hazardous_decomposition": (
            "Thermal decomposition may produce irritating and/or toxic fumes and "
            "gases."),
        "disposal_methods": (
            "Dispose of contents and container in accordance with all applicable "
            "local, regional, national and international regulations. Do not mix "
            "with other waste. Handle uncleaned containers like the product "
            "itself. Do not discharge to drains, sewers or waterways."),
        "disposal_container": (
            "Empty containers may retain product residue and must be handled as "
            "hazardous until cleaned. Triple-rinse and dispose of in accordance "
            "with applicable regulations."),
    }

    def _generate_handling_storage_ppe(self, product: SDSProduct) -> None:
        """Generate Section 6/7/8/10 narrative when not already populated.

        These fields are only hardcoded by the OxyStrike factory; products
        entered through the web wizard arrive with them blank.
        """
        keys = {
            "spill_personal_precautions": product.spill_personal_precautions,
            "spill_environmental_precautions": product.spill_environmental_precautions,
            "spill_containment_cleanup": product.spill_containment_cleanup,
            "handling_precautions": product.handling_precautions,
            "storage_conditions": product.storage_conditions,
            "engineering_controls": product.engineering_controls,
            "ppe_respiratory": product.ppe_respiratory,
            "ppe_hand": product.ppe_hand,
            "ppe_eye": product.ppe_eye,
            "ppe_skin": product.ppe_skin,
            "hygienic_measures": product.hygienic_measures,
            "reactivity": product.reactivity,
            "chemical_stability": product.chemical_stability,
            "hazardous_reactions": product.hazardous_reactions,
            "conditions_to_avoid": product.conditions_to_avoid,
            "incompatible_materials": product.incompatible_materials,
            "hazardous_decomposition": product.hazardous_decomposition,
            "disposal_methods": product.disposal_methods,
            "disposal_container": product.disposal_container,
        }
        missing = [k for k, v in keys.items() if not (v or "").strip()]
        if not missing:
            return

        ing_names = [ing.name for ing in product.ingredients]
        hazard_classes = [c.class_name for c in product.classification.categories]

        system_prompt = (
            "You are a senior GHS-compliant SDS technical writer (OSHA HCS 2012). "
            "Write accurate Section 6 (accidental release), Section 7 (handling & "
            "storage), Section 8 (engineering controls & PPE), Section 10 "
            "(stability & reactivity) and Section 13 (disposal) text for a "
            "chemical product. Return ONLY a "
            "valid JSON object whose keys are exactly the requested field names; "
            "each value is a plain-text string (no markdown). Base every statement "
            "on the product's actual hazard classes and chemistry — do NOT assume "
            "properties (e.g. oxidizing, flammable) that are not listed in the "
            "hazard classes."
        )
        user_msg = (
            f"Product: {product.product_name}\n"
            f"Hazard classes: {', '.join(hazard_classes) or 'None classified'}\n"
            f"Ingredients: {', '.join(ing_names)}\n\n"
            f"Generate these fields only: {', '.join(missing)}\n"
            "Return JSON only."
        )
        try:
            resp = self._client.messages.create(
                model="claude-sonnet-4-6",
                max_tokens=3500,
                system=[{"type": "text", "text": system_prompt,
                         "cache_control": {"type": "ephemeral"}}],
                messages=[{"role": "user", "content": user_msg}],
            )
            data = json.loads(_extract_json(resp.content[0].text.strip()))
            for k in missing:
                val = data.get(k)
                if isinstance(val, str) and val.strip():
                    setattr(product, k, val.strip())
        except Exception as e:  # noqa: BLE001
            print(f"[WARNING] Handling/storage/PPE generation failed: {e}.")

        # Guarantee these sections are never blank, even if the API failed or
        # omitted a key.
        for k in missing:
            if not (getattr(product, k) or "").strip():
                setattr(product, k, self._HSP_DEFAULTS[k])

    # ------------------------------------------------------------------
    # Claude API — Section 9 physical & chemical properties estimation
    # ------------------------------------------------------------------

    _ND = "Not determined or not available."

    def _generate_physical_properties(self, product: SDSProduct) -> None:
        """Estimate Section 9 properties from the formulation when blank.

        Values that can be reasonably inferred from the ingredients and their
        concentrations are returned with an "(estimated)" suffix; everything
        else is explicitly "Not determined or not available."
        """
        pp = product.physical_properties
        fields = list(SDSPhysicalProperties.__dataclass_fields__)

        def _blank(v: str) -> bool:
            v = (v or "").strip().lower()
            return v == "" or v.startswith("not determined") or v.startswith("not available")

        missing = [f for f in fields if _blank(getattr(pp, f))]
        if not missing:
            return

        ings = [f"{i.name} ({i.cas_number}) {i.wt_percent_low}-{i.wt_percent_high}%"
                for i in product.ingredients]

        system_prompt = (
            "You are a physical chemist estimating Section 9 properties of an "
            "aqueous chemical mixture for an OSHA HCS 2012 SDS. Return ONLY a "
            "valid JSON object whose keys are exactly the requested field names; "
            "values are plain strings. Estimate ONLY properties that can be "
            "reasonably inferred from the listed ingredients and their "
            "concentrations (e.g. appearance, odour, pH for known acids/bases, "
            "approximate density, boiling/freezing behaviour for dilute aqueous "
            "solutions). Append ' (estimated)' to every value you infer. For any "
            "property that requires laboratory measurement and cannot be "
            f"reliably inferred, return exactly \"{self._ND}\". Never fabricate "
            "precise instrument values."
        )
        user_msg = (
            f"Product: {product.product_name}\n"
            f"Ingredients: {'; '.join(ings)}\n\n"
            f"Estimate these fields only: {', '.join(missing)}\n"
            "Return JSON only."
        )
        try:
            resp = self._client.messages.create(
                model="claude-sonnet-4-6",
                max_tokens=1500,
                system=[{"type": "text", "text": system_prompt,
                         "cache_control": {"type": "ephemeral"}}],
                messages=[{"role": "user", "content": user_msg}],
            )
            data = json.loads(_extract_json(resp.content[0].text.strip()))
            for f in missing:
                val = data.get(f)
                setattr(pp, f, val.strip() if isinstance(val, str) and val.strip()
                        else self._ND)
        except Exception as e:  # noqa: BLE001
            print(f"[WARNING] Physical property estimation failed: {e}.")
            for f in missing:
                if _blank(getattr(pp, f)):
                    setattr(pp, f, self._ND)

    # ------------------------------------------------------------------
    # Consistency cross-check
    # ------------------------------------------------------------------

    def _consistency_pass(self, product: SDSProduct) -> None:
        """Log contradictions between AI-generated prose and the classification.

        Does not rewrite text (that risks introducing new errors) — surfaces
        issues so they can be caught in review and so prompt regressions are
        visible in the server log.
        """
        classes = " ".join(c.class_name.lower()
                            for c in product.classification.categories)
        has_oxidizer = "oxidiz" in classes
        has_flammable = "flammable" in classes
        ff = (product.firefighting_hazards or "").lower()
        pp = product.physical_properties

        if not has_oxidizer and "oxidiz" in ff and "not " not in ff[:ff.find("oxidiz")][-12:]:
            print("[CONSISTENCY] Section 5 mentions 'oxidizing' but no "
                  "oxidizing hazard class is classified — verify wording.")
        flash = (pp.flash_point or "").lower()
        if has_flammable and flash.startswith("not "):
            print("[CONSISTENCY] Product classified flammable but Section 9 "
                  "flash point is 'Not determined' — verify.")
        if not has_flammable and any(
                w in flash for w in ("flammable", "flash point:")) \
                and "not applicable" not in flash and "no flash" not in flash:
            print("[CONSISTENCY] Section 9 implies a flash point but product "
                  "is not classified flammable — verify.")

        # Organic-peroxide sanity: a peroxy acid / peroxide present but not
        # classified as an organic peroxide is almost certainly an omission.
        names = " ".join(i.name.lower() for i in product.ingredients)
        cas_set = {i.cas_number.strip() for i in product.ingredients}
        peroxidey = ("79-21-0" in cas_set or "peroxyacetic" in names
                     or "peracetic" in names or "peroxide" in names)
        if peroxidey and "organic peroxide" not in classes \
                and "hydrogen peroxide" not in names:
            print("[CONSISTENCY] A peroxy-acid/peroxide ingredient is present "
                  "but no Organic peroxide class is classified — verify.")

        # Carcinogenicity from a mist-only IARC entry (sulfuric-acid type).
        for cat in product.classification.categories:
            if "carcinogen" not in cat.class_name.lower():
                continue
            for ing in product.ingredients:
                rec = self._db.get(ing.cas_number.strip()) or {}
                ia = (rec.get("iarc_classification") or "").lower()
                if "mist" in ia and "per se" in ia:
                    print("[CONSISTENCY] Carcinogenicity may stem from a "
                          f"mist-only IARC entry ({ing.name}) — verify it "
                          "should classify the liquid mixture.")

    # ------------------------------------------------------------------
    # Rule-based transport classification
    # ------------------------------------------------------------------

    def _build_transport(self, product: SDSProduct) -> list[TransportInfo]:
        """Assign UN numbers based on GHS classification results."""
        classified_classes = {cat.class_name for cat in product.classification.categories}
        is_oxidizer = any("oxidizing" in c.lower() for c in classified_classes)
        is_corrosive = any("corrosion" in c.lower() or "corrosive to metals" in c.lower()
                           for c in classified_classes)
        is_env = any("aquatic" in c.lower() or "environment" in c.lower()
                     for c in classified_classes)

        # Transport packing group from the skin-corrosion sub-category
        # (49 CFR / UN: 1A → PG I, 1B → PG II, 1C → PG III; default II).
        corr_cat = next((c.category for c in product.classification.categories
                         if "corrosion" in c.class_name.lower()), "")
        corr_pg = {"1A": "I", "1B": "II", "1C": "III"}.get(corr_cat, "II")

        # Dominant ingredient (highest upper-bound concentration) names the n.o.s.
        dominant = max(product.ingredients, key=lambda i: i.wt_percent_high,
                       default=None)
        dom = dominant.name if dominant else ""
        env_note = "Marine Pollutant" + (f" ({dom})" if dom else "") if is_env else "None"

        cas_set = {i.cas_number.strip() for i in product.ingredients}
        is_org_perox = any("organic peroxide" in c.lower()
                           for c in classified_classes)
        has_paa = "79-21-0" in cas_set        # peroxyacetic / peracetic acid
        has_h2o2 = "7722-84-1" in cas_set     # hydrogen peroxide

        if has_paa and has_h2o2:
            # Well-known stabilized H2O2 + peroxyacetic acid mixture.
            un = "UN3149"
            psn = "Hydrogen peroxide and peroxyacetic acid mixture, with " \
                  "acid(s), water and not more than 5% peroxyacetic acid, " \
                  "stabilized"
            haz_class = "5.1 (8)"
            pg = "II"
            labels = "5.1, 8"
        elif is_org_perox:
            un = "UN3109"
            psn = f"Organic peroxide type F, liquid{f' ({dom})' if dom else ''}"
            haz_class = "5.2"
            pg = "None"          # organic peroxides are not assigned a PG
            labels = "5.2"
        elif is_oxidizer and is_corrosive:
            un = "UN3139"
            psn = f"Oxidizing liquid, corrosive, n.o.s.{f' ({dom})' if dom else ''}"
            haz_class = "5.1 (8)"
            pg = corr_pg
            labels = "5.1, 8"
        elif is_oxidizer:
            un = "UN3139"
            psn = f"Oxidizing liquid, n.o.s.{f' ({dom})' if dom else ''}"
            haz_class = "5.1"
            pg = "II"
            labels = "5.1"
        elif is_corrosive:
            un = "UN1760"
            psn = f"Corrosive liquid, n.o.s.{f' ({dom})' if dom else ''}"
            haz_class = "8"
            pg = corr_pg
            labels = "8"
        else:
            un = "Not regulated"
            psn = "Not regulated"
            haz_class = "None"
            pg = "None"
            labels = "None"
            env_note = "None"

        return [
            TransportInfo(
                mode="DOT",
                un_number=un,
                proper_shipping_name=psn,
                hazard_class=haz_class,
                packing_group=pg,
                labels_required=labels,
                environmental_hazard=env_note,
                special_precautions="None",
            ),
            TransportInfo(
                mode="IMDG",
                un_number="Not regulated",
                proper_shipping_name="Not regulated",
                hazard_class="None",
                packing_group="None",
                labels_required="None",
                environmental_hazard="None",
                special_precautions="None",
            ),
            TransportInfo(
                mode="IATA",
                un_number="Not regulated",
                proper_shipping_name="Not regulated",
                hazard_class="None",
                packing_group="None",
                labels_required="None",
                environmental_hazard="None",
                special_precautions="None",
            ),
        ]


# ---------------------------------------------------------------------------
# OxyStrike factory — pre-populated SDSProduct for testing
# ---------------------------------------------------------------------------

def sds_from_oxystrike() -> SDSProduct:
    """
    Return a pre-populated SDSProduct matching OxyStrike CC1383 by Capacity Chemical LLC.
    Classification is left empty (GHSClassification()) and will be populated by
    SDSGenerator.generate().
    """
    mfr = ManufacturerInfo(
        company_name="Capacity Chemical LLC",
        address_line1="8512 Hwy 33",
        city_state_zip="Westley, CA 95387",
        country="United States",
        phone="(209) 231-3977",
        website="http://www.capacitychemical.com",
        emergency_phone="1-800-424-9300 (24 hours)",
        emergency_provider="CHEMTREC",
        emergency_account="1014335",
    )

    ingredients = [
        SDSIngredient("Hydrogen peroxide",   "7722-84-1", 20.0, 25.0, "Active oxidant"),
        SDSIngredient("Nitric acid",          "7697-37-2",  5.0, 10.0, "Acid component"),
        SDSIngredient("Acetic Acid",          "64-19-7",    4.0,  8.0, "Acid component"),
        SDSIngredient("Ethaneperoxoic acid",  "79-21-0",    4.0,  6.0, "Active oxidant"),
        SDSIngredient("Sulfuric acid",        "7664-93-9",  1.0,  5.0, "Acid component"),
    ]

    physical = SDSPhysicalProperties(
        appearance="Clear and colorless",
        odour="Pungent, Strong vinegar-like",
        odour_threshold="Not determined or not available.",
        pH="< 2",
        melting_point="Not determined or not available.",
        boiling_point="Not determined or not available.",
        flash_point="Not determined or not available.",
        evaporation_rate="Not determined or not available.",
        flammability="Not determined or not available.",
        upper_explosive_limit="Not determined or not available.",
        lower_explosive_limit="Not determined or not available.",
        vapour_pressure="Not determined or not available.",
        vapour_density="Not determined or not available.",
        density="1.169",
        relative_density="Not determined or not available.",
        solubility="Not determined or not available.",
        partition_coefficient="Not determined or not available.",
        auto_ignition_temp="Not determined or not available.",
        decomposition_temp="Not determined or not available.",
        viscosity="Not determined or not available.",
    )

    return SDSProduct(
        # Section 1
        product_name="OxyStrike",
        product_code="CC1383",
        product_type="Oxidizing acid cleaner / disinfectant",
        manufacturer=mfr,
        recommended_use="Please see Labels/TDS for the instructions.",
        restrictions_on_use="Not determined or not applicable.",

        # Section 3
        ingredients=ingredients,
        additional_ingredient_info="None",

        # Section 7
        handling_precautions=(
            "Use appropriate personal protective equipment (see Section 8). "
            "Prevent skin contact. Do not get in eyes. Use only with adequate ventilation. "
            "Do not add water to the corrosive product. Avoid breathing mist/vapor/spray/dust. "
            "Keep containers tightly closed when not in use. Keep only in original packaging. "
            "Never return unused product to the original container."
        ),
        storage_conditions=(
            "Store in cool, dry, well-ventilated location out of direct sunlight and away from "
            "exit paths. Store in a corrosion-resistant container with a resistant inner liner. "
            "Keep away from food and beverages. Protect from freezing and physical damage. "
            "Store away from heat, open flames and other sources of ignition. Store separately. "
            "Keep container tightly sealed."
        ),

        # Section 8
        engineering_controls=(
            "Emergency eye wash stations and safety showers should be available in the immediate "
            "vicinity of use or handling. Provide adequate ventilation to maintain airborne "
            "concentrations below the applicable workplace exposure limits."
        ),
        ppe_respiratory=(
            "If engineering controls do not maintain airborne concentrations below the applicable "
            "workplace exposure limits, a respirator approved by recognized national standards "
            "must be worn."
        ),
        ppe_hand=(
            "Chemical resistant, impervious gloves approved by the appropriate standards. "
            "Gloves must be inspected prior to use. Full body protection should be worn."
        ),
        ppe_eye=(
            "Use safety glasses with side shields or goggles. Consider the use of a face shield "
            "for splash protection."
        ),
        ppe_skin="Full body protection. Chemical resistant, impervious clothing.",
        hygienic_measures=(
            "When handling chemical products, do not eat, drink or smoke. Wash hands after "
            "handling, before breaks, and at the end of the workday. Avoid contact with skin, "
            "eyes and clothing. Wash contaminated clothing before reuse."
        ),

        # Section 9
        physical_properties=physical,

        # Section 10
        reactivity="Not reactive under recommended handling and storage conditions.",
        chemical_stability="Stable under recommended handling and storage conditions.",
        hazardous_reactions=(
            "Hazardous reactions are not anticipated under recommended conditions of "
            "handling and storage."
        ),
        conditions_to_avoid=(
            "Avoid generation of aerosols and mists, extreme heat, open flames, hot surfaces, "
            "sparks, ignition sources and incompatible materials."
        ),
        incompatible_materials="None known.",
        hazardous_decomposition=(
            "Under normal conditions of storage and use, hazardous decomposition products "
            "should not be produced."
        ),

        # Section 6
        spill_personal_precautions=(
            "Evacuate unnecessary personnel. Ventilate area. Extinguish any sources of ignition. "
            "Wear recommended personal protective equipment (see Section 8). Avoid contact with "
            "skin, eyes and clothing. Avoid breathing mist, vapor, dust, fume and spray. "
            "Do not walk through spilled material."
        ),
        spill_environmental_precautions=(
            "Prevent further leakage or spillage if safe to do so. Prevent from reaching drains, "
            "sewers and waterways. Discharge into the environment must be avoided."
        ),
        spill_containment_cleanup=(
            "Do not touch damaged containers or spilled material unless wearing appropriate "
            "personal protective clothing. Stop leak if you can do it without risk. Contain and "
            "collect spillage and place in suitable corrosive resistant containers for future "
            "disposal. Do not get water in containers as reaction with water or moist air may "
            "release toxic, corrosive or flammable gases. Dispose of in accordance with all "
            "applicable regulations (see Section 13)."
        ),

        # Section 13
        disposal_methods=(
            "Waste material must be disposed of in accordance with the national and local "
            "regulations. Leave chemicals in original containers. No mixing with other waste. "
            "Handle uncleaned containers like the product itself."
        ),
        disposal_container="Not determined or not applicable.",

        # Section 15
        tsca_inventory="All ingredients are listed-active or exempt.",
        tsca_snur="None of the ingredients are listed.",
        tsca_export="None of the ingredients are listed.",

        # Section 16
        prepared_by="Capacity Chemical LLC, EHS Department",
        preparation_date="04.06.2026",
        revision_date="04.06.2026",
        revision_number="1",
        supersedes="N/A",
        nfpa_ratings="0-0-0",
        hmis_ratings="0-0-0",
    )


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import json as _json
    from sds_input import run_wizard

    BASE = Path(__file__).parent

    print("Initialising SDS Generator...")
    gen = SDSGenerator(
        BASE / "data/raw_material_db.json",
        BASE / "config/api_config.json",
    )
    brand = load_brand()
    with open(BASE / "data/raw_material_db.json", encoding="utf-8") as _f:
        _db = {r["cas"]: r for r in _json.load(_f)}

    run_wizard(gen, brand, _db, BASE / "output")
