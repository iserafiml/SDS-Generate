"""
Flask web interface for the SDS Generator.

Run with:  python3 sds_app.py
Then open: http://localhost:5000
"""

from __future__ import annotations

import json
import os
import threading
import time
import uuid
from pathlib import Path

from flask import Flask, Response, jsonify, render_template, request, send_from_directory

from brand_config import load_brand
from ghs_classifier import HAZARD_MENU, build_manual_category
from sds_data_model import (
    ManufacturerInfo,
    SDSIngredient,
    SDSPhysicalProperties,
    SDSProduct,
)
from sds_generator import SDSGenerator
from sds_input import _merge_manual_categories
from sds_pdf_builder import build_sds_pdf

# ---------------------------------------------------------------------------
# App + shared resources
# ---------------------------------------------------------------------------

app = Flask(__name__)

BASE = Path(__file__).parent
OUTPUT_DIR = BASE / "output"
OUTPUT_DIR.mkdir(exist_ok=True)

gen = SDSGenerator(BASE / "data/raw_material_db.json", BASE / "config/api_config.json")
brand = load_brand()
with open(BASE / "data/raw_material_db.json", encoding="utf-8") as _f:
    _db: dict[str, dict] = {r["cas"]: r for r in json.load(_f)}

_RM_INDEX_PATH = BASE / "data/rm_index.json"
_rm_index: dict[str, dict] = {}
if _RM_INDEX_PATH.exists():
    with open(_RM_INDEX_PATH, encoding="utf-8") as _f:
        _rm_index = json.load(_f)

# Unified searchable pool: every RM# entry plus any DB chemical without an RM.
_search_pool: list[dict] = []


def _rebuild_search_pool() -> None:
    global _search_pool
    pool, seen = [], set()
    for rm, rec in _rm_index.items():
        cas = rec.get("cas", "")
        pool.append({
            "rm": rm, "cas": cas, "name": rec.get("name", ""),
            "in_db": cas in _db,
            "active_fraction": rec.get("active_fraction", 1.0),
        })
        seen.add(cas)
    for cas, rec in _db.items():
        if cas not in seen:
            pool.append({
                "rm": "", "cas": cas, "name": rec.get("name", ""),
                "in_db": True, "active_fraction": 1.0,
            })
    _search_pool = pool


def _reload_library() -> None:
    """Re-read rm_index + DB and refresh in-memory state after an add,
    so a new material is usable without restarting the server."""
    global _rm_index
    with open(BASE / "data/raw_material_db.json", encoding="utf-8") as f:
        fresh = {r["cas"]: r for r in json.load(f)}
    gen._db.clear()
    gen._db.update(fresh)            # classifier shares this dict reference
    globals()["_db"] = gen._db
    with open(_RM_INDEX_PATH, encoding="utf-8") as f:
        _rm_index = json.load(f)
    _rebuild_search_pool()


_rebuild_search_pool()

# ---------------------------------------------------------------------------
# In-memory job store
# ---------------------------------------------------------------------------

_jobs: dict[str, dict] = {}
_jobs_lock = threading.Lock()

_NOT_AVAIL = "Not determined or not available."


def _create_job(job_id: str) -> None:
    with _jobs_lock:
        _jobs[job_id] = {
            "progress": 0,
            "message": "Queued...",
            "done": False,
            "pdf": None,
            "error": None,
        }


def _update_job(job_id: str, pct: int, msg: str) -> None:
    with _jobs_lock:
        if job_id in _jobs:
            _jobs[job_id].update({"progress": pct, "message": msg})


def _finish_job(job_id: str, pdf_filename: str) -> None:
    with _jobs_lock:
        _jobs[job_id].update(
            {"progress": 100, "message": "Complete.", "done": True, "pdf": pdf_filename}
        )


def _fail_job(job_id: str, error_msg: str) -> None:
    with _jobs_lock:
        _jobs[job_id].update({"done": True, "error": error_msg})


# ---------------------------------------------------------------------------
# Form data → SDSProduct
# ---------------------------------------------------------------------------

def _parse_product(data: dict) -> SDSProduct:
    m = data.get("manufacturer", {})
    phys = data.get("physical", {})

    ingredients = [
        SDSIngredient(
            name=row.get("name", ""),
            cas_number=row.get("cas_number", ""),
            wt_percent_low=float(row.get("wt_percent_low") or 0),
            wt_percent_high=float(row.get("wt_percent_high") or 0),
            function=row.get("function", ""),
            active_fraction=float(row.get("active_fraction") or 1.0),
        )
        for row in data.get("ingredients", [])
    ]

    return SDSProduct(
        product_name=data.get("product_name", ""),
        product_code=data.get("product_code", ""),
        product_type=data.get("product_type", ""),
        manufacturer=ManufacturerInfo(
            company_name=m.get("company_name", ""),
            phone=m.get("phone", ""),
            emergency_phone=m.get("emergency_phone", ""),
            emergency_provider=m.get("emergency_provider", ""),
            website=m.get("website", ""),
        ),
        ingredients=ingredients,
        fuzzy_formula=bool(data.get("fuzzy_formula")),
        physical_properties=SDSPhysicalProperties(
            appearance=phys.get("appearance") or _NOT_AVAIL,
            odour=phys.get("odour") or _NOT_AVAIL,
            pH=phys.get("pH") or _NOT_AVAIL,
            density=phys.get("density") or _NOT_AVAIL,
        ),
        reactivity="Not reactive under recommended handling and storage conditions.",
        chemical_stability="Stable under recommended handling and storage conditions.",
        hazardous_reactions="Hazardous reactions are not anticipated under recommended conditions.",
        conditions_to_avoid="Avoid extreme heat, open flames, sparks and incompatible materials.",
        incompatible_materials="None known.",
        hazardous_decomposition=(
            "Under normal conditions, hazardous decomposition products should not be produced."
        ),
        disposal_methods="Dispose of in accordance with national and local regulations.",
        disposal_container="Not determined or not applicable.",
        tsca_inventory="All ingredients are listed-active or exempt.",
        tsca_snur="None of the ingredients are listed.",
        tsca_export="None of the ingredients are listed.",
    )


