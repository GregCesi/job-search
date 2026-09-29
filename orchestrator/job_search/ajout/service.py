"""Traitement d'un ajout à la main (EXE-79), exécuté en tâche de fond par l'API.

Même chaîne que le /run pour une offre (`ingestion.process_offer`) : filtre dur,
extraction (un seul appel LLM), scoring Python, porte hors périmètre. L'état de
l'ajout vit dans `ajouts`, jamais dans `offers`.
"""

import json
import os
import sqlite3
from datetime import datetime, timezone

from dotenv import load_dotenv

from orchestrator.job_search.ingestion import process_offer
from orchestrator.job_search.matching.profile import load_profile
from orchestrator.job_search.paths import ALIAS_PATH, PROFILE_PATH
from orchestrator.job_search.scoring.aliases import load_alias_table
from orchestrator.job_search.sources.manual import (
    JobPostingAbsent,
    ManualSource,
    PageInjoignable,
)
from orchestrator.job_search.storage.db import get_connection
from orchestrator.job_search.storage.dedup import find_existing


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def create_ajout(conn: sqlite3.Connection, url: str) -> int:
    cur = conn.execute(
        "INSERT INTO ajouts (url, statut, created_at) VALUES (?, 'en_cours', ?)",
        (url, _now()),
    )
    conn.commit()
    return cur.lastrowid


def _finish(
    conn: sqlite3.Connection,
    ajout_id: int,
    statut: str,
    *,
    offer_id: int | None = None,
    categorie: str | None = None,
    raison: str | None = None,
    causes: list[str] | None = None,
    message: str | None = None,
) -> None:
    conn.execute(
        """
        UPDATE ajouts SET statut = ?, offer_id = ?, categorie = ?, raison = ?,
                          causes_json = ?, message = ?, finished_at = ?
        WHERE id = ?
        """,
        (
            statut,
            offer_id,
            categorie,
            raison,
            json.dumps(causes) if causes else None,
            message,
            _now(),
            ajout_id,
        ),
    )
    conn.commit()


def run_ajout(ajout_id: int, source: ManualSource) -> None:
    """Lit l'offre, la dédoublonne, la traite et écrit l'état final de l'ajout.
    Ne laisse jamais un ajout « en cours » : toute erreur finit en « échec »."""
    conn = get_connection()
    try:
        try:
            [offer] = source.fetch()
        except PageInjoignable as exc:
            _finish(conn, ajout_id, "echec", message=str(exc))
            return
        except JobPostingAbsent as exc:
            _finish(conn, ajout_id, "texte_a_coller", message=str(exc))
            return

        existing = find_existing(conn, offer)
        if existing is not None:
            _finish(
                conn,
                ajout_id,
                "deja_en_base",
                offer_id=existing,
                message="Cette offre est déjà en base.",
            )
            return

        load_dotenv()
        profile, _ = load_profile(PROFILE_PATH)
        alias_table = load_alias_table(ALIAS_PATH)
        model = os.getenv("OLLAMA_MODEL", "gemma4:12b")
        host = os.getenv("OLLAMA_HOST", "http://localhost:11434")

        outcome = process_offer(
            conn, offer, profile, alias_table, model=model, host=host
        )
        offer_id = find_existing(conn, offer)
        if outcome.filter_reason is not None:
            _finish(
                conn,
                ajout_id,
                "filtree",
                offer_id=offer_id,
                raison=outcome.filter_reason,
            )
        elif outcome.perimetre_causes:
            _finish(
                conn,
                ajout_id,
                "hors_perimetre",
                offer_id=offer_id,
                causes=outcome.perimetre_causes,
            )
        else:
            _finish(
                conn,
                ajout_id,
                "termine",
                offer_id=offer_id,
                categorie=outcome.category.value,
            )
    except Exception as exc:
        _finish(
            conn,
            ajout_id,
            "echec",
            message=f"Traitement interrompu par une erreur : {type(exc).__name__}: {exc}",
        )
    finally:
        conn.close()
