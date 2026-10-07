"""Génération de la fiche entreprise : cascade → prompt → Claude Agent SDK → table fiches_entreprise.

Frontière (architecture.md §4) : un appel SDK ne part que d'une action explicite
(POST /offers/{id}/fiche), jamais d'un changement de profil.
"""

import asyncio
import json
import sqlite3
from datetime import datetime, timezone

from claude_agent_sdk import (
    AssistantMessage,
    ClaudeAgentOptions,
    ResultMessage,
    SystemMessage,
    ToolUseBlock,
    query,
)

from orchestrator.job_search.fiche.cascade import identify_employer
from orchestrator.job_search.fiche.prompt import FAMILLES, build_prompt
from orchestrator.job_search.paths import FICHE_CWD
from orchestrator.job_search.storage.db import get_connection, init_db

MAX_POINTS = 8
# Plafond des points que la fiche désigne elle-même pour la lettre (EXE-132, H3) —
# constaté comme maximum choisi à la main sur les fiches du 5 octobre 2026.
MAX_LETTRE_POINTS = 4

_FICHE_SCHEMA = {
    "type": "object",
    "properties": {
        "mode": {"type": "string", "enum": ["entreprise", "offre_seule"]},
        "presentation": {"type": "string"},
        "employeur": {
            "type": "object",
            "properties": {
                "nom": {"type": ["string", "null"]},
                "entite_precise": {"type": ["string", "null"]},
                "type_source": {
                    "type": "string",
                    "enum": ["direct", "agence", "agregateur", "inconnu"],
                },
                "methode": {"type": "string"},
                "confiance": {
                    "type": "string",
                    "enum": ["sur", "probable", "non_trouve"],
                },
                "urls": {"type": "array", "items": {"type": "string"}},
            },
            "required": [
                "nom",
                "entite_precise",
                "type_source",
                "methode",
                "confiance",
                "urls",
            ],
        },
        "points": {
            "type": "array",
            "maxItems": MAX_POINTS,
            "items": {
                "type": "object",
                "properties": {
                    "position": {"type": "string"},
                    "citation": {"type": ["string", "null"]},
                    "url": {"type": ["string", "null"]},
                    # Type string libre, pas d'enum (EXE-149, critère 8) : une
                    # famille hors vocabulaire doit pouvoir être reçue puis
                    # écartée en code, jamais rejetée par le schéma du SDK.
                    "famille": {"type": ["string", "null"]},
                    "date": {"type": ["string", "null"]},
                },
                "required": ["position"],
            },
        },
        "points_pour_lettre": {
            "type": "array",
            "maxItems": MAX_LETTRE_POINTS,
            "items": {"type": "integer"},
        },
    },
    "required": ["mode", "presentation", "employeur", "points"],
}

# Trois champs déclarés explicitement à chaque appel : `allowed_tools` ne fait qu'auto-approuver,
# seul `tools` fixe l'ensemble disponible (TCK-224 phase 0).
_SEARCH_TOOLS = ["WebSearch", "WebFetch"]
_FORBIDDEN_TOOLS = ["Bash", "Write", "Edit", "NotebookEdit"]


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def reset_pending(conn: sqlite3.Connection, offer_id: int) -> None:
    """Insère ou remet à zéro la ligne fiche de l'offre en `pending` (relance après erreur incluse)."""
    conn.execute(
        """
        INSERT INTO fiches_entreprise (offer_id, statut, created_at) VALUES (?, 'pending', ?)
        ON CONFLICT(offer_id) DO UPDATE SET
            statut='pending', mode=NULL, presentation=NULL, employeur_nom=NULL, employeur_entite=NULL,
            employeur_type_source=NULL, employeur_confiance=NULL, employeur_methode=NULL,
            employeur_urls_json=NULL, points_json=NULL, session_id=NULL, cost_usd=NULL,
            tools_called_json=NULL, api_key_source=NULL, prompt_text=NULL,
            error_message=NULL, created_at=excluded.created_at
        """,
        (offer_id, _now()),
    )
    conn.commit()


def _parse_output(result: ResultMessage) -> dict:
    out = result.structured_output
    if out is None and result.result:
        out = json.loads(result.result)
    if not isinstance(out, dict):
        raise ValueError(f"sortie SDK sans JSON exploitable (subtype={result.subtype})")
    return out


def _cascade_in_thread(offer_id: int):
    conn = get_connection()
    try:
        return identify_employer(offer_id, conn)
    finally:
        conn.close()


