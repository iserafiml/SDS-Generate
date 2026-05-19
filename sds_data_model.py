"""
Core data model for the SDS Generation Engine.
All 16 SDS sections are represented as fields on SDSProduct.
All dataclasses use empty-string / empty-list defaults so partial population is safe.

Key difference from TDS data_model.py:
  - SDSIngredient stores wt_percent as two floats (low/high) for classifier thresholds
  - NO ingredient redaction — CAS numbers and concentrations are always disclosed
"""

from __future__ import annotations

from dataclasses import dataclass, field


# ---------------------------------------------------------------------------
# Section 2 — GHS Classification
# ---------------------------------------------------------------------------

@dataclass
class GHSHazardCategory:
    """One classified hazard class/category pair."""
    class_name: str = ""          # "Oxidizing liquids"
    category: str = ""            # "2" or "1A" (string — handles "1A", "1B" etc.)
    h_codes: list[str] = field(default_factory=list)
    p_codes: list[str] = field(default_factory=list)
    pictogram_codes: list[str] = field(default_factory=list)


@dataclass
class GHSClassification:
    """Aggregated output of the GHS classifier."""
    signal_word: str = ""
    categories: list[GHSHazardCategory] = field(default_factory=list)
    pictograms_needed: list[str] = field(default_factory=list)    # deduplicated list
    all_h_statements: list[str] = field(default_factory=list)     # ordered by H-code number
    all_p_statements: list[str] = field(default_factory=list)     # grouped P2xx/P3xx/P4xx/P5xx
    # Ingredient names the classifier evaluated (CAS found in DB) and the
    # subset that triggered ≥1 hazard. Used by the fuzzy-formula renderer to
    # decide which ingredients are safe to aggregate as "non-hazardous".
    classified_ingredients: list[str] = field(default_factory=list)
    hazardous_ingredients: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Section 3 — Ingredients
# ---------------------------------------------------------------------------

@dataclass
class SDSIngredient:
    """
    One ingredient row for Section 3.
    Uses two floats for concentration (not a string) so the classifier can compare
    thresholds directly without regex parsing.  wt_percent_high is used for
    worst-case (conservative) GHS classification.
    """
    name: str = ""
    cas_number: str = ""
    wt_percent_low: float = 0.0
    wt_percent_high: float = 0.0
    function: str = ""
    trade_secret: bool = False    # always False for regulatory SDS; reserved
    # Supplied-grade active fraction (e.g. 0.5 for a "50%" raw material).
    # The classifier multiplies wt_percent by this to obtain the pure-substance
    # concentration ONLY for records whose thresholds are pure-substance based
    # (threshold_basis=="pure"); 1.0 = neat / unknown (no conversion).
    active_fraction: float = 1.0


# ---------------------------------------------------------------------------
# Section 8 — Occupational Exposure Limits
# ---------------------------------------------------------------------------

@dataclass
class OELEntry:
    """One row of the Section 8 OEL table."""
    substance_name: str = ""
    cas: str = ""
    authority: str = ""           # "ACGIH" | "NIOSH" | "OSHA" | "CA"
    oel_type: str = ""            # "TWA" | "STEL" | "IDLH" | "Ceiling" | "TWA-PEL"
    value: str = ""               # kept as string to preserve ">" prefix
    unit: str = ""                # "ppm" | "mg/m³"


# ---------------------------------------------------------------------------
# Section 9 — Physical and Chemical Properties
# ---------------------------------------------------------------------------

@dataclass
class SDSPhysicalProperties:
    """All 20 physical/chemical properties required by OSHA HCS 2012 Section 9."""
    appearance: str = ""
    odour: str = ""
    odour_threshold: str = ""
    pH: str = ""
    melting_point: str = ""
    boiling_point: str = ""
    flash_point: str = ""
    evaporation_rate: str = ""
    flammability: str = ""
    upper_explosive_limit: str = ""
    lower_explosive_limit: str = ""
    vapour_pressure: str = ""
    vapour_density: str = ""
    density: str = ""             # absolute density (g/mL or g/cm³)
    relative_density: str = ""    # relative to water
    solubility: str = ""
    partition_coefficient: str = ""   # log Pow (n-octanol/water)
    auto_ignition_temp: str = ""
    decomposition_temp: str = ""
    viscosity: str = ""


