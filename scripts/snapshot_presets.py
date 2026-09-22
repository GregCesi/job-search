"""Snapshot des ids de référence pour les 4 presets candidat.

Appelle GET /offers pour chacun des 4 presets (params de VIEW_PRESETS, sans view_profile),
enregistre les sets d'ids dans data/snapshot_presets.json.

Usage :
    python scripts/snapshot_presets.py
"""
import json
from pathlib import Path

import requests

API_BASE = "http://localhost:8000"
DATA_DIR = Path(__file__).resolve().parent.parent / "data"

PRESETS: dict[str, dict[str, str]] = {
    "cibles":   {"category": "parfait",     "hors_perimetre": "false", "exclude_ad_language": "nl", "sort": "seen_candidat,fetched_at", "order": "asc,desc"},
    "gaps":     {"category": "reve",        "hors_perimetre": "false", "exclude_ad_language": "nl", "sort": "seen_candidat,fetched_at", "order": "asc,desc"},
    "filet":    {"category": "atteignable", "hors_perimetre": "false", "exclude_ad_language": "nl", "sort": "seen_candidat,fetched_at", "order": "asc,desc"},
    "retenues": {"verdict": "retenu", "hors_perimetre": "false", "exclude_category": "hors", "exclude_ad_language": "nl", "sort": "fetched_at", "order": "desc"},
}


def main() -> None:
    snapshot: dict[str, list[int]] = {}
    for preset_name, params in PRESETS.items():
        resp = requests.get(f"{API_BASE}/offers", params=params, timeout=30)
        resp.raise_for_status()
        ids = [offer["id"] for offer in resp.json()]
        snapshot[preset_name] = ids
        print(f"  {preset_name}: {len(ids)} offres")

    out = DATA_DIR / "snapshot_presets.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(snapshot, indent=2), encoding="utf-8")
    print(f"\nSauvegardé : {out}")
    assert set(snapshot.keys()) == {"cibles", "gaps", "filet", "retenues"}, "4 clés attendues"
    print("OK — 4 clés présentes.")


if __name__ == "__main__":
    main()
