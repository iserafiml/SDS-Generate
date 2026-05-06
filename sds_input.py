"""
Interactive CLI wizard for the SDS Generator.

Entry point: run_wizard(gen, brand, db, output_dir)
"""

from __future__ import annotations

import sys
from pathlib import Path

from brand_config import BrandConfig, load_brand
from ghs_classifier import H_STATEMENTS, HAZARD_MENU, build_manual_category
from sds_data_model import (
    GHSClassification,
    GHSHazardCategory,
    ManufacturerInfo,
    SDSIngredient,
    SDSPhysicalProperties,
    SDSProduct,
)

_NOT_AVAIL = "Not determined or not available."


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def run_wizard(gen: object, brand: BrandConfig, db: dict, output_dir: Path) -> None:
    """Run the interactive wizard. Handles both menu options."""
    from sds_pdf_builder import build_sds_pdf

    wizard = InputWizard(db, brand)
    product = wizard.run()

    if product is None:
        from sds_generator import sds_from_oxystrike
        product = sds_from_oxystrike()
        manual_categories: list[GHSHazardCategory] = []
    else:
        manual_categories = getattr(product, "_manual_ghs_categories", [])

    print(f"\nRunning GHS classification + database enrichment + Claude API for '{product.product_name}'...")
    sds_doc = gen.generate(product)  # type: ignore[attr-defined]

    if manual_categories:
        _merge_manual_categories(sds_doc.product.classification, manual_categories)

    out_path = output_dir / f"{product.product_name}_SDS.pdf"
    print(f"\nBuilding PDF → {out_path}")
    out = build_sds_pdf(sds_doc, out_path, brand)
    print(f"Done: {out}")


def _merge_manual_categories(
    clf: GHSClassification,
    manual: list[GHSHazardCategory],
) -> None:
    existing = {c.class_name for c in clf.categories}
    for mc in manual:
        if mc.class_name not in existing:
            clf.categories.append(mc)

    seen_h: set[str] = set()
    all_h_codes: list[str] = []
    for cat in clf.categories:
        for code in cat.h_codes:
            if code not in seen_h:
                seen_h.add(code)
                all_h_codes.append(code)
    all_h_codes.sort(key=lambda s: int(s[1:4]))
    clf.all_h_statements = [f"{c} {H_STATEMENTS.get(c, c)}" for c in all_h_codes]
    clf.pictograms_needed = sorted({pic for cat in clf.categories for pic in cat.pictogram_codes})


# ---------------------------------------------------------------------------
# Wizard class
# ---------------------------------------------------------------------------