async def run_fiche(offer_id: int) -> None:
    """Produit la fiche de l'offre. Toute exception finit en `statut='error'`."""
    conn = get_connection()
    try:
        init_db(conn)
        reset_pending(conn, offer_id)
        try:
            offer = conn.execute(
                "SELECT title, company, location, url, description, description_raw "
                "FROM offers WHERE id = ?",
                (offer_id,),
            ).fetchone()
            if offer is None:
                raise ValueError(f"offre {offer_id} introuvable")

            # Cascade synchrone (Ollama bloquant + scan des offres) : hors event loop, connexion propre.
            cascade = await asyncio.to_thread(_cascade_in_thread, offer_id)
            prompt = build_prompt(offer, cascade)

            api_key_source: str | None = None
            tools_called: list[str] = []
            result: ResultMessage | None = None
            # cwd stable et vide + aucune source de settings : la session de recherche ne charge ni
            # le CLAUDE.md du repo ni ses hooks, et la reprise de session (route explain) retrouve la session.
            FICHE_CWD.mkdir(parents=True, exist_ok=True)
            options = ClaudeAgentOptions(
                tools=_SEARCH_TOOLS,
                allowed_tools=_SEARCH_TOOLS,
                disallowed_tools=_FORBIDDEN_TOOLS,
                output_format={"type": "json_schema", "schema": _FICHE_SCHEMA},
                setting_sources=[],
                cwd=str(FICHE_CWD),
                max_turns=40,
            )
            async for msg in query(prompt=prompt, options=options):
                if isinstance(msg, SystemMessage) and msg.subtype == "init":
                    api_key_source = msg.data.get("apiKeySource")
                elif isinstance(msg, AssistantMessage):
                    tools_called += [
                        b.name for b in msg.content if isinstance(b, ToolUseBlock)
                    ]
                elif isinstance(msg, ResultMessage):
                    result = msg
            if result is None:
                raise RuntimeError("aucun ResultMessage reçu du SDK")
            if result.is_error:
                raise RuntimeError(
                    f"SDK en erreur ({result.subtype}): {(result.result or '')[:500]}"
                )

            out = _parse_output(result)
            employeur = out.get("employeur") or {}
            raw_points = (out.get("points") or [])[:MAX_POINTS]
            # Désignation pour la lettre (EXE-132) : index invalides ignorés (critère 5),
            # seuls les quatre premiers valides, dans l'ordre désigné, sont gardés (critère 4).
            valid_designated = [
                i
                for i in (out.get("points_pour_lettre") or [])
                if isinstance(i, int)
                and not isinstance(i, bool)
                and 0 <= i < len(raw_points)
            ]
            kept_designated = set(valid_designated[:MAX_LETTRE_POINTS])
            points = [
                {
                    "position": p.get("position"),
                    "citation": p.get("citation"),
                    "url": p.get("url"),
                    "tas": None,
                    "explication": None,
                    "pour_lettre": i in kept_designated,
                    # Famille hors des trois connues (critère 8) ou date absente
                    # (critère 7) : le point est gardé, seul le champ manque.
                    "famille": p.get("famille")
                    if p.get("famille") in FAMILLES
                    else None,
                    "date": p.get("date") or None,
                }
                for i, p in enumerate(raw_points)
            ]
            conn.execute(
                """
                UPDATE fiches_entreprise SET
                    statut='done', mode=?, presentation=?, employeur_nom=?, employeur_entite=?,
                    employeur_type_source=?, employeur_confiance=?, employeur_methode=?,
                    employeur_urls_json=?, points_json=?, session_id=?, cost_usd=?,
                    tools_called_json=?, api_key_source=?, prompt_text=?, error_message=NULL
                WHERE offer_id=?
                """,
                (
                    out.get("mode"),
                    out.get("presentation"),
                    employeur.get("nom"),
                    employeur.get("entite_precise"),
                    employeur.get("type_source"),
                    employeur.get("confiance"),
                    employeur.get("methode"),
                    json.dumps(employeur.get("urls") or [], ensure_ascii=False),
                    json.dumps(points, ensure_ascii=False),
                    result.session_id,
                    result.total_cost_usd,
                    json.dumps(tools_called),
                    api_key_source,
                    prompt,
                    offer_id,
                ),
            )
            conn.commit()
        except BaseException as exc:  # noqa: BLE001 — l'échec est une donnée ; l'annulation aussi
            conn.execute(
                "UPDATE fiches_entreprise SET statut='error', error_message=? WHERE offer_id=?",
                (f"{type(exc).__name__}: {exc}"[:2000], offer_id),
            )
            conn.commit()
            if not isinstance(exc, Exception):
                raise
    finally:
        conn.close()