def _parse_manual_categories(data: dict) -> list:
    result = []
    for row in data.get("ingredients", []):
        for h in row.get("manual_hazards", []):
            result.append(build_manual_category(h["key"], h["category"]))
    return result


# ---------------------------------------------------------------------------
# Background worker
# ---------------------------------------------------------------------------

def _run_generation(job_id: str, data: dict) -> None:
    try:
        product = _parse_product(data)
        manual_cats = _parse_manual_categories(data)

        sds_doc = gen.generate(
            product,
            progress_cb=lambda pct, msg: _update_job(job_id, pct, msg),
        )

        if manual_cats:
            _merge_manual_categories(sds_doc.product.classification, manual_cats)

        safe_name = "".join(
            c if c.isalnum() or c in ("-", "_") else "_"
            for c in product.product_name
        )
        filename = f"{safe_name}_{job_id[:8]}.pdf"
        build_sds_pdf(sds_doc, OUTPUT_DIR / filename, brand)
        _finish_job(job_id, filename)

    except Exception as exc:
        _fail_job(job_id, str(exc))


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@app.route("/")
def index():
    return render_template(
        "index.html",
        brand=brand,
        hazard_menu=HAZARD_MENU,
        hazard_menu_json=json.dumps(HAZARD_MENU),
    )


@app.route("/lookup_cas")
def lookup_cas():
    cas = request.args.get("cas", "").strip()
    rec = _db.get(cas)
    if rec:
        return jsonify({"found": True, "name": rec.get("name", "")})
    return jsonify({"found": False})


@app.route("/lookup_rm")
def lookup_rm():
    rm = request.args.get("rm", "").strip().upper()
    rec = _rm_index.get(rm)
    if rec:
        cas = rec.get("cas", "")
        name = rec.get("name", "")
        in_db = cas in _db
        return jsonify({"found": True, "cas": cas, "name": name, "in_db": in_db})
    return jsonify({"found": False})


@app.route("/api/search_materials")
def search_materials():
    """Autocomplete: match RM#, CAS or name by substring. Returns ≤20 hits."""
    q = request.args.get("q", "").strip().lower()
    if len(q) < 2:
        return jsonify([])
    starts, contains = [], []
    for item in _search_pool:
        rm = item["rm"].lower()
        cas = item["cas"].lower()
        name = item["name"].lower()
        if rm.startswith(q) or cas.startswith(q) or name.startswith(q):
            starts.append(item)
        elif q in rm or q in cas or q in name:
            contains.append(item)
        if len(starts) >= 20:
            break
    return jsonify((starts + contains)[:20])


@app.route("/api/add_material", methods=["POST"])
def add_material_route():
    data = request.get_json(force=True) or {}
    try:
        from material_admin import add_material
        result = add_material(
            name=(data.get("name") or "").strip(),
            cas=(data.get("cas") or "").strip(),
            strength_pct=data.get("strength"),
            synonyms=(data.get("synonyms") or "").strip(),
        )
        _reload_library()              # usable immediately, no restart
        return jsonify({"ok": True, **result})
    except ValueError as e:
        return jsonify({"ok": False, "error": str(e)}), 400
    except Exception as e:            # noqa: BLE001
        return jsonify({"ok": False, "error": f"Unexpected error: {e}"}), 500


@app.route("/generate", methods=["POST"])
def generate_route():
    data = request.get_json(force=True)
    if not data:
        return jsonify({"error": "Invalid JSON"}), 400
    job_id = str(uuid.uuid4())
    _create_job(job_id)
    threading.Thread(target=_run_generation, args=(job_id, data), daemon=True).start()
    return jsonify({"job_id": job_id})


@app.route("/progress/<job_id>")
def progress_stream(job_id: str):
    def stream():
        while True:
            with _jobs_lock:
                job = dict(
                    _jobs.get(job_id, {"done": True, "error": "Job not found",
                                       "progress": 0, "message": "", "pdf": None})
                )
            yield f"data: {json.dumps(job)}\n\n"
            if job["done"]:
                return
            time.sleep(0.4)

    return Response(
        stream(),
        mimetype="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.route("/download/<filename>")
def download(filename: str):
    return send_from_directory(OUTPUT_DIR, filename, as_attachment=True)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import signal
    import subprocess

    PORT = 5001

    # Release port if already in use
    result = subprocess.run(
        ["lsof", "-ti", f":{PORT}"],
        capture_output=True, text=True
    )
    pids = result.stdout.strip().split()
    for pid in pids:
        try:
            os.kill(int(pid), signal.SIGKILL)
        except (ProcessLookupError, ValueError):
            pass
    if pids:
        time.sleep(0.5)

    print("Starting SDS Generator web interface...")
    print(f"Open http://localhost:{PORT} in your browser")
    app.run(debug=False, port=PORT, threaded=True)
