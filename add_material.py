"""
CLI to add a raw material to the library.

Non-interactive:
  python3 add_material.py --name "Citric Acid" --cas 77-92-9 --strength 100
  python3 add_material.py --name "Sodium Gluconate"          # CAS via PubChem

Interactive (no args):
  python3 add_material.py
"""

from __future__ import annotations

import argparse

from material_admin import add_material


def main() -> None:
    ap = argparse.ArgumentParser(description="Add a raw material to the library.")
    ap.add_argument("--name")
    ap.add_argument("--cas", default="")
    ap.add_argument("--strength", type=float, default=None,
                    help="Supplied strength %% (e.g. 50 for a 50%% solution).")
    ap.add_argument("--rm", default=None, help="RM number (auto if omitted).")
    ap.add_argument("--synonyms", default="")
    a = ap.parse_args()

    name = a.name or input("Material name: ").strip()
    cas = a.cas or input("CAS (blank = look up via PubChem): ").strip()
    if a.strength is None and not a.name:
        s = input("Supplied strength % (blank = parse from name / 100): ").strip()
        a.strength = float(s) if s else None

    try:
        r = add_material(name, cas, a.strength, a.rm, a.synonyms)
    except ValueError as e:
        print(f"Error: {e}")
        raise SystemExit(1)

    print(f"\nAdded {r['rm']}: {r['name']}")
    print(f"  CAS: {r['cas'] or '(unresolved)'}  [{r['cas_source']}]")
    print(f"  active_fraction: {r['active_fraction']} "
          f"(strength {r['strength_pct']}%, {r['strength_source']})")
    print(f"  DB stub added: {r['stub_added']}")
    if r["needs_review"]:
        print("  ** needs_review: confirm the CAS before production use **")


if __name__ == "__main__":
    main()
