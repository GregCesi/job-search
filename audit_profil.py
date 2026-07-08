"""One-shot: audit couverture profil vs techs extraites du corpus.

Consomme profiles/alias.yaml via le module scoring (source unique).
"""

import csv
import json
import sqlite3
from pathlib import Path

import yaml

from orchestrator.job_search.scoring.aliases import (
    canonicalize,
    load_alias_table,
)

ROOT = Path(__file__).parent
DB = ROOT / "data" / "job_search.sqlite"
PROFILE = ROOT / "profiles" / "gregoire.yaml"
ALIAS_FILE = ROOT / "profiles" / "alias.yaml"
OUT_MD = ROOT / "audit-profil.md"
OUT_CSV = ROOT / "audit-profil.csv"


def load_profile_skills() -> set[str]:
    with open(PROFILE) as f:
        data = yaml.safe_load(f)
    skills = set(data.get("skills", {}).keys())
    print(f"Profile loaded: {PROFILE.resolve()}")
    print(f"  {len(skills)} skills: {sorted(skills)}")
    return skills


def edit_distance(a: str, b: str) -> int:
    """Levenshtein distance."""
    if len(a) < len(b):
        return edit_distance(b, a)
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a):
        curr = [i + 1]
        for j, cb in enumerate(b):
            curr.append(min(prev[j + 1] + 1, curr[j] + 1,
                            prev[j] + (0 if ca == cb else 1)))
        prev = curr
    return prev[-1]


def classify(tech: str, profile_skills: set[str]) -> str:
    if tech in profile_skills:
        return "couverte"
    # Edit distance ≤ 2 — only for names long enough to avoid false positives
    if len(tech) >= 4:
        for sk in profile_skills:
            if len(sk) >= 4 and edit_distance(tech, sk) <= 2:
                return "alias_suspect"
    return "absente"


def main():
    profile_skills = load_profile_skills()
    alias_table = load_alias_table(ALIAS_FILE)
    print(f"Alias table loaded: {ALIAS_FILE.resolve()}")

    conn = sqlite3.connect(DB)
    rows = conn.execute(
        "SELECT extracted_facts_json, category FROM offers "
        "WHERE extracted_facts_json IS NOT NULL"
    ).fetchall()
    conn.close()

    # Aggregate: canonical tech -> stats
    # Uses the same canonicalize() as scoring — single source of truth
    stats: dict[str, dict] = {}
    for facts_json, category in rows:
        try:
            facts = json.loads(facts_json)
        except json.JSONDecodeError:
            continue
        techs = facts.get("techs_required", [])
        domain = facts.get("domain") or category or "?"
        seen_in_offer: set[str] = set()
        for t in techs:
            raw = t["name"].lower().strip()
            name = canonicalize(raw, alias_table)
            if name is None:  # excluded term
                continue
            imp = t.get("importance", "nice_to_have")
            if name not in stats:
                stats[name] = {
                    "nb_offers": 0, "nb_core": 0,
                    "nb_required": 0, "nb_nice_to_have": 0,
                    "domains": set(), "raw_variants": set(),
                }
            stats[name]["raw_variants"].add(raw)
            if name not in seen_in_offer:
                stats[name]["nb_offers"] += 1
                seen_in_offer.add(name)
            key = f"nb_{imp}" if f"nb_{imp}" in stats[name] else "nb_nice_to_have"
            stats[name][key] += 1
            stats[name]["domains"].add(domain)

    # Classify & score
    results = []
    for tech, s in stats.items():
        impact = (s["nb_core"] * 3 + s["nb_required"] * 2
                  + s["nb_nice_to_have"] * 1)
        status = classify(tech, profile_skills)
        variants = s["raw_variants"] - {tech}
        results.append({
            "tech": tech,
            "variants": " ".join(sorted(variants)) if variants else "",
            "nb_offers": s["nb_offers"],
            "nb_core": s["nb_core"],
            "nb_required": s["nb_required"],
            "nb_nice_to_have": s["nb_nice_to_have"],
            "impact": impact,
            "status": status,
            "domains": ", ".join(sorted(s["domains"])),
        })

    # Sort: absentes first, then alias_suspect, then couverte; within group by impact desc
    status_order = {"absente": 0, "alias_suspect": 1, "couverte": 2}
    results.sort(key=lambda r: (status_order[r["status"]], -r["impact"]))

    # Write MD
    with open(OUT_MD, "w") as f:
        f.write("# Audit couverture profil — techs corpus vs gregoire.yaml\n\n")
        f.write(f"Corpus : {len(rows)} offres avec faits extraits. "
                f"Profil : {len(profile_skills)} skills déclarées.\n\n")

        f.write("| Tech | Variants | Offres | Core | Req | Nice | Impact | Statut | Domaines |\n")
        f.write("|------|----------|--------|------|-----|------|--------|--------|----------|\n")
        for r in results:
            f.write(f"| {r['tech']} | {r['variants']} | {r['nb_offers']} | "
                    f"{r['nb_core']} | {r['nb_required']} | {r['nb_nice_to_have']} | "
                    f"{r['impact']} | {r['status']} | {r['domains']} |\n")

    # Write CSV
    with open(OUT_CSV, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=[
            "tech", "variants", "nb_offers", "nb_core", "nb_required",
            "nb_nice_to_have", "impact", "status", "domains",
        ])
        w.writeheader()
        w.writerows(results)

    # Summary
    absent = [r for r in results if r["status"] == "absente"]
    alias = [r for r in results if r["status"] == "alias_suspect"]
    covered = [r for r in results if r["status"] == "couverte"]
    print(f"\nTechs uniques dans le corpus : {len(results)}")
    print(f"  couverte       : {len(covered)}")
    print(f"  alias_suspect  : {len(alias)}")
    print(f"  absente        : {len(absent)}")
    print(f"\nTop 20 absentes par impact :")
    for r in absent[:20]:
        v = f"  (← {r['variants']})" if r["variants"] else ""
        print(f"  {r['tech']:20s}  offres={r['nb_offers']:3d}  "
              f"impact={r['impact']:4d}  domaines={r['domains']}{v}")
    print(f"\nAlias suspects :")
    for r in alias:
        print(f"  {r['tech']:20s}  offres={r['nb_offers']:3d}  "
              f"impact={r['impact']:4d}")
    print(f"\n→ {OUT_MD}")
    print(f"→ {OUT_CSV}")


if __name__ == "__main__":
    main()