# ---------------------------------------------------------------------------
# Section 11 — Toxicological Information
# ---------------------------------------------------------------------------

@dataclass
class ToxicologyRecord:
    """One LD50/LC50 data row for the Section 11 acute toxicity table."""
    substance: str = ""
    route: str = ""               # "Oral" | "Dermal" | "Inhalation ATE"
    species: str = ""             # "Rat" | "Rabbit" | "Mouse"
    result: str = ""              # "LD50 Rat: 693.7 mg/kg"


# ---------------------------------------------------------------------------
# Section 12 — Ecological Information
# ---------------------------------------------------------------------------

@dataclass
class AquaticToxRecord:
    """One aquatic toxicity data row for Section 12."""
    substance: str = ""
    organism_type: str = ""       # "Fish" | "Aquatic Invertebrates" | "Aquatic Plants"
    organism: str = ""            # "Pimephales promelas"
    metric: str = ""              # "LC50" | "EC50" | "NOEC"
    value: str = ""               # "16.4 mg/L (96 hr)"
    endpoint: str = ""            # "mortality" | "growth rate" | ""


# ---------------------------------------------------------------------------
# Section 14 — Transport Information
# ---------------------------------------------------------------------------

@dataclass
class TransportInfo:
    """Transport classification for one mode (DOT / IMDG / IATA)."""
    mode: str = ""                # "DOT" | "IMDG" | "IATA"
    un_number: str = ""
    proper_shipping_name: str = ""
    hazard_class: str = ""        # "5.1" or "5.1 (8)" for subsidiary
    packing_group: str = ""       # "I" | "II" | "III"
    labels_required: str = ""
    environmental_hazard: str = ""    # "Marine Pollutant: Peroxyacetic acid" or "None"
    special_precautions: str = ""


# ---------------------------------------------------------------------------
# Section 15 — Regulatory Information
# ---------------------------------------------------------------------------

@dataclass
class RegulatoryListing:
    """Regulatory status of one ingredient for Section 15."""
    substance_name: str = ""
    cas: str = ""
    tsca_listed: bool = False
    sara_302: bool = False
    sara_302_tpq_lbs: str = ""
    sara_313: bool = False
    cercla_listed: bool = False
    cercla_rq_lbs: str = ""
    rcra_code: str = ""
    caa_112r: bool = False
    prop_65: bool = False
    prop_65_warning: str = ""
    rtk_states: list[str] = field(default_factory=list)   # e.g. ["MA", "NJ", "NY", "PA"]


# ---------------------------------------------------------------------------
# Manufacturer Info (Section 1)
# ---------------------------------------------------------------------------

@dataclass
class ManufacturerInfo:
    company_name: str = ""
    address_line1: str = ""
    city_state_zip: str = ""
    country: str = ""
    phone: str = ""
    website: str = ""
    email: str = ""
    emergency_phone: str = ""
    emergency_provider: str = ""      # "CHEMTREC"
    emergency_account: str = ""


# ---------------------------------------------------------------------------
# Master SDSProduct — all 16 section data fields
# ---------------------------------------------------------------------------

