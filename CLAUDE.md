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
  → SDSGenerator._ai_enrich_db()          # Claude fills empty DB fields once, writes back (cached) — BEFORE classify
  → GHSClassifier.classify()              # ghs_triggers × wt% (× active_fraction if threshold_basis=="pure") → H/P codes
  → SDSGenerator._enrich_from_db()        # OELs, toxicology, aquatic, regulatory, Prop 65 (local, from DB)
  → SDSGenerator._generate_first_aid()    # Claude → Section 4 text
  → SDSGenerator._generate_firefighting() # Claude → Section 5 text
  → SDSGenerator._generate_handling_storage_ppe()  # Claude → Sections 6/7/8/10/13 (guaranteed _HSP_DEFAULTS)
  → SDSGenerator._generate_physical_properties()   # Claude → Section 9 estimates ("(estimated)")
  → SDSGenerator._consistency_pass()      # logs prose/classification contradictions
  → nfpa_hmis.derive()                    # local: GHS → NFPA 704 / HMIS III (unless manual override)
  → SDSGenerator._build_transport()       # rule-based DOT/IMDG/IATA
  → build_sds_pdf()                       # ReportLab → PDF  (+ persisted as output/<pdf>.sds.json)
```

Re-issuing a saved SDS under a different company (`/api/reissue`) reloads
the persisted `.sds.json`, swaps Section 1 + brand/logo, and rebuilds the
PDF only — **no AI pipeline, no API cost**.

**Key files:**

- `sds_data_model.py` — All dataclasses for the 16-section SDS. `SDSProduct` holds every field; `SDSDocument` wraps it. `GHSClassification` and `GHSHazardCategory` are produced by the classifier.
- `ghs_classifier.py` — Pure classification logic. `HAZARD_MENU` and `build_manual_category()` are public exports used by the input wizard for unknown-CAS ingredients.
- `sds_generator.py` — `SDSGenerator` class orchestrates the full pipeline. `sds_from_oxystrike()` is a factory for the OxyStrike demo product.
- `sds_input.py` — Interactive CLI wizard (`InputWizard`) and `run_wizard()` entry point. Handles CAS lookup, manual GHS hazard selection, and calls `_merge_manual_categories()` for unknown-CAS ingredients.
- `sds_app.py` — Flask web UI. Routes: `/` (form), `/api/search_materials?q=` (RM#/CAS/name autocomplete over `rm_index.json` + DB), `/lookup_cas`, `/lookup_rm`, `/generate` (async job), `/progress/<id>` (SSE), `/download/<file>`. Runs on port 5001.
- `templates/index.html` — Single-page form. Each ingredient row is one searchable autocomplete field (backed by `/api/search_materials`) that auto-fills CAS/name/RM and shows an In-DB badge; unknown CAS still exposes the manual GHS hazard modal.
- `db_enrichment.py` — `enrich_chemical(client, record)` fills a record's empty `oels`/`toxicology`/`aquatic_toxicology`/persistence/bioaccumulation/mobility/IARC/NTP/`regulatory` fields **and** emits `ghs_health_triggers` (carcinogenicity / mutagenicity / reproductive toxicity / respiratory & skin sensitization / STOT-RE / aspiration), merged into the record's `ghs_triggers` so CMR hazards reach Section 2 + the GHS08 pictogram via the normal classifier path. Provenance is stamped as `_enrichment: {date, model, v}`. `needs_enrichment()` re-verifies only when that metadata is missing, older than `REVERIFY_AFTER_DAYS` (365, tracks regulatory drift), produced by a different model, or predates `ENRICHMENT_SCHEMA_VERSION`; `_locked` records are never overwritten; legacy `_ai_enriched` is migrated on next pass. `persist_db()` atomically rewrites the JSON list. Per-field merge protects hand-curated data; the whole `regulatory` block is replaced only when it is the uncurated default skeleton.
- `nfpa_hmis.py` — `derive(classification, physical_properties)` maps GHS → conservative NFPA 704 / HMIS III ratings (industry heuristic; GHS does not define these). `parse_override()` parses manual form input. Rendered as the colour fire-diamond + HMIS bar in Section 16.
- `company_admin.py` — Reusable company profiles (`config/companies.json`) + 24h emergency contacts (`config/emergency_contacts.json`) + uploaded logos (`config/logos/`). `build_profile(company_id, emergency_id)` → `(BrandConfig, ManufacturerInfo)`. Used by generation and by `/api/reissue`.
- `material_admin.py` / `add_material.py` — Add a raw material to the library (web `/api/add_material` button + CLI). Auto RM#, PubChem CAS lookup when missing (flagged needs_review), `active_fraction` from name/strength, atomic write to `rm_index.json` + DB stub.
- Data tooling (one-off / maintenance, read from `data/sources/`): `build_rm_index.py` (rebuild rm_index from the Items863 master + RM→CAS export), `sync_db_stubs.py` (add `threshold_basis:"pure"` stubs for new CAS), `resolve_missing_cas.py` (PubChem backfill, flagged needs_review), `apply_cas_review.py` (apply the reviewer-edited CAS list), `fix_gcl_thresholds.py` (snap health thresholds to `HEALTH_GCL`), `batch_enrich.py` (crash-safe full-library pre-enrichment).
- `make_pictograms.py` — Offline fallback generator for `assets/pictograms/GHS0X.png`. The real official UN GHS PNGs are committed; the PDF builder prefers them and only falls back to drawn diamonds if missing.
- `sds_pdf_builder.py` — ReportLab Platypus renderer. Each SDS section is a discrete `build_section_N_*()` function. `_draw_pictogram_row()` loads `assets/pictograms/`. Architecture mirrors the TDS Generator's `tds_pdf_builder.py`.
- `brand_config.py` — `BrandConfig` dataclass + `load_brand()` / `save_brand()`. Reads from `config/brand_config.json`; returns hardcoded defaults if file absent.
- `data/raw_material_db.json` — Chemical DB (JSON **list**, indexed by `cas`). ~175 records; per-record `ghs_triggers`, `oels`, `toxicology`, `aquatic_toxicology`, persistence/bioaccumulation/mobility, IARC/NTP, `regulatory`, optional `threshold_basis:"pure"` (stub-origin → active_fraction conversion applies) and `_enrichment:{date,model,v}`. ~171/175 already AI-enriched (batch); the rest fill lazily.
- `data/rm_index.json` — RM# → `{cas, cas_all, name, synonyms, active_fraction, strength_pct, strength_source, needs_review, cas_source}` (242 entries; 225 with CAS). Powers material search/lookup and the supplied-grade → pure-substance conversion.
- `data/sources/` — internal raw-material exports + gap/review reports (**gitignored**); inputs to the data-tooling scripts.
- `config/companies.json`, `config/emergency_contacts.json`, `config/logos/` — issuer profiles (**gitignored**, instance data).

## GHS classification internals

`GHSClassifier` only processes ingredients whose CAS exists in the DB (with `ghs_triggers`) — unknown CAS entries are skipped by the classifier but still appear in Section 3 and are still AI-enriched for Sections 11/15. Classification uses `wt_percent_high` (upper bound) for worst-case assessment.

The private module-level dicts `_CATEGORY_H_CODES`, `_CATEGORY_P_CODES`, `_PICTOGRAM_MAP`, `_CLASS_DISPLAY` define all H/P codes. `HAZARD_MENU` exposes only the 9 hazard classes that have H-code entries defined. `build_manual_category(hazard_class, category)` uses the same lookup logic as `GHSClassifier._build_categories()` without requiring a DB entry.

## Claude API usage

All Claude calls use `claude-sonnet-4-6` with prompt caching (`cache_control: ephemeral` on the system prompt) and `_extract_json()` to strip code fences. Each generator method short-circuits if its target fields are already populated:

- `_generate_first_aid()` / `_generate_firefighting()` — Sections 4 & 5 narrative. Prompts are hazard-class-driven and explicitly forbid assuming unlisted properties (e.g. oxidizing) — do not reintroduce hardcoded "oxidizing acid" phrasing.
- `_generate_handling_storage_ppe()` — Sections 6/7/8/10/13. Any field still blank after the call is filled from `_HSP_DEFAULTS`, so these sections are never empty.
- `_generate_physical_properties()` — Section 9. Inferable values get an "(estimated)" suffix; non-inferable ones return "Not determined or not available."
- `db_enrichment.enrich_chemical()` — fills empty DB record fields **and** emits `ghs_health_triggers` + `ghs_physical_triggers` (merged into `ghs_triggers` only when absent — curated triggers never overwritten), using the authoritative `HEALTH_GCL` / `PHYS_GCL` generic-concentration-limit tables. `ENRICHMENT_SCHEMA_VERSION = 3`. Result written back so each chemical costs **one API call ever** (cached; `batch_enrich.py` front-loads the whole library).

`active_fraction` / `threshold_basis`: a supplied grade ("Sulfuric Acid 50%") carries `active_fraction` in `rm_index`. The classifier multiplies `wt_percent` by it **only** for records flagged `threshold_basis:"pure"` (AI-stub origin, thresholds = pure-substance GHS limits); the ~original curated records have no flag and keep as-supplied behaviour (zero regression).

## Company profiles, fuzzy formula, re-issue

- **Companies/emergency**: managed via the web "Manage" modal or `company_admin` CLI. Generation picks `company_id`/`emergency_id`; that profile fills Section 1 + brand/logo. Two 24h emergency providers ship by default (CHEMTREC + an editable second).
- **Re-issue**: every generated SDS is persisted as `output/<pdf>.sds.json` (`sds_product_to/from_dict`, faithful nested dataclass round-trip). The Re-issue modal / `/api/reissue` re-renders it under a different company with **no AI/API**.
- **Fuzzy formula** (`SDSProduct.fuzzy_formula`): Section 3 only — known non-hazardous in-DB components aggregate into one "Other ingredients" row and %s snap to standard disclosure bands. Classification & Sections 8/11/12/15 still use the true formula.

## Adding a new chemical to the database

Prefer the web "+ New material to library" button or `python3 add_material.py` (handles RM#, PubChem CAS, active_fraction, stub). Manual: append to the `data/raw_material_db.json` list with `cas`, `name`; omit hazard/tox fields and the AI layer fills them on first use. To lock hand-curated data, populate it and set `"_locked": true` (never re-enriched).

## Known limitations (must review before issuing a regulated SDS)

- **AI-estimated content** (Section 9, enriched toxicology/OEL/regulatory, GHS health/physical triggers) is best-effort, flagged `needs_review` where applicable; `_consistency_pass()` only logs contradictions.
- **NFPA 704 / HMIS III** are an industry heuristic from GHS, not official; overridable on the form.
- **Transport** is rule-based (UN3139 / UN1760, PG from skin-corrosion sub-category); IMDG/IATA always "Not regulated".
- **Classifier** needs CAS in DB with `ghs_triggers`; unknown CAS → manual hazard modal. Acute toxicity uses cut-offs, not full ATE additivity.
- ~14 dye/fragrance RMs intentionally have no CAS; ~4 chemicals not yet enriched (re-run `batch_enrich.py`).
