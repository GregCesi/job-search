"""Vérifie la cohérence entre le filtre SQL (view_profile) et le filtre Python (filters.py)
sur les zones belgique_area et strasbourg_area, pour toutes les offres filtered_out=0.

Usage :
    python scripts/check_zone_invariant.py
"""
from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from orchestrator.job_search.matching.profile import load_profile
from orchestrator.job_search.paths import DB_PATH, PROFILE_PATH

TARGET_ZONES = ["belgique_area", "strasbourg_area"]


def main() -> None:
    profile, _ = load_profile(PROFILE_PATH)

    # SQL conditions — même logique que api/view_profile.py (sans le cache)
    sql_conds: list[str] = []
    sql_params: list[str] = []
    for name in TARGET_ZONES:
        zone = profile.zones[name]
        for dept in zone.dept:
            sql_conds.append("UPPER(o.location) LIKE ?")
            sql_params.append(f"{dept.upper()}%")
        for kw in zone.keywords:
            sql_conds.append("UPPER(o.location) LIKE ?")
            sql_params.append(f"%{kw.upper()}%")

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row

    all_rows = conn.execute(
        "SELECT id, location, remote FROM offers WHERE filtered_out = 0"
    ).fetchall()
    total = len(all_rows)

    # Ensemble SQL
    if sql_conds:
        where = " OR ".join(sql_conds)
        sql_ids: set[int] = {
            r["id"]
            for r in conn.execute(
                f"SELECT id FROM offers o WHERE o.filtered_out = 0 AND ({where})",
                sql_params,
            ).fetchall()
        }
    else:
        sql_ids = set()

    conn.close()

    # Ensemble Python — même logique que filters.py l. 73-86
    zones = {name: profile.zones[name] for name in TARGET_ZONES}
    python_ids: set[int] = set()
    for row in all_rows:
        loc = (row["location"] or "").upper()
        matched = False
        for zone in zones.values():
            if any(loc.startswith(d) for d in zone.dept):
                matched = True
                break
            if any(kw.upper() in loc for kw in zone.keywords):
                matched = True
                break
        if matched:
            python_ids.add(row["id"])

    sql_only = sql_ids - python_ids
    python_only = python_ids - sql_ids

    # Cas liège non-ASCII : location contient "liège" (Python insensible à la casse),
    # non matché SQL mais matché Python
    liege_python_matched: set[int] = set()
    for row in all_rows:
        loc_lower = (row["location"] or "").lower()
        if "liège" in loc_lower and row["id"] in python_ids and row["id"] not in sql_ids:
            liege_python_matched.add(row["id"])

    # Rapport
    print(f"Offres filtered_out=0 testées : {total}")
    print(f"SQL oui / Python non         : {len(sql_only)}")
    print(f"SQL non / Python oui         : {len(python_only)}")
    print(f"Cas liège non-ASCII          : {len(liege_python_matched)}")

    if sql_only:
        print("\nExemples SQL oui / Python non :")
        rows_map = {r["id"]: r for r in all_rows}
        for eid in list(sql_only)[:5]:
            r = rows_map[eid]
            print(f"  id={eid} location={r['location']!r} SQL=oui Python=non")

    if python_only:
        print("\nExemples SQL non / Python oui :")
        rows_map = {r["id"]: r for r in all_rows}
        for eid in list(python_only)[:5]:
            r = rows_map[eid]
            print(f"  id={eid} location={r['location']!r} SQL=non Python=oui")

    if sql_only or python_only:
        print("\nÉCARTS DÉTECTÉS — à consigner au handoff.")
        sys.exit(1)
    else:
        print("\n0 écart dans les deux sens. Invariant respecté.")


if __name__ == "__main__":
    main()
