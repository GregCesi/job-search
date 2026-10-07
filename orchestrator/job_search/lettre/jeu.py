"""Préparation du jeu d'évaluation figé du banc de la lettre (EXE-151).

Part uniquement d'une commande lancée à la main (`python -m
orchestrator.job_search.lettre.jeu --nom ... --offres ...`). Lecture seule de
`offers` et `verdicts` — n'écrit dans aucune table, et ne lit ni n'écrit
`fiches_entreprise` : la recherche d'entreprise de chaque offre est rejouée à
part, par la même fonction que l'application (`fiche.service.rechercher_entreprise`),
jamais lue depuis la fiche déjà en base.

Le jeu produit est un fichier JSON figé sous `data/lettre/banc/jeux/<nom>.json`
(hors git comme le reste de `data/`), lu ensuite par le banc
(`lettre/banc.py`) sans jamais ouvrir la base.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sqlite3
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from orchestrator.job_search.fiche.cascade import identify_employer
from orchestrator.job_search.fiche.service import rechercher_entreprise
from orchestrator.job_search.lettre.redaction import (
    RAISON_TEXTE_MANQUANT,
    resolve_offer_text,
)
from orchestrator.job_search.paths import DB_PATH, LETTRE_BANC_JEUX_DIR

RAISON_OFFRE_INTROUVABLE = "aucune offre ne correspond à ce numéro"
RAISON_NON_RETENUE = "l'offre n'est pas retenue"


class JeuExistantError(ValueError):
    """Un jeu du même nom existe déjà (critère 10) : la préparation refuse,
    sans appeler aucun modèle, et laisse le jeu existant intact."""


@dataclass
class OffreJeuResolue:
    """Résolution d'un numéro d'offre côté base, avant toute recherche
    d'entreprise : soit prête pour la recherche, soit sautée avec sa raison
    (critères 6, 7, 8) — ces offres sautées n'entrent jamais dans le jeu."""

    offer_id: int
    skip_reason: str | None
    titre: str = ""
    entreprise: str = ""
    texte_offre: str = ""
    row: sqlite3.Row | None = None


def _resoudre_offre_pour_jeu(
    conn: sqlite3.Connection, offer_id: int
) -> OffreJeuResolue:
    offer = conn.execute(
        "SELECT title, company, location, url, description, description_raw "
        "FROM offers WHERE id = ?",
        (offer_id,),
    ).fetchone()
    if offer is None:
        return OffreJeuResolue(offer_id, RAISON_OFFRE_INTROUVABLE)

    titre = offer["title"] or ""
    entreprise = offer["company"] or ""

    verdict = conn.execute(
        "SELECT status FROM verdicts WHERE offer_id = ? ORDER BY id DESC LIMIT 1",
        (offer_id,),
    ).fetchone()
    if verdict is None or verdict["status"] != "retenu":
        return OffreJeuResolue(offer_id, RAISON_NON_RETENUE, titre, entreprise)

    texte = resolve_offer_text(offer["description_raw"], offer["description"])
    if not texte:
        return OffreJeuResolue(offer_id, RAISON_TEXTE_MANQUANT, titre, entreprise)

    return OffreJeuResolue(offer_id, None, titre, entreprise, texte, offer)


def _fait_depuis_point(point: dict) -> dict:
    """Un fait du jeu ne porte que ce que la recherche a rendu (position,
    citation, lien, famille, date) — jamais les champs de classement humain
    de la fiche (`tas`, `explication`, `pour_lettre`), hors de propos ici."""
    return {
        "position": point.get("position"),
        "citation": point.get("citation"),
        "url": point.get("url"),
        "famille": point.get("famille"),
        "date": point.get("date"),
    }


def _fmt_cout(cout: float | None) -> str:
    return f"{cout:.4f}$" if cout is not None else "coût non rendu"