@dataclass
class SDSProduct:
    # ---- Section 1: Identification ----
    product_name: str = ""
    product_code: str = ""
    product_type: str = ""
    manufacturer: ManufacturerInfo = field(default_factory=ManufacturerInfo)
    recommended_use: str = ""
    restrictions_on_use: str = ""

    # ---- Section 2: Hazard Identification ----
    classification: GHSClassification = field(default_factory=GHSClassification)
    label_notes: str = ""                        # supplemental label text

    # ---- Section 3: Composition/Information on Ingredients ----
    ingredients: list[SDSIngredient] = field(default_factory=list)
    additional_ingredient_info: str = "None"
    # When True, Section 3 is rendered "fuzzy": exact %s become standard
    # disclosure bands and known non-hazardous proprietary components are
    # aggregated into one row. Classification & Sections 8/11/12/15 still use
    # the true ingredient list and true concentrations.
    fuzzy_formula: bool = False

    # ---- Section 4: First Aid Measures ----
    first_aid_inhalation: str = ""
    first_aid_skin: str = ""
    first_aid_eye: str = ""
    first_aid_ingestion: str = ""
    first_aid_general: str = ""
    first_aid_symptoms: str = ""
    first_aid_doctor_notes: str = "Treat symptomatically."

    # ---- Section 5: Firefighting Measures ----
    extinguishing_media: str = ""
    unsuitable_extinguishing_media: str = ""
    firefighting_hazards: str = ""
    firefighting_ppe: str = ""
    firefighting_precautions: str = ""

    # ---- Section 6: Accidental Release Measures ----
    spill_personal_precautions: str = ""
    spill_environmental_precautions: str = ""
    spill_containment_cleanup: str = ""

    # ---- Section 7: Handling and Storage ----
    handling_precautions: str = ""
    storage_conditions: str = ""
    specific_end_use: str = ""

    # ---- Section 8: Exposure Controls / Personal Protection ----
    control_parameters: list[OELEntry] = field(default_factory=list)
    biological_limit_values: str = "No biological exposure limits noted for the ingredient(s)."
    engineering_controls: str = ""
    ppe_respiratory: str = ""
    ppe_hand: str = ""
    ppe_eye: str = ""
    ppe_skin: str = ""
    hygienic_measures: str = ""

    # ---- Section 9: Physical and Chemical Properties ----
    physical_properties: SDSPhysicalProperties = field(default_factory=SDSPhysicalProperties)

    # ---- Section 10: Stability and Reactivity ----
    reactivity: str = ""
    chemical_stability: str = ""
    hazardous_reactions: str = ""
    conditions_to_avoid: str = ""
    incompatible_materials: str = ""
    hazardous_decomposition: str = ""

    # ---- Section 11: Toxicological Information ----
    toxicology_records: list[ToxicologyRecord] = field(default_factory=list)
    skin_corrosion_result: str = ""
    eye_damage_result: str = ""
    sensitisation: str = ""
    mutagenicity: str = ""
    carcinogenicity_iarc: str = ""
    carcinogenicity_ntp: str = ""
    osha_carcinogens: str = "Not applicable"
    reproductive_toxicity: str = ""
    stot_single: str = ""
    stot_repeated: str = ""
    aspiration_hazard: str = ""

    # ---- Section 12: Ecological Information ----
    aquatic_tox_records: list[AquaticToxRecord] = field(default_factory=list)
    chronic_tox_records: list[AquaticToxRecord] = field(default_factory=list)
    persistence_degradability: list[tuple[str, str]] = field(default_factory=list)
    bioaccumulation: list[tuple[str, str]] = field(default_factory=list)
    mobility: list[tuple[str, str]] = field(default_factory=list)
    pbt_vpvb: str = ""
    other_adverse_effects: str = "No data available."

    # ---- Section 13: Disposal Considerations ----
    disposal_methods: str = ""
    disposal_container: str = ""

    # ---- Section 14: Transport Information ----
    transport: list[TransportInfo] = field(default_factory=list)

    # ---- Section 15: Regulatory Information ----
    regulatory_listings: list[RegulatoryListing] = field(default_factory=list)
    tsca_inventory: str = "All ingredients are listed-active or exempt."
    tsca_snur: str = "None of the ingredients are listed."
    tsca_export: str = "None of the ingredients are listed."
    prop_65_warning_text: str = ""

    # ---- Section 16: Other Information ----
    prepared_by: str = ""
    preparation_date: str = ""
    revision_date: str = ""
    revision_number: str = ""
    supersedes: str = ""
    disclaimer: str = (
        "This product has been classified in accordance with OSHA HCS 2012 guidelines. "
        "The information provided in this SDS is correct, to the best of our knowledge, "
        "based on information available. The information given is designed only as a "
        "guidance for safe handling, use, storage, transportation and disposal and is "
        "not to be considered a warranty or quality specification."
    )
    nfpa_ratings: str = "0-0-0"
    hmis_ratings: str = "0-0-0"
    abbreviations: str = "None"
    generated_date: str = ""


