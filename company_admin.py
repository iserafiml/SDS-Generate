"""
Company + 24-hour emergency-contact profiles.

Stores reusable issuer profiles so an SDS can be generated — or later
re-issued — under any saved company without re-running the AI pipeline.

  config/companies.json          list of company profiles (+ brand/logo)
  config/emergency_contacts.json list of 24h emergency providers
  config/logos/                  uploaded logo image files

A company profile supplies BOTH the Section-1 manufacturer block and the
PDF brand (logo + colours). build_profile() returns (BrandConfig,
ManufacturerInfo) ready for the PDF builder.
"""

from __future__ import annotations

import json
import os
import tempfile
import uuid
from pathlib import Path

from brand_config import BrandConfig
from sds_data_model import ManufacturerInfo

BASE = Path(__file__).parent
CONF = BASE / "config"
COMPANIES = CONF / "companies.json"
EMERGENCY = CONF / "emergency_contacts.json"
LOGO_DIR = CONF / "logos"

_DEFAULT_EMERGENCY = [
    {"id": "chemtrec", "provider": "CHEMTREC",
     "phone": "1-800-424-9300 (24 hours)", "account": ""},
    {"id": "second", "provider": "(second provider — edit me)",
     "phone": "", "account": ""},
]


def _read(path: Path, default: list) -> list:
    if path.exists():
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            pass
    return list(default)


def _write(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=".tmp_", suffix=".json")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        os.replace(tmp, path)
    except Exception:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise


# ---- companies ---------------------------------------------------------

def list_companies() -> list[dict]:
    return _read(COMPANIES, [])


def list_emergency() -> list[dict]:
    return _read(EMERGENCY, _DEFAULT_EMERGENCY)


def get_company(cid: str) -> dict | None:
    return next((c for c in list_companies() if c.get("id") == cid), None)


def get_emergency(eid: str) -> dict | None:
    return next((e for e in list_emergency() if e.get("id") == eid), None)


_COMPANY_FIELDS = ("name", "address_line1", "city_state_zip", "country",
                   "phone", "email", "website", "logo_path",
                   "primary", "secondary", "accent", "light_bg")


def save_company(data: dict) -> dict:
    """Create (no id) or update (existing id) a company profile."""
    if not (data.get("name") or "").strip():
        raise ValueError("Company name is required.")
    companies = list_companies()
    cid = (data.get("id") or "").strip()
    rec = {k: (data.get(k) or "").strip() for k in _COMPANY_FIELDS}
    # sensible brand-colour defaults
    for k, dv in (("primary", "#0078C8"), ("secondary", "#005FA3"),
                  ("accent", "#F47920"), ("light_bg", "#EBF5FC")):
        rec[k] = rec[k] or dv
    if cid:
        for c in companies:
            if c.get("id") == cid:
                c.update(rec)
                _write(COMPANIES, companies)
                return c
        raise ValueError(f"Company id '{cid}' not found.")
    rec["id"] = uuid.uuid4().hex[:8]
    companies.append(rec)
    _write(COMPANIES, companies)
    return rec


def delete_company(cid: str) -> bool:
    companies = list_companies()
    new = [c for c in companies if c.get("id") != cid]
    if len(new) == len(companies):
        return False
    _write(COMPANIES, new)
    return True


def save_emergency(data: dict) -> dict:
    if not (data.get("provider") or "").strip():
        raise ValueError("Provider name is required.")
    items = list_emergency()
    eid = (data.get("id") or "").strip()
    rec = {"provider": data.get("provider", "").strip(),
           "phone": data.get("phone", "").strip(),
           "account": data.get("account", "").strip()}
    if eid:
        for e in items:
            if e.get("id") == eid:
                e.update(rec)
                _write(EMERGENCY, items)
                return e
    rec["id"] = eid or uuid.uuid4().hex[:8]
    items.append(rec)
    _write(EMERGENCY, items)
    return rec


def save_logo(filename: str, raw: bytes) -> str:
    """Persist an uploaded logo, return its stored path (relative to repo)."""
    LOGO_DIR.mkdir(parents=True, exist_ok=True)
    ext = os.path.splitext(filename)[1].lower() or ".png"
    if ext not in (".png", ".jpg", ".jpeg", ".gif"):
        raise ValueError("Logo must be PNG/JPG/GIF.")
    name = f"{uuid.uuid4().hex[:10]}{ext}"
    (LOGO_DIR / name).write_bytes(raw)
    return f"config/logos/{name}"


def build_profile(company_id: str,
                   emergency_id: str = "") -> tuple[BrandConfig, ManufacturerInfo]:
    """Resolve a company (+optional emergency provider) into the
    (BrandConfig, ManufacturerInfo) the PDF builder consumes."""
    c = get_company(company_id)
    if not c:
        raise ValueError(f"Company '{company_id}' not found.")
    e = get_emergency(emergency_id) if emergency_id else None
    brand = BrandConfig(
        company_name=c.get("name", ""),
        logo_path=c.get("logo_path", ""),
        primary=c.get("primary") or "#0078C8",
        secondary=c.get("secondary") or "#005FA3",
        accent=c.get("accent") or "#F47920",
        light_bg=c.get("light_bg") or "#EBF5FC",
        website=c.get("website", ""),
        email=c.get("email", ""),
        phone=c.get("phone", ""),
    )
    mfr = ManufacturerInfo(
        company_name=c.get("name", ""),
        address_line1=c.get("address_line1", ""),
        city_state_zip=c.get("city_state_zip", ""),
        country=c.get("country", ""),
        phone=c.get("phone", ""),
        website=c.get("website", ""),
        email=c.get("email", ""),
        emergency_phone=(e or {}).get("phone", ""),
        emergency_provider=(e or {}).get("provider", ""),
        emergency_account=(e or {}).get("account", ""),
    )
    return brand, mfr


if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1 and sys.argv[1] == "add":
        print(save_company({
            "name": input("Company name: "),
            "address_line1": input("Address: "),
            "city_state_zip": input("City, State ZIP: "),
            "country": input("Country: "),
            "phone": input("Phone: "),
            "email": input("Email: "),
            "website": input("Website: "),
        }))
    else:
        print("companies:", json.dumps(list_companies(), indent=2))
        print("emergency:", json.dumps(list_emergency(), indent=2))
