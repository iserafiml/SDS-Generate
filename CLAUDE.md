# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Running the project

```bash
# Web UI (Flask) — primary interface
python3 sds_app.py                 # http://localhost:5001

# CLI mode (interactive terminal wizard)
python3 sds_generator.py

# Install dependencies
pip3 install -r requirements.txt

# (Re)generate the GHS pictogram PNG assets
python3 make_pictograms.py
```

`config/api_config.json` must contain a valid Anthropic API key (`{"api_key": "sk-ant-..."}`).

Generated PDFs are written to `output/`.

## Architecture

The pipeline runs in this order every time a product is generated:

```
SDSProduct (input)
  → GHSClassifier.classify()              # concentration thresholds → H/P codes
  → SDSGenerator._ai_enrich_db()          # Claude fills empty DB fields, writes back to JSON (cached)
  → SDSGenerator._enrich_from_db()        # OELs, toxicology, aquatic, regulatory, Prop 65
  → SDSGenerator._generate_first_aid()    # Claude API → JSON → Section 4 text
  → SDSGenerator._generate_firefighting() # Claude API → JSON → Section 5 text
  → SDSGenerator._generate_handling_storage_ppe()  # Claude → Sections 6/7/8/10/13 (guaranteed defaults)
  → SDSGenerator._generate_physical_properties()   # Claude → Section 9 estimates (marked "(estimated)")
  → SDSGenerator._consistency_pass()      # logs prose/classification contradictions
  → SDSGenerator._build_transport()       # rule-based DOT/IMDG/IATA
  → build_sds_pdf()                       # ReportLab → PDF
```

**Key files:**

