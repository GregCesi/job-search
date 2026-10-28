"""Liste les clones du rapport jscpd avec leur chemin depuis la racine (EXE-203).

jscpd 5.4.2 rend chaque fichier relatif au dossier passé en argument (api,
orchestrator ou web/app). Un nom est rattaché au seul de ces dossiers où il existe ;
s'il en existe plusieurs, la ligne le dit.

Usage, depuis la racine du dépôt : python docs/recon/outils/clones_chemins.py
"""

import json
import os

RAPPORT = "docs/recon/sorties/jscpd/jscpd-report.json"
DOSSIERS = ("api", "orchestrator", "web/app")


def chemin(nom: str) -> str:
    trouves = [f"{d}/{nom}" for d in DOSSIERS if os.path.exists(f"{d}/{nom}")]
    return trouves[0] if len(trouves) == 1 else "AMBIGU:" + ",".join(trouves)


def main():
    with open(RAPPORT, encoding="utf-8") as fichier:
        rapport = json.load(fichier)
    for clone in rapport["duplicates"]:
        a, b = clone["firstFile"], clone["secondFile"]
        print(
            f"{chemin(a['name'])}:{a['start']}-{a['end']} | "
            f"{chemin(b['name'])}:{b['start']}-{b['end']} | "
            f"{clone['lines']} lignes | {clone['format']}"
        )


if __name__ == "__main__":
    main()