class InputWizard:
    def __init__(self, db: dict, brand: BrandConfig) -> None:
        self._db = db
        self._brand = brand

    # ------------------------------------------------------------------
    # Public
    # ------------------------------------------------------------------

    def run(self) -> SDSProduct | None:
        """Show startup menu. Returns SDSProduct or None (demo mode)."""
        print("\n=== SDS Generator ===")
        print("1. Generate OxyStrike demo")
        print("2. Enter new product interactively")
        for _ in range(5):
            choice = input("Enter choice (1 or 2): ").strip()
            if choice == "1":
                return None
            if choice == "2":
                return self._collect_product()
            print("  Invalid choice — please enter 1 or 2.")
        print("No valid choice entered. Exiting.")
        sys.exit(1)

    # ------------------------------------------------------------------
    # Product assembly
    # ------------------------------------------------------------------

    def _collect_product(self) -> SDSProduct:
        name, code, ptype = self._prompt_identification()
        mfr = self._prompt_manufacturer()
        ingredients, manual_categories = self._prompt_ingredients()
        props = self._prompt_physical_properties()

        product = SDSProduct(
            product_name=name,
            product_code=code,
            product_type=ptype,
            manufacturer=mfr,
            ingredients=ingredients,
            physical_properties=props,
            recommended_use="Please see Labels/TDS for the instructions.",
            restrictions_on_use="Not determined or not applicable.",
            reactivity="Not reactive under recommended handling and storage conditions.",
            chemical_stability="Stable under recommended handling and storage conditions.",
            hazardous_reactions=(
                "Hazardous reactions are not anticipated under recommended conditions of "
                "handling and storage."
            ),
            conditions_to_avoid=(
                "Avoid extreme heat, open flames, hot surfaces, sparks, ignition sources "
                "and incompatible materials."
            ),
            incompatible_materials="None known.",
            hazardous_decomposition=(
                "Under normal conditions of storage and use, hazardous decomposition products "
                "should not be produced."
            ),
            disposal_methods=(
                "Waste material must be disposed of in accordance with the national and local "
                "regulations."
            ),
            disposal_container="Not determined or not applicable.",
            tsca_inventory="All ingredients are listed-active or exempt.",
            tsca_snur="None of the ingredients are listed.",
            tsca_export="None of the ingredients are listed.",
        )
        product._manual_ghs_categories = manual_categories  # type: ignore[attr-defined]
        return product

    # ------------------------------------------------------------------
    # Individual prompt sections
    # ------------------------------------------------------------------

    def _prompt_identification(self) -> tuple[str, str, str]:
        print("\n--- Product Identification ---")
        name = ""
        for _ in range(5):
            name = input("Product name (required): ").strip()
            if name:
                break
            print("  Product name cannot be empty.")
        else:
            print("Product name is required. Exiting.")
            sys.exit(1)

        code = input("Product code (optional): ").strip()
        ptype = input("Product type (e.g. Oxidizing cleaner, optional): ").strip()
        return name, code, ptype

    def _prompt_manufacturer(self) -> ManufacturerInfo:
        print("\n--- Manufacturer Info (press Enter to use default) ---")
        b = self._brand

        def _ask(label: str, default: str) -> str:
            val = input(f"{label} [{default}]: ").strip()
            return val if val else default

        company   = _ask("Company name",      b.company_name)
        phone     = _ask("Phone",             b.phone)
        em_phone  = _ask("Emergency phone",   "1-800-424-9300 (24 hours)")
        em_prov   = _ask("Emergency provider","CHEMTREC")
        website   = _ask("Website",           b.website)

        return ManufacturerInfo(
            company_name=company,
            phone=phone,
            emergency_phone=em_phone,
            emergency_provider=em_prov,
            website=website,
        )

    def _prompt_ingredients(self) -> tuple[list[SDSIngredient], list[GHSHazardCategory]]:
        ingredients: list[SDSIngredient] = []
        manual_categories: list[GHSHazardCategory] = []
        seen_cas: set[str] = set()

        while True:
            idx = len(ingredients) + 1
            print(f"\n--- Ingredient #{idx} (press Enter with no CAS to finish) ---")
            cas = input("CAS number: ").strip()
            if not cas:
                if not ingredients:
                    print("  At least one ingredient is required.")
                    continue
                break

            if cas in seen_cas:
                print(f"  Duplicate CAS {cas} — skipping.")
                continue
            seen_cas.add(cas)

            rec = self._db.get(cas)
            suggested_name = ""
            if rec:
                suggested_name = rec["name"]
                print(f"  Found in DB: {suggested_name}")
            else:
                print(f"  CAS {cas} not found in database.")
                yn = input("  Manually specify GHS hazard class? (y/n): ").strip().lower()
                if yn == "y":
                    manual_categories.extend(self._prompt_manual_hazards(cas))

            name_prompt = f"Ingredient name [{suggested_name}]: " if suggested_name else "Ingredient name: "
            ing_name = ""
            for _ in range(5):
                raw = input(name_prompt).strip()
                if raw:
                    ing_name = raw
                    break
                if suggested_name:
                    ing_name = suggested_name
                    break
                print("  Ingredient name is required.")
            else:
                print("  Ingredient name is required. Skipping this ingredient.")
                seen_cas.discard(cas)
                continue

            low = self._prompt_float("Concentration low %", min_val=0.0)
            high = self._prompt_float_min("Concentration high %", min_val=low)
            function = input("Function/purpose (optional): ").strip()

            ingredients.append(SDSIngredient(
                name=ing_name,
                cas_number=cas,
                wt_percent_low=low,
                wt_percent_high=high,
                function=function,
            ))
            print(f"  Added: {ing_name} ({low}–{high}%)")

        return ingredients, manual_categories

    def _prompt_manual_hazards(self, cas: str) -> list[GHSHazardCategory]:
        result: list[GHSHazardCategory] = []
        print("  Available GHS hazard classes:")
        for i, entry in enumerate(HAZARD_MENU, 1):
            cats = ", ".join(entry["categories"])
            print(f"  {i:2d}. {entry['display']:<40} (categories: {cats})")

        while True:
            raw = input("  Enter class number (0 to finish): ").strip()
            if raw == "0" or raw == "":
                break
            if not raw.isdigit() or not (1 <= int(raw) <= len(HAZARD_MENU)):
                print(f"  Please enter a number between 1 and {len(HAZARD_MENU)}, or 0 to finish.")
                continue
            entry = HAZARD_MENU[int(raw) - 1]
            valid_cats = entry["categories"]
            cat_str = ", ".join(valid_cats)
            category = ""
            for _ in range(5):
                category = input(f"  Category for '{entry['display']}' ({cat_str}): ").strip().upper()
                if category in [c.upper() for c in valid_cats]:
                    category = next(c for c in valid_cats if c.upper() == category)
                    break
                print(f"  Invalid category. Valid options: {cat_str}")
            else:
                print("  Skipping this hazard class.")
                continue

            result.append(build_manual_category(entry["key"], category))
            print(f"  Added: {entry['display']} category {category}")
            yn = input("  Add another hazard class? (y/n): ").strip().lower()
            if yn != "y":
                break

        return result

    def _prompt_physical_properties(self) -> SDSPhysicalProperties:
        print("\n--- Physical Properties (press Enter to skip) ---")

        def _ask(label: str) -> str:
            val = input(f"{label}: ").strip()
            return val if val else _NOT_AVAIL

        return SDSPhysicalProperties(
            appearance=_ask("Appearance"),
            odour=_ask("Odour"),
            pH=_ask("pH"),
            density=_ask("Density (g/mL)"),
            odour_threshold=_NOT_AVAIL,
            melting_point=_NOT_AVAIL,
            boiling_point=_NOT_AVAIL,
            flash_point=_NOT_AVAIL,
            evaporation_rate=_NOT_AVAIL,
            flammability=_NOT_AVAIL,
            upper_explosive_limit=_NOT_AVAIL,
            lower_explosive_limit=_NOT_AVAIL,
            vapour_pressure=_NOT_AVAIL,
            vapour_density=_NOT_AVAIL,
            relative_density=_NOT_AVAIL,
            solubility=_NOT_AVAIL,
            partition_coefficient=_NOT_AVAIL,
            auto_ignition_temp=_NOT_AVAIL,
            decomposition_temp=_NOT_AVAIL,
            viscosity=_NOT_AVAIL,
        )

    # ------------------------------------------------------------------
    # Numeric input helpers
    # ------------------------------------------------------------------

    def _prompt_float(self, label: str, min_val: float = 0.0) -> float:
        while True:
            raw = input(f"{label}: ").strip()
            try:
                val = float(raw)
            except ValueError:
                print(f"  Please enter a number.")
                continue
            if val < min_val:
                print(f"  Value must be >= {min_val}.")
                continue
            return val

    def _prompt_float_min(self, label: str, min_val: float) -> float:
        while True:
            raw = input(f"{label}: ").strip()
            try:
                val = float(raw)
            except ValueError:
                print("  Please enter a number.")
                continue
            if val < min_val:
                print(f"  High% must be >= low% ({min_val}).")
                continue
            return val