# ---------------------------------------------------------------------------
# Document wrapper
# ---------------------------------------------------------------------------

@dataclass
class SDSDocument:
    product: SDSProduct = field(default_factory=SDSProduct)
    version: str = "1.0"


# ---------------------------------------------------------------------------
# Safe dict → SDSProduct conversion (for future Claude API responses)
# ---------------------------------------------------------------------------

def dict_to_sds_product(d: dict) -> SDSProduct:
    """Safely convert a raw dict (e.g. from Claude JSON) into a typed SDSProduct."""
    def _str(key: str) -> str:
        return str(d.get(key) or "")

    def _list(key: str) -> list:
        v = d.get(key)
        return v if isinstance(v, list) else []

    def _dict_val(key: str) -> dict:
        v = d.get(key)
        return v if isinstance(v, dict) else {}

    mfr_raw = _dict_val("manufacturer")
    mfr = ManufacturerInfo(
        company_name=str(mfr_raw.get("company_name") or ""),
        address_line1=str(mfr_raw.get("address_line1") or ""),
        city_state_zip=str(mfr_raw.get("city_state_zip") or ""),
        country=str(mfr_raw.get("country") or ""),
        phone=str(mfr_raw.get("phone") or ""),
        website=str(mfr_raw.get("website") or ""),
        email=str(mfr_raw.get("email") or ""),
        emergency_phone=str(mfr_raw.get("emergency_phone") or ""),
        emergency_provider=str(mfr_raw.get("emergency_provider") or ""),
        emergency_account=str(mfr_raw.get("emergency_account") or ""),
    )

    pp_raw = _dict_val("physical_properties")
    pp = SDSPhysicalProperties(**{
        k: str(pp_raw.get(k) or "")
        for k in SDSPhysicalProperties.__dataclass_fields__
    })

    ings = [
        SDSIngredient(
            name=str(c.get("name") or ""),
            cas_number=str(c.get("cas_number") or ""),
            wt_percent_low=float(c.get("wt_percent_low") or 0),
            wt_percent_high=float(c.get("wt_percent_high") or 0),
            function=str(c.get("function") or ""),
        )
        for c in _list("ingredients") if isinstance(c, dict)
    ]

    return SDSProduct(
        product_name=_str("product_name"),
        product_code=_str("product_code"),
        product_type=_str("product_type"),
        manufacturer=mfr,
        recommended_use=_str("recommended_use"),
        restrictions_on_use=_str("restrictions_on_use"),
        ingredients=ings,
        physical_properties=pp,
        preparation_date=_str("preparation_date"),
        generated_date=_str("generated_date"),
    )


# ---------------------------------------------------------------------------
# Smoke test
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    p = SDSProduct(
        product_name="OxyStrike",
        product_code="CC1383",
        manufacturer=ManufacturerInfo(
            company_name="Capacity Chemical LLC",
            emergency_phone="1-800-424-9300",
            emergency_provider="CHEMTREC",
        ),
    )
    p.ingredients.append(SDSIngredient(
        name="Hydrogen peroxide", cas_number="7722-84-1",
        wt_percent_low=20.0, wt_percent_high=25.0,
        function="Active oxidant",
    ))
    doc = SDSDocument(product=p)
    print(f"OK: {doc.product.product_name} ({doc.product.product_code}), "
          f"{len(doc.product.ingredients)} ingredient(s)")
    print(f"    Manufacturer: {doc.product.manufacturer.company_name}")
    print(f"    Emergency: {doc.product.manufacturer.emergency_provider} "
          f"{doc.product.manufacturer.emergency_phone}")
