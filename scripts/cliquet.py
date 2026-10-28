"""Cliquet de la barre : la dette mesurée ne peut que baisser.

Critère 7 de scripts/barre.sh. Lit les plafonds de scripts/plafonds.toml et
rend 0 s'ils tiennent tous, 1 sinon. Trois mesures :

- appels .execute( hors des fichiers de stockage, sous api/ et orchestrator/ ;
- taille des fichiers .py, .vue et .ts de api/, orchestrator/ et web/app/ ;
- complexité cyclomatique des blocs Python (radon), sous api/ et orchestrator/.

Un fichier ou un bloc nommé dans les exceptions a son propre plafond ; tout
autre fichier ou bloc est tenu au seuil général. Les plafonds ne se baissent
qu'à la main, après promotion : l'agent n'écrit pas sous scripts/.

Usage : .venv/bin/python scripts/cliquet.py           (vérifie)
        .venv/bin/python scripts/cliquet.py --mesure  (imprime les valeurs du jour)

TCK-301, 28 octobre 2026.
"""

from __future__ import annotations

import re
import sys
import tomllib
from pathlib import Path

from radon.complexity import cc_visit

ROOT = Path(__file__).resolve().parent.parent
PLAFONDS = ROOT / "scripts" / "plafonds.toml"
DOSSIERS_PY = ("api", "orchestrator")
DOSSIERS_TAILLE = ("api", "orchestrator", "web/app")
EXTENSIONS_TAILLE = (".py", ".vue", ".ts")
EXECUTE = re.compile(r"\.execute\(")


def _fichiers(dossiers: tuple[str, ...], extensions: tuple[str, ...]) -> list[Path]:
    trouves: list[Path] = []
    for d in dossiers:
        for p in sorted((ROOT / d).rglob("*")):
            if p.suffix not in extensions or not p.is_file():
                continue
            parts = p.relative_to(ROOT).parts
            if "__pycache__" in parts or "node_modules" in parts or ".nuxt" in parts:
                continue
            trouves.append(p)
    return trouves


def _rel(p: Path) -> str:
    return p.relative_to(ROOT).as_posix()


def est_stockage(rel: str) -> bool:
    """Un fichier de stockage : sous un dossier storage/ ou stockage/, ou nommé
    storage.py ou stockage.py."""
    parts = rel.split("/")
    return (
        "storage" in parts[:-1]
        or "stockage" in parts[:-1]
        or parts[-1] in ("storage.py", "stockage.py")
    )


def mesurer() -> dict:
    execute_hors = 0
    par_fichier: dict[str, int] = {}
    for p in _fichiers(DOSSIERS_PY, (".py",)):
        rel = _rel(p)
        if est_stockage(rel):
            continue
        n = len(EXECUTE.findall(p.read_text(encoding="utf-8")))
        if n:
            par_fichier[rel] = n
            execute_hors += n

    tailles = {
        _rel(p): sum(1 for _ in p.open(encoding="utf-8"))
        for p in _fichiers(DOSSIERS_TAILLE, EXTENSIONS_TAILLE)
    }

    blocs: dict[str, int] = {}
    for p in _fichiers(DOSSIERS_PY, (".py",)):
        try:
            for b in cc_visit(p.read_text(encoding="utf-8")):
                cle = f"{_rel(p)}::{b.fullname}"
                blocs[cle] = max(blocs.get(cle, 0), b.complexity)
        except SyntaxError as e:  # un fichier illisible par radon est une erreur
            raise SystemExit(f"CLIQUET: {_rel(p)} illisible par radon : {e}") from e

    return {
        "execute_hors": execute_hors,
        "execute_par_fichier": par_fichier,
        "tailles": tailles,
        "blocs": blocs,
    }


def verifier(m: dict, pl: dict) -> list[str]:
    ecarts: list[str] = []

    plafond_exec = pl["execute"]["hors_stockage"]
    if m["execute_hors"] > plafond_exec:
        ecarts.append(
            f".execute( hors stockage : {m['execute_hors']} pour un plafond de "
            f"{plafond_exec}"
        )

    seuil_t = pl["taille"]["seuil"]
    exc_t = pl["taille"].get("exceptions", {})
    for f, n in sorted(m["tailles"].items()):
        plafond = exc_t.get(f, seuil_t)
        if n > plafond:
            ecarts.append(f"taille : {f} fait {n} lignes pour un plafond de {plafond}")

    seuil_c = pl["complexite"]["seuil"]
    exc_c = pl["complexite"].get("exceptions", {})
    for b, cc in sorted(m["blocs"].items()):
        plafond = exc_c.get(b, seuil_c)
        if cc > plafond:
            ecarts.append(f"complexité : {b} vaut {cc} pour un plafond de {plafond}")

    return ecarts


def baissables(m: dict, pl: dict) -> list[str]:
    """Plafonds au-dessus de la mesure : à baisser à la main après promotion."""
    sortie: list[str] = []
    if m["execute_hors"] < pl["execute"]["hors_stockage"]:
        sortie.append(
            f"execute.hors_stockage : {pl['execute']['hors_stockage']} -> "
            f"{m['execute_hors']}"
        )
    for f, plafond in sorted(pl["taille"].get("exceptions", {}).items()):
        n = m["tailles"].get(f)
        if n is None or n < plafond:
            sortie.append(
                f"taille.exceptions.{f} : {plafond} -> {n if n else 'retirer'}"
            )
    for b, plafond in sorted(pl["complexite"].get("exceptions", {}).items()):
        cc = m["blocs"].get(b)
        if cc is None or cc < plafond:
            sortie.append(
                f"complexite.exceptions.{b} : {plafond} -> {cc if cc else 'retirer'}"
            )
    return sortie


def main() -> int:
    m = mesurer()
    if "--mesure" in sys.argv:
        print(f"execute hors stockage : {m['execute_hors']}")
        for f, n in sorted(m["execute_par_fichier"].items(), key=lambda x: -x[1]):
            print(f"  {n:4d}  {f}")
        print("tailles au-dessus de 800 lignes :")
        for f, n in sorted(m["tailles"].items(), key=lambda x: -x[1]):
            if n > 800:
                print(f"  {n:5d}  {f}")
        print("blocs au-dessus de 20 :")
        for b, cc in sorted(m["blocs"].items(), key=lambda x: -x[1]):
            if cc > 20:
                print(f"  {cc:3d}  {b}")
        return 0

    pl = tomllib.loads(PLAFONDS.read_text(encoding="utf-8"))
    ecarts = verifier(m, pl)
    for e in ecarts:
        print(f"CLIQUET rouge — {e}")
    for b in baissables(m, pl):
        print(f"CLIQUET à baisser — {b}")
    if not ecarts:
        print(
            f"CLIQUET vert — execute hors stockage {m['execute_hors']}/"
            f"{pl['execute']['hors_stockage']}"
        )
    return 1 if ecarts else 0


if __name__ == "__main__":
    sys.exit(main())