async def _preparer_une_offre(
    conn: sqlite3.Connection, offer_id: int
) -> tuple[dict | None, str]:
    """Rend (entrée de jeu ou `None` si sautée côté base, ligne de résumé
    affichée à la fin de la préparation — critère 12)."""
    resolue = _resoudre_offre_pour_jeu(conn, offer_id)
    if resolue.skip_reason is not None:
        ligne = (
            f"offre {offer_id} ({resolue.entreprise}) — {resolue.skip_reason} — "
            f"0.0s — {_fmt_cout(None)}"
        )
        return None, ligne

    debut = time.perf_counter()
    try:
        cascade = identify_employer(offer_id, conn)
        resultat = await rechercher_entreprise(resolue.row, cascade)
    except Exception as exc:  # noqa: BLE001 — l'échec est une donnée pour le jeu
        duree = time.perf_counter() - debut
        raison = f"la recherche a échoué : {exc}"
        entree = {
            "offer_id": offer_id,
            "intitule": resolue.titre,
            "entreprise": resolue.entreprise,
            "texte_offre": resolue.texte_offre,
            "faits": [],
            "raison_echec_recherche": raison,
        }
        ligne = (
            f"offre {offer_id} ({resolue.entreprise}) — {raison} — "
            f"{duree:.1f}s — {_fmt_cout(None)}"
        )
        return entree, ligne

    duree = time.perf_counter() - debut
    faits = [_fait_depuis_point(p) for p in resultat.points]
    entreprise = resultat.employeur_nom or resolue.entreprise
    entree = {
        "offer_id": offer_id,
        "intitule": resolue.titre,
        "entreprise": entreprise,
        "texte_offre": resolue.texte_offre,
        "faits": faits,
        "raison_echec_recherche": None,
    }
    ligne = (
        f"offre {offer_id} ({entreprise}) — {len(faits)} fait(s) — "
        f"{duree:.1f}s — {_fmt_cout(resultat.cost_usd)}"
    )
    return entree, ligne


@dataclass
class ResultatPreparation:
    chemin: Path
    jeu: dict
    lignes_resume: list[str]


async def preparer_jeu(
    conn: sqlite3.Connection,
    nom: str,
    offer_ids: list[int],
    *,
    jeux_dir: str | Path = LETTRE_BANC_JEUX_DIR,
) -> ResultatPreparation:
    """Prépare le jeu `nom` pour `offer_ids`, dans cet ordre (critère 12).
    Refuse sans appeler aucun modèle si `nom` existe déjà (critère 10)."""
    jeux_dir = Path(jeux_dir)
    chemin = jeux_dir / f"{nom}.json"
    if chemin.exists():
        raise JeuExistantError(f"un jeu nommé « {nom} » existe déjà : {chemin}")

    offres_jeu: list[dict] = []
    lignes: list[str] = []
    for offer_id in offer_ids:
        entree, ligne = await _preparer_une_offre(conn, offer_id)
        if entree is not None:
            offres_jeu.append(entree)
        lignes.append(ligne)

    jeu = {
        "nom": nom,
        "prepare_le": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "offres": offres_jeu,
    }
    jeux_dir.mkdir(parents=True, exist_ok=True)
    chemin.write_text(json.dumps(jeu, ensure_ascii=False, indent=2), encoding="utf-8")

    for ligne in lignes:
        print(ligne)

    return ResultatPreparation(chemin=chemin, jeu=jeu, lignes_resume=lignes)


# --- CLI ----------------------------------------------------------------------


def main(
    argv: list[str] | None = None,
    *,
    jeux_dir: str | Path = LETTRE_BANC_JEUX_DIR,
    db_path: str | Path = DB_PATH,
) -> int:
    """python -m orchestrator.job_search.lettre.jeu --nom essai1 --offres
    179,1677 (H2 du ticket)."""
    parser = argparse.ArgumentParser(
        description="Préparation du jeu d'évaluation figé du banc de la lettre"
    )
    parser.add_argument("--nom", required=True, help="nom du jeu à préparer")
    parser.add_argument(
        "--offres", required=True, help="numéros d'offres séparés par des virgules"
    )
    args = parser.parse_args(argv)

    try:
        offer_ids = [
            int(morceau.strip())
            for morceau in args.offres.split(",")
            if morceau.strip()
        ]
    except ValueError:
        print(f"liste d'offres invalide : « {args.offres} »")
        return 1

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        try:
            resultat = asyncio.run(
                preparer_jeu(conn, args.nom, offer_ids, jeux_dir=jeux_dir)
            )
        except JeuExistantError as exc:
            print(str(exc))
            return 1
    finally:
        conn.close()

    print(f"Jeu écrit : {resultat.chemin}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
