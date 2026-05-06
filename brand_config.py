"""
Brand configuration for SDS PDF output.
Loaded from / saved to config/brand_config.json.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path

_BASE = Path(__file__).parent
_CFG_PATH = _BASE / "config" / "brand_config.json"


@dataclass
class BrandConfig:
    company_name: str = "Capacity Chemical"
    logo_path: str = ""
    primary: str = "#0078C8"
    secondary: str = "#005FA3"
    accent: str = "#F47920"
    light_bg: str = "#EBF5FC"
    website: str = ""
    email: str = ""
    phone: str = ""


def load_brand() -> BrandConfig:
    """Load BrandConfig from disk, returning defaults if file absent or corrupt."""
    if _CFG_PATH.exists():
        try:
            with open(_CFG_PATH, encoding="utf-8") as f:
                data = json.load(f)
            return BrandConfig(**{k: v for k, v in data.items()
                                  if k in BrandConfig.__dataclass_fields__})
        except Exception:
            pass
    return BrandConfig()


def save_brand(cfg: BrandConfig) -> None:
    _CFG_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(_CFG_PATH, "w", encoding="utf-8") as f:
        json.dump(asdict(cfg), f, indent=2)
