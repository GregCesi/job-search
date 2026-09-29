"""Génération de la lettre de motivation (EXE-65) : fiche entreprise + choix de points +
préférences de ton + CV de référence → Claude Agent SDK → table `lettres`.

Frontière (architecture.md, exceptions encadrées) : l'appel SDK ne part que d'une
action explicite (POST /offers/{id}/lettre), jamais d'un changement de profil ou de la
fiche entreprise. Le choix des points est stocké avec la lettre (H2 du ticket) et ne
modifie jamais `fiches_entreprise.points_json`.
"""

import asyncio
import json
import sqlite3
from datetime import datetime, timezone

from claude_agent_sdk import ClaudeAgentOptions, ResultMessage, query

from orchestrator.job_search.lettre.redaction import (
    build_prompt,
    count_words,
    detect_tournures,
    exceeds_length,
    load_tournures_interdites,
    resolve_chosen_indices,
    strip_html,
)
from orchestrator.job_search.paths import (
    CV_REFERENCE_PATH,
    LETTRE_CWD,
    LETTRE_PREFERENCES_PATH,
    LETTRE_TOURNURES_PATH,
)
from orchestrator.job_search.storage.db import get_connection, init_db

TIMEOUT_S = 300  # 5 minutes (H6 du ticket, repris du CV)
MODELE = "sonnet"  # H5 : alias fixé du Claude Agent SDK

# La rédaction n'a besoin d'aucun outil : tout ce qu'il faut (offre, fiche, points,
# préférences, CV) est déjà dans le prompt (critère 22).
_TOOLS: list[str] = []
_FORBIDDEN_TOOLS = ["Bash", "Write", "Edit", "NotebookEdit", "WebSearch", "WebFetch"]


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def reset_pending(conn: sqlite3.Connection, offer_id: int) -> None:
    """Insère ou remet à zéro la ligne lettre en `pending` (relance après erreur incluse).

    Ne touche jamais `points_choisis_json` : le choix de points survit à une
    régénération (H2 du ticket), ce reset ne concerne que la sortie de génération.
    """
    conn.execute(
        """
        INSERT INTO lettres (offer_id, statut, created_at) VALUES (?, 'pending', ?)
        ON CONFLICT(offer_id) DO UPDATE SET
            statut='pending', texte=NULL, tournures_signalees_json=NULL, nb_mots=NULL,
            depasse_longueur=NULL, modele=NULL, session_id=NULL, cost_usd=NULL,
            prompt_text=NULL, error_message=NULL
        """,
        (offer_id, _now()),
    )
    conn.commit()


async def run_lettre(offer_id: int) -> None:
    """Produit la lettre de l'offre. Toute exception (dont le timeout, l'absence des
    préférences de ton, ou l'absence de point choisi) finit en `statut='error'`, sans
    qu'aucun texte ne soit stocké (critères 14, 23).
    """
    conn = get_connection()
    try:
        init_db(conn)
        reset_pending(conn, offer_id)
        try:
            offer = conn.execute(
                "SELECT description_raw FROM offers WHERE id = ?", (offer_id,)
            ).fetchone()
            if offer is None:
                raise ValueError(f"offre {offer_id} introuvable")

            fiche = conn.execute(
                "SELECT presentation, points_json FROM fiches_entreprise "
                "WHERE offer_id = ? AND statut = 'done'",
                (offer_id,),
            ).fetchone()
            if fiche is None:
                raise ValueError(f"fiche entreprise manquante pour l'offre {offer_id}")

            points = json.loads(fiche["points_json"] or "[]")
            row = conn.execute(
                "SELECT points_choisis_json FROM lettres WHERE offer_id = ?",
                (offer_id,),
            ).fetchone()
            chosen_indices = resolve_chosen_indices(
                points, row["points_choisis_json"] if row else None
            )
            if not chosen_indices:
                raise ValueError("aucun point choisi pour la lettre")
            chosen_points = [points[i] for i in chosen_indices]

            if not LETTRE_PREFERENCES_PATH.exists():
                raise FileNotFoundError(
                    f"préférences de ton manquantes : {LETTRE_PREFERENCES_PATH}"
                )
            preferences_ton = LETTRE_PREFERENCES_PATH.read_text(encoding="utf-8")

            if not CV_REFERENCE_PATH.exists():
                raise FileNotFoundError(
                    f"CV de référence manquant : {CV_REFERENCE_PATH}"
                )
            cv_reference_text = strip_html(
                CV_REFERENCE_PATH.read_text(encoding="utf-8")
            )

            prompt_text = build_prompt(
                offer["description_raw"] or "",
                fiche["presentation"] or "",
                chosen_points,
                preferences_ton,
                cv_reference_text,
            )

            result: ResultMessage | None = None
            LETTRE_CWD.mkdir(parents=True, exist_ok=True)
            options = ClaudeAgentOptions(
                tools=_TOOLS,
                allowed_tools=_TOOLS,
                disallowed_tools=_FORBIDDEN_TOOLS,
                model=MODELE,
                setting_sources=[],
                cwd=str(LETTRE_CWD),
                max_turns=5,
            )

            async def _consume() -> None:
                nonlocal result
                async for msg in query(prompt=prompt_text, options=options):
                    if isinstance(msg, ResultMessage):
                        result = msg

            await asyncio.wait_for(_consume(), timeout=TIMEOUT_S)

            if result is None:
                raise RuntimeError("aucun ResultMessage reçu du SDK")
            if result.is_error:
                raise RuntimeError(
                    f"SDK en erreur ({result.subtype}): {(result.result or '')[:500]}"
                )
            texte = (result.result or "").strip()
            if not texte:
                raise RuntimeError("réponse vide du modèle")

            tournures = load_tournures_interdites(LETTRE_TOURNURES_PATH)
            signalees = detect_tournures(texte, tournures)
            nb_mots = count_words(texte)

            conn.execute(
                """
                UPDATE lettres SET
                    statut='done', texte=?, tournures_signalees_json=?, nb_mots=?,
                    depasse_longueur=?, modele=?, session_id=?, cost_usd=?, prompt_text=?,
                    error_message=NULL
                WHERE offer_id=?
                """,
                (
                    texte,
                    json.dumps(signalees, ensure_ascii=False),
                    nb_mots,
                    int(exceeds_length(nb_mots)),
                    MODELE,
                    result.session_id,
                    result.total_cost_usd,
                    prompt_text,
                    offer_id,
                ),
            )
            conn.commit()
        except BaseException as exc:  # noqa: BLE001 — l'échec est une donnée (cf cv/service.py)
            conn.execute(
                "UPDATE lettres SET statut='error', error_message=? WHERE offer_id=?",
                (f"{type(exc).__name__}: {exc}"[:2000], offer_id),
            )
            conn.commit()
            if not isinstance(exc, Exception):
                raise
    finally:
        conn.close()