- `sds_data_model.py` — All dataclasses for the 16-section SDS. `SDSProduct` holds every field; `SDSDocument` wraps it. `GHSClassification` and `GHSHazardCategory` are produced by the classifier.
- `ghs_classifier.py` — Pure classification logic. `HAZARD_MENU` and `build_manual_category()` are public exports used by the input wizard for unknown-CAS ingredients.
- `sds_generator.py` — `SDSGenerator` class orchestrates the full pipeline. `sds_from_oxystrike()` is a factory for the OxyStrike demo product.
- `sds_input.py` — Interactive CLI wizard (`InputWizard`) and `run_wizard()` entry point. Handles CAS lookup, manual GHS hazard selection, and calls `_merge_manual_categories()` for unknown-CAS ingredients.
- `sds_app.py` — Flask web UI. Routes: `/` (form), `/api/search_materials?q=` (RM#/CAS/name autocomplete over `rm_index.json` + DB), `/lookup_cas`, `/lookup_rm`, `/generate` (async job), `/progress/<id>` (SSE), `/download/<file>`. Runs on port 5001.
- `templates/index.html` — Single-page form. Each ingredient row is one searchable autocomplete field (backed by `/api/search_materials`) that auto-fills CAS/name/RM and shows an In-DB badge; unknown CAS still exposes the manual GHS hazard modal.
- `db_enrichment.py` — `enrich_chemical(client, record)` fills a record's empty `oels`/`toxicology`/`aquatic_toxicology`/persistence/bioaccumulation/mobility/IARC/NTP/`regulatory` fields **and** emits `ghs_health_triggers` (carcinogenicity / mutagenicity / reproductive toxicity / respiratory & skin sensitization / STOT-RE / aspiration), merged into the record's `ghs_triggers` so CMR hazards reach Section 2 + the GHS08 pictogram via the normal classifier path. Provenance is stamped as `_enrichment: {date, model, v}`. `needs_enrichment()` re-verifies only when that metadata is missing, older than `REVERIFY_AFTER_DAYS` (365, tracks regulatory drift), produced by a different model, or predates `ENRICHMENT_SCHEMA_VERSION`; `_locked` records are never overwritten; legacy `_ai_enriched` is migrated on next pass. `persist_db()` atomically rewrites the JSON list. Per-field merge protects hand-curated data; the whole `regulatory` block is replaced only when it is the uncurated default skeleton.
- `make_pictograms.py` — Generates the nine `assets/pictograms/GHS0X.png` files (red diamond + symbol, 4× supersampled). The PDF builder prefers these PNGs and falls back to text-label diamonds only if missing. Drop in official UNECE artwork under the same filenames to override.
- `sds_pdf_builder.py` — ReportLab Platypus renderer. Each SDS section is a discrete `build_section_N_*()` function. `_draw_pictogram_row()` loads `assets/pictograms/`. Architecture mirrors the TDS Generator's `tds_pdf_builder.py`.
- `brand_config.py` — `BrandConfig` dataclass + `load_brand()` / `save_brand()`. Reads from `config/brand_config.json`; returns hardcoded defaults if file absent.
- `data/raw_material_db.json` — Chemical database (JSON **list**, indexed by `cas` at load). Each record has: `ghs_triggers` (hazard class → threshold_pct + category), `oels`, `toxicology`, `aquatic_toxicology`, `persistence`, `bioaccumulation`, `mobility`, `iarc_classification`, `ntp_classification`, `regulatory`, optional `_ai_enriched`. ~114 chemicals; most have `ghs_triggers`/`regulatory` but their toxicology/OEL/aquatic fields are filled lazily by the AI enrichment layer on first use.
- `data/rm_index.json` — RM# → `{cas, name}` map (~201 entries) powering RM lookup and material search.

## GHS classification internals

`GHSClassifier` only processes ingredients whose CAS exists in the DB (with `ghs_triggers`) — unknown CAS entries are skipped by the classifier but still appear in Section 3 and are still AI-enriched for Sections 11/15. Classification uses `wt_percent_high` (upper bound) for worst-case assessment.

The private module-level dicts `_CATEGORY_H_CODES`, `_CATEGORY_P_CODES`, `_PICTOGRAM_MAP`, `_CLASS_DISPLAY` define all H/P codes. `HAZARD_MENU` exposes only the 9 hazard classes that have H-code entries defined. `build_manual_category(hazard_class, category)` uses the same lookup logic as `GHSClassifier._build_categories()` without requiring a DB entry.

## Claude API usage

All Claude calls use `claude-sonnet-4-6` with prompt caching (`cache_control: ephemeral` on the system prompt) and `_extract_json()` to strip code fences. Each generator method short-circuits if its target fields are already populated:

- `_generate_first_aid()` / `_generate_firefighting()` — Sections 4 & 5 narrative. Prompts are hazard-class-driven and explicitly forbid assuming unlisted properties (e.g. oxidizing) — do not reintroduce hardcoded "oxidizing acid" phrasing.
- `_generate_handling_storage_ppe()` — Sections 6/7/8/10/13. Any field still blank after the call is filled from `_HSP_DEFAULTS`, so these sections are never empty.
- `_generate_physical_properties()` — Section 9. Inferable values get an "(estimated)" suffix; non-inferable ones return "Not determined or not available."
- `db_enrichment.enrich_chemical()` — fills empty DB record fields; result is written back to `raw_material_db.json` so each chemical costs one API call ever.

## Adding a new chemical to the database

Append a JSON object to the `data/raw_material_db.json` list. Required: `cas`, `name`, `ghs_triggers`. The toxicology/OEL/aquatic/regulatory fields may be omitted — the AI enrichment layer fills them on first use and persists the result. To lock in hand-curated data, populate the fields and set `"_ai_enriched": true` so Claude never overwrites them.

## Known limitations

- **Transport logic** is rule-based: UN3139 (oxidizing±corrosive) / UN1760 (corrosive). Packing group is derived from the skin-corrosion sub-category (1A→I, 1B→II, 1C→III). IMDG and IATA are always "Not regulated".
- **GHS classifier** still only processes ingredients whose CAS is in the DB with `ghs_triggers`; unknown CAS needs manual hazard selection (web modal / CLI wizard). Carcinogenicity/CMR/sensitization now reach Section 2 + GHS08 **via AI-enriched `ghs_triggers`**, gated by GHS mixture concentration cutoffs (e.g. a carcinogen below 0.1 % correctly does not classify the mixture, though Prop 65 still flags it in Section 15).
- **AI-estimated content** (Section 9 values, enriched toxicology/regulatory) is best-effort and must be reviewed before a regulated SDS is issued; `_consistency_pass()` logs obvious contradictions to the console but does not block.
