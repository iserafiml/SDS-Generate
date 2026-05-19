# SDS Generator — User Guide

> This tool uses AI to assist in producing a 16-section SDS in the OSHA HCS
> 2012 format. **It produces a high-quality draft. A qualified person must
> review it before it is issued or distributed.**

## 1. Start

```bash
pip3 install -r requirements.txt          # first time only
python3 sds_app.py                        # open http://localhost:5001
```

`config/api_config.json` must contain a valid Anthropic key
(`{"api_key":"sk-ant-..."}`). Generated PDFs are written to `output/`.
Currently accessible from this machine only (LAN sharing is opt-in).

## 2. Generate an SDS (web)

1. **Company** — in the Section 2 area pick an "Issuing company" and a
   "24h Emergency contact". Use **Manage** to add one (logo upload supported).
2. **Product** — name, product code, etc.
3. **Materials** — one search box per row: type any part of the
   **RM# / CAS / name** (≥2 chars), click a result to auto-fill and get an
   "In DB" badge. If the material is not in the library, either type the CAS
   manually and click **+ Hazards** to pick GHS classes, or use
   **+ New material to library** to add it permanently. Enter the
   concentration low/high **as the as-supplied grade %** (not the pure
   active %).
4. *(optional)* physical properties, NFPA/HMIS override, fuzzy-formula box.
5. Click Generate → progress bar → download the PDF.

## 3. Re-issue the same SDS under another company (free)

Section 2 area → **Re-issue** → pick a previously generated SDS + a different
company / emergency contact → re-render. **Only Section 1 and the logo
change; no AI runs, no API charge, instant.**

## 4. API cost model (billed to your own Anthropic key)

| Action | Uses API? |
|---|---|
| Generating a **brand-new** SDS (first aid / firefighting / handling / Section 9 estimate, etc.) | Yes — a few calls |
| **First-time** enrichment of a chemical (toxicology / OEL / regulatory / hazards) | Yes — once; **cached forever** afterwards |
| Re-using an enriched chemical, GHS classification, NFPA/HMIS, pictograms, fuzzy formula | No |
| **Re-rendering an existing SDS under a different company** | **No (0)** |
| Material search/lookup, company management, viewing/downloading | No |
| New-material CAS lookup via PubChem | No (free public API, not Anthropic) |

~171/175 chemicals were **batch pre-enriched and cached**, so day-to-day
generation does not re-incur that cost.

## 5. ⚠️ Important notes

- **AI content must be reviewed.** Section 9 properties are **estimated**
  (marked `(estimated)`); enriched toxicology/regulatory/hazard data is
  best-effort. Verify before issuing.
- **NFPA 704 / HMIS III** are an industry heuristic derived from the GHS
  classification, not an official mapping; a note states this and they are
  overridable on the form.
- **Enter the as-supplied grade %.** e.g. for "Sodium Hydroxide 50%" dosed at
  20%, enter 20 — not the 10% pure NaOH. The system converts library grades
  to the pure substance via `active_fraction` before applying GHS cut-offs.
- **GHS cut-offs.** A hazard below its concentration cut-off is correctly not
  classified in Section 2 (e.g. cobalt < 0.1% → no carcinogenicity in
  Section 2, but California Prop 65 is still flagged in Section 15).
- **Fuzzy formula** affects the Section 3 display only; classification and
  Sections 8/11/12/15 always use the true formula and **hazardous
  components are never hidden**.
- **Proprietary blends / dyes / fragrances** (~14 RMs) have no single CAS —
  use the manual hazard selector for those.
- After changing code or the HTML template, **restart** `python3 sds_app.py`
  (no hot reload). Editing data JSON does not require a restart.

## 6. Maintenance scripts (rarely needed)

`batch_enrich.py` — full-library pre-enrichment (safe to re-run to fill
gaps) · `add_material.py` — add a material from the CLI ·
`build_rm_index.py` / `apply_cas_review.py` / `sync_db_stubs.py` /
`resolve_missing_cas.py` / `fix_gcl_thresholds.py` — data rebuild/maintenance
(read from `data/sources/`).
