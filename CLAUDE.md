# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Running the project

```bash
# CLI mode (interactive terminal wizard)
python3 sds_generator.py

# Install dependencies
pip3 install -r requirements.txt
```

`config/api_config.json` must contain a valid Anthropic API key (`{"api_key": "sk-ant-..."}`).

Generated PDFs are written to `output/`.

## Architecture

The pipeline runs in this order every time a product is generated:

```
SDSProduct (input)
  → GHSClassifier.classify()          # concentration thresholds → H/P codes
  → SDSGenerator._enrich_from_db()    # OELs, toxicology, aquatic, regulatory
  → SDSGenerator._generate_first_aid()  # Claude API → JSON → Section 4 text
  → SDSGenerator._generate_firefighting() # Claude API → JSON → Section 5 text
  → SDSGenerator._build_transport()   # rule-based DOT/IMDG/IATA
  → build_sds_pdf()                   # ReportLab → PDF
```

**Key files:**

- `sds_data_model.py` — All dataclasses for the 16-section SDS. `SDSProduct` holds every field; `SDSDocument` wraps it. `GHSClassification` and `GHSHazardCategory` are produced by the classifier.
- `ghs_classifier.py` — Pure classification logic. `HAZARD_MENU` and `build_manual_category()` are public exports used by the input wizard for unknown-CAS ingredients.
- `sds_generator.py` — `SDSGenerator` class orchestrates the full pipeline. `sds_from_oxystrike()` is a factory for the OxyStrike demo product.
- `sds_input.py` — Interactive CLI wizard (`InputWizard`) and `run_wizard()` entry point. Handles CAS lookup, manual GHS hazard selection, and calls `_merge_manual_categories()` for unknown-CAS ingredients.
- `sds_pdf_builder.py` — ReportLab Platypus renderer. Each SDS section is a discrete `build_section_N_*()` function. Architecture mirrors the TDS Generator's `tds_pdf_builder.py`.
- `brand_config.py` — `BrandConfig` dataclass + `load_brand()` / `save_brand()`. Reads from `config/brand_config.json`; returns hardcoded defaults if file absent.
- `data/raw_material_db.json` — Chemical database keyed by CAS number. Each record has: `ghs_triggers` (hazard class → threshold_pct + category), `oels`, `toxicology`, `aquatic_toxicology`, `persistence`, `bioaccumulation`, `mobility`, `iarc_classification`, `ntp_classification`, `regulatory`. Currently contains 5 chemicals (H₂O₂, HNO₃, CH₃COOH, peracetic acid, H₂SO₄).

## GHS classification internals

`GHSClassifier` only processes ingredients whose CAS exists in the DB — unknown CAS entries are silently skipped. Classification uses `wt_percent_high` (upper bound) for worst-case assessment.

The private module-level dicts `_CATEGORY_H_CODES`, `_CATEGORY_P_CODES`, `_PICTOGRAM_MAP`, `_CLASS_DISPLAY` define all H/P codes. `HAZARD_MENU` exposes only the 9 hazard classes that have H-code entries defined. `build_manual_category(hazard_class, category)` uses the same lookup logic as `GHSClassifier._build_categories()` without requiring a DB entry.

## Claude API usage (Sections 4 & 5)

Both `_generate_first_aid()` and `_generate_firefighting()` use `claude-sonnet-4-6` with prompt caching (`cache_control: ephemeral` on the system prompt). They expect the model to return a plain JSON object — `_extract_json()` strips any code fences before parsing. Both methods short-circuit if fields are already populated on the product.

## Adding a new chemical to the database

Add a JSON object to `data/raw_material_db.json` following the exact schema of existing entries. Required keys: `cas`, `name`, `ghs_triggers`. All other keys (`oels`, `toxicology`, `aquatic_toxicology`, `persistence`, `bioaccumulation`, `mobility`, `iarc_classification`, `ntp_classification`, `regulatory`) are optional but omitting them will produce blank SDS sections.

## Known limitations

- **Transport logic** is simplistic: oxidizing+corrosive → UN3139, oxidizing only → UN2015, corrosive only → UN1760. IMDG and IATA entries are always "Not regulated".
- **Database** only covers the 5 OxyStrike ingredients. Ingredients with unknown CAS numbers are skipped by the GHS classifier (manual hazard selection via wizard is the workaround).
- **GUI** is CLI-only (`sds_input.py`). A Flask web interface is planned.
