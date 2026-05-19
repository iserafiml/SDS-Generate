"""
Batch pre-enrichment of the whole chemical library.

Calls Claude (via the key in config/api_config.json) for every record that
needs_enrichment(): empty stubs, curated records not yet enriched, and any
record predating the current ENRICHMENT_SCHEMA_VERSION. Results are written
back to data/raw_material_db.json every 10 records, so the run is
crash-safe and fully resumable — re-running skips records already stamped
with the current _enrichment metadata.

Per-chemical failures are caught inside enrich_chemical and do not abort
the batch (that chemical is simply retried on the next run).

Run:  python3 batch_enrich.py
"""

from __future__ import annotations

import json
import time
from pathlib import Path

import anthropic

from db_enrichment import enrich_chemical, needs_enrichment, persist_db

BASE = Path(__file__).parent
DB = BASE / "data" / "raw_material_db.json"

cfg = json.loads((BASE / "config/api_config.json").read_text())
client = anthropic.Anthropic(api_key=cfg["api_key"])

records = json.loads(DB.read_text(encoding="utf-8"))
idx = {r["cas"]: r for r in records}

todo = [r for r in records if needs_enrichment(r)]
total = len(todo)
print(f"DB {len(records)} records | need enrichment: {total}", flush=True)

done = failed = pending_writes = 0
for i, rec in enumerate(todo, 1):
    before = rec.get("_enrichment")
    try:
        _, changed = enrich_chemical(client, rec)
    except Exception as e:  # noqa: BLE001 — never abort the batch
        failed += 1
        print(f"[{i}/{total}] FAIL {rec['cas']} {rec['name'][:40]}: {e}", flush=True)
        continue
    if rec.get("_enrichment") != before or changed:
        done += 1
        pending_writes += 1
        ntrig = len(rec.get("ghs_triggers", {}))
        print(f"[{i}/{total}] {rec['cas']:13s} {rec['name'][:38]:38s} "
              f"triggers={ntrig}", flush=True)
    else:
        print(f"[{i}/{total}] {rec['cas']} skipped (already current)", flush=True)
    if pending_writes >= 10:
        persist_db(idx, DB)
        pending_writes = 0
        print("  …progress saved", flush=True)
    time.sleep(0.4)

persist_db(idx, DB)
print(f"\nDONE. enriched/updated={done} failed={failed} "
      f"(re-run to retry any failures).", flush=True)
