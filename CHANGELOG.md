# Changelog

## v1.0 — AI-assisted SDS overhaul

A single large pass that took the generator from producing incomplete,
non-compliant 6-page sheets to complete, professional 16-section SDSs, and
rebuilt the chemical library from the company's authoritative data.

### Compliance & content (fixed blank / wrong sections)

- Added an **AI enrichment layer**: when a chemical's reference data is
  missing, Claude fills OELs, toxicology, aquatic data, persistence/
  bioaccumulation/mobility, IARC/NTP and regulatory fields; results are
  written back to the database and cached (one API call per chemical, ever).
- **Restored Sections 8 / 11 / 12 / 15** which were previously blank.
- **Fixed the California Proposition 65 omission** (e.g. cobalt sulfate
  carcinogen warning now correctly appears in Section 15).
- Added narrative generation for **Sections 6 / 7 / 8 / 10 / 13** with
  guaranteed fallback text so they are never empty.
- **Section 9** physical properties are now AI-estimated from the formula
  and clearly marked `(estimated)`; non-inferable values say
  "Not determined".
- Removed hard-coded prompt text that made every product read as an
  "oxidizing acid"; added a consistency cross-check that logs
  prose/classification contradictions.

### Hazard classification

- Carcinogenicity, mutagenicity, reproductive toxicity, respiratory/skin
  sensitization, STOT-RE and aspiration now flow into **Section 2 and the
  GHS08 health-hazard pictogram** via AI-derived `ghs_triggers`.
- Corrected a systemic error where every health hazard used a ~0.1% cut-off;
  thresholds now use the authoritative GHS/CLP generic concentration limits
  (e.g. reproductive toxicity 0.3%, STOT-RE 10%).
- Added supplied-grade → pure-substance conversion (`active_fraction`):
  enter the as-supplied % and the classifier converts before applying GHS
  cut-offs. Applied only to AI-stub records; the original curated records
  are unchanged (zero regression).
- Enrichment provenance is stamped (`date`, `model`, schema version);
  re-verification is driven by staleness/model/schema, not blind re-asking.

### Chemical library

- Rebuilt `rm_index` from the authoritative item master + RM→CAS export:
  **242 RMs, 225 with CAS**, RM normalized, supplier strength parsed into
  `active_fraction`.
- Backfilled missing CAS via PubChem (flagged for review); the reviewer's
  edits were synced back across all sections.
- Created database stubs for new chemicals so they are "In DB" and enrich on
  first use; **batch pre-enriched the whole library (171/175)**.

### Usability

- Single **searchable material field** (type RM#/CAS/name; was three manual
  boxes).
- **"+ New material to library"** — web button + CLI; optional manual **RM#**
  (blank = auto, duplicates rejected); hot-reloads so the new material is
  usable immediately without a restart.
- **Fuzzy / proprietary formula** option — aggregates known non-hazardous
  components and bands concentrations in Section 3 only (classification
  unaffected).
- **Company & 24h emergency-contact profiles** (with logo upload), selectable
  per SDS.
- **Re-issue**: re-render an existing SDS under a different company with no
  AI / no API cost (Section 1 + logo only).

### Presentation

- Replaced the drawn pictograms with the **official UN GHS artwork**.
- **NFPA 704 colour fire-diamond + HMIS III colour bar** auto-derived from
  the GHS classification (industry heuristic; overridable), replacing the
  plain "0-0-0" text.
- Layout: sections flow to fill pages (eliminated large blank gaps), long
  tables repeat their header row across pages, section headers no longer
  orphan at the bottom of a page.

### Documentation

- Refreshed `CLAUDE.md` (architecture), added this `CHANGELOG.md`, a
  `USAGE.md` user guide, and an in-app help / important-notes panel.

### Known limitations

AI-estimated content and the NFPA/HMIS heuristic must be reviewed before a
regulated SDS is issued. Transport is rule-based (DOT only). ~14 dye/
fragrance RMs have no single CAS. The app currently has no authentication
and is local-only.
