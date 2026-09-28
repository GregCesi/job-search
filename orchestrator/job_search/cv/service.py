"""Génération du CV adapté (EXE-58) : profil/alias → ajouts autorisés (Python pur) →
placement par Claude Agent SDK dans les groupes existants → rendu HTML → table `cvs`.

Frontière (architecture.md §4) : le LLM ne décide jamais QUELLES compétences ajouter,
seulement OÙ les placer. Comme la fiche entreprise, un appel SDK ne part que d'une
action explicite (POST /offers/{id}/cv), jamais d'un changement de profil.
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

from orchestrator.job_search.cv import prompt as cv_prompt
from orchestrator.job_search.cv.config import skill_threshold
from orchestrator.job_search.cv.skills import (
    SkillGroup,
    block_canonicals,
    clean_title,
    compute_au_cv,
    compute_permitted_additions,
    compute_requested_missing,
    detect_location,
    filter_model_groups,
    generate_cv_html,
    parse_reference_block,
)
from orchestrator.job_search.matching.profile import load_profile
from orchestrator.job_search.paths import (
    ALIAS_PATH,
    CV_CWD,
    CV_REFERENCE_PATH,
    PROFILE_PATH,
)
from orchestrator.job_search.scoring.aliases import load_alias_table
from orchestrator.job_search.storage.db import get_connection, init_db

TIMEOUT_S = 300  # 5 minutes (H6 du ticket)

# Le placement n'a besoin d'aucun outil : tout ce qu'il faut (groupes, ajouts autorisés)
# est déjà dans le prompt.
_TOOLS: list[str] = []
_FORBIDDEN_TOOLS = ["Bash", "Write", "Edit", "NotebookEdit", "WebSearch", "WebFetch"]


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def reset_pending(conn: sqlite3.Connection, offer_id: int) -> None:
    """Insère ou remet à zéro la ligne CV de l'offre en `pending` (relance après erreur incluse)."""
    conn.execute(
        """
        INSERT INTO cvs (offer_id, statut, created_at) VALUES (?, 'pending', ?)
        ON CONFLICT(offer_id) DO UPDATE SET
            statut='pending', html=NULL, titre=NULL, localisation=NULL,
            au_cv_json=NULL, demande_sans_y_etre_json=NULL, ajouts_permis_json=NULL,
            seuil_utilise=NULL, session_id=NULL, cost_usd=NULL, prompt_text=NULL,
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


async def run_cv(offer_id: int) -> None:
    """Produit le CV de l'offre. Toute exception (dont le timeout) finit en `statut='error'`,
    sans qu'aucun HTML ne soit stocké (critère 22).
    """
    conn = get_connection()
    try:
        init_db(conn)
        reset_pending(conn, offer_id)
        try:
            offer = conn.execute(
                "SELECT title, location, extracted_facts_json FROM offers WHERE id = ?",
                (offer_id,),
            ).fetchone()
            if offer is None:
                raise ValueError(f"offre {offer_id} introuvable")

            profile, _digest = load_profile(PROFILE_PATH)
            alias_table = load_alias_table(ALIAS_PATH)
            if not CV_REFERENCE_PATH.exists():
                raise FileNotFoundError(
                    f"CV de référence manquant : {CV_REFERENCE_PATH}"
                )
            cv_html_ref = CV_REFERENCE_PATH.read_text(encoding="utf-8")

            ref = parse_reference_block(cv_html_ref)
            facts = json.loads(offer["extracted_facts_json"] or "{}")
            techs_required = facts.get("techs_required") or []

            covered = block_canonicals(ref.groupes, ref.notions, alias_table)
            threshold = skill_threshold()
            additions = compute_permitted_additions(
                techs_required, profile, alias_table, covered, threshold
            )

            title = clean_title(offer["title"] or "")
            location = detect_location(offer["location"], profile)
            prompt_text = cv_prompt.build_prompt(title, ref.groupes, additions)

            api_key_source: str | None = None
            tools_called: list[str] = []
            result: ResultMessage | None = None
            # cwd stable et vide + aucune source de settings (même isolation que fiche/service.py).
            CV_CWD.mkdir(parents=True, exist_ok=True)
            options = ClaudeAgentOptions(
                tools=_TOOLS,
                allowed_tools=_TOOLS,
                disallowed_tools=_FORBIDDEN_TOOLS,
                output_format={"type": "json_schema", "schema": cv_prompt.SCHEMA},
                setting_sources=[],
                cwd=str(CV_CWD),
                max_turns=10,
            )

            async def _consume() -> None:
                nonlocal api_key_source, result
                async for msg in query(prompt=prompt_text, options=options):
                    if isinstance(msg, SystemMessage) and msg.subtype == "init":
                        api_key_source = msg.data.get("apiKeySource")
                    elif isinstance(msg, AssistantMessage):
                        tools_called.extend(
                            b.name for b in msg.content if isinstance(b, ToolUseBlock)
                        )
                    elif isinstance(msg, ResultMessage):
                        result = msg

            await asyncio.wait_for(_consume(), timeout=TIMEOUT_S)

            if result is None:
                raise RuntimeError("aucun ResultMessage reçu du SDK")
            if result.is_error:
                raise RuntimeError(
                    f"SDK en erreur ({result.subtype}): {(result.result or '')[:500]}"
                )

            out = _parse_output(result)
            model_groups = [
                SkillGroup(label=g.get("label", ""), items=list(g.get("items") or []))
                for g in (out.get("groupes") or [])
            ]
            final_groups = filter_model_groups(ref.groupes, model_groups, additions)
            cv_html = generate_cv_html(
                cv_html_ref, title, location, final_groups, ref.notions
            )

            present = block_canonicals(final_groups, ref.notions, alias_table)
            au_cv = compute_au_cv(final_groups, ref.notions)
            demande_sans_y_etre = compute_requested_missing(
                techs_required, alias_table, present
            )

            conn.execute(
                """
                UPDATE cvs SET
                    statut='done', html=?, titre=?, localisation=?,
                    au_cv_json=?, demande_sans_y_etre_json=?, ajouts_permis_json=?,
                    seuil_utilise=?, session_id=?, cost_usd=?, prompt_text=?, error_message=NULL
                WHERE offer_id=?
                """,
                (
                    cv_html,
                    title,
                    location,
                    json.dumps(au_cv, ensure_ascii=False),
                    json.dumps(demande_sans_y_etre, ensure_ascii=False),
                    json.dumps([a.raw_name for a in additions], ensure_ascii=False),
                    threshold,
                    result.session_id,
                    result.total_cost_usd,
                    prompt_text,
                    offer_id,
                ),
            )
            conn.commit()
        except BaseException as exc:  # noqa: BLE001 — l'échec est une donnée (cf fiche/service.py)
            conn.execute(
                "UPDATE cvs SET statut='error', error_message=? WHERE offer_id=?",
                (f"{type(exc).__name__}: {exc}"[:2000], offer_id),
            )
            conn.commit()
            if not isinstance(exc, Exception):
                raise
    finally:
        conn.close()
