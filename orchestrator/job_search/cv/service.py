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
from orchestrator.job_search.cv.corrections import add_skill, remove_skill
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


class CvNotReadyError(RuntimeError):
    """Aucun CV `done` pour cette offre : rien à corriger (EXE-59)."""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _groupes_to_json(groupes: list[SkillGroup]) -> str:
    return json.dumps(
        [{"label": g.label, "items": g.items} for g in groupes], ensure_ascii=False
    )


def _groupes_from_json(raw: str | None) -> list[SkillGroup]:
    return [
        SkillGroup(label=g["label"], items=list(g["items"]))
        for g in json.loads(raw or "[]")
    ]


def reset_pending(conn: sqlite3.Connection, offer_id: int) -> None:
    """Insère ou remet à zéro la ligne CV de l'offre en `pending` (relance après erreur incluse)."""
    conn.execute(
        """
        INSERT INTO cvs (offer_id, statut, created_at) VALUES (?, 'pending', ?)
        ON CONFLICT(offer_id) DO UPDATE SET
            statut='pending', html=NULL, titre=NULL, localisation=NULL,
            au_cv_json=NULL, demande_sans_y_etre_json=NULL, ajouts_permis_json=NULL,
            groupes_json=NULL, notions_json=NULL,
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

            titre_defaut = get_titre_defaut(conn)
            title = titre_defaut if titre_defaut else clean_title(offer["title"] or "")
            location = detect_location(offer["location"], profile)

            # EXE-63 critères 3-5 : une offre qui nomme des technos toutes déjà couvertes
            # (ou sous le seuil) n'a rien à faire placer par le modèle — l'appeler ne
            # changerait rien au bloc compétences (architecture.md §4) et ne coûterait
            # que pour rien (cas réel : offre 2874, 1,00 $ pour 0 ajout). Une offre sans
            # aucune tech exigée (`techs_required` vide) reste sur l'ancien chemin : ce
            # n'est pas le cas documenté par le ticket.
            if techs_required and not additions:
                prompt_text = None
                session_id = None
                cost_usd = 0.0
                final_groups = list(ref.groupes)
            else:
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
                                b.name
                                for b in msg.content
                                if isinstance(b, ToolUseBlock)
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
                    SkillGroup(
                        label=g.get("label", ""), items=list(g.get("items") or [])
                    )
                    for g in (out.get("groupes") or [])
                ]
                final_groups = filter_model_groups(ref.groupes, model_groups, additions)
                session_id = result.session_id
                cost_usd = result.total_cost_usd

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
                    groupes_json=?, notions_json=?,
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
                    _groupes_to_json(final_groups),
                    json.dumps(ref.notions, ensure_ascii=False),
                    threshold,
                    session_id,
                    cost_usd,
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


def apply_correction(
    conn: sqlite3.Connection,
    offer_id: int,
    action: str,
    competence: str,
    maitrisee: bool | None,
    groupe: str | None,
) -> None:
    """Applique une correction manuelle (ajout/retrait) au CV déjà généré de
    l'offre et journalise l'entrée d'historique (EXE-59). Calcul 100% Python
    (critère 13) : aucun appel modèle, la connexion `conn` est fournie par
    l'appelant (route API). Une marque « Prête » (EXE-101) est effacée par
    toute correction : le contenu change, la validation humaine est à refaire.
    """
    init_db(conn)
    row = conn.execute("SELECT * FROM cvs WHERE offer_id = ?", (offer_id,)).fetchone()
    if row is None or row["statut"] != "done":
        raise CvNotReadyError(f"aucun CV terminé pour l'offre {offer_id}")

    groupes = _groupes_from_json(row["groupes_json"])
    notions = json.loads(row["notions_json"] or "[]")

    if action == "ajout":
        if maitrisee is None:
            raise ValueError("`maitrisee` est requis pour un ajout")
        outcome = add_skill(groupes, notions, competence, maitrisee, groupe)
    elif action == "retrait":
        outcome = remove_skill(groupes, notions, competence)
    else:
        raise ValueError(f"action inconnue : {action}")

    offer = conn.execute(
        "SELECT extracted_facts_json FROM offers WHERE id = ?", (offer_id,)
    ).fetchone()
    techs_required = (
        json.loads(offer["extracted_facts_json"] or "{}").get("techs_required") or []
    )
    alias_table = load_alias_table(ALIAS_PATH)
    present = block_canonicals(outcome.groupes, outcome.notions, alias_table)
    demande_sans_y_etre = compute_requested_missing(
        techs_required, alias_table, present
    )
    au_cv = compute_au_cv(outcome.groupes, outcome.notions)

    if not CV_REFERENCE_PATH.exists():
        raise FileNotFoundError(f"CV de référence manquant : {CV_REFERENCE_PATH}")
    cv_html_ref = CV_REFERENCE_PATH.read_text(encoding="utf-8")
    html = generate_cv_html(
        cv_html_ref, row["titre"], row["localisation"], outcome.groupes, outcome.notions
    )

    conn.execute(
        """
        UPDATE cvs SET
            html=?, au_cv_json=?, demande_sans_y_etre_json=?,
            groupes_json=?, notions_json=?, marque_pret_at=NULL
        WHERE offer_id=?
        """,
        (
            html,
            json.dumps(au_cv, ensure_ascii=False),
            json.dumps(demande_sans_y_etre, ensure_ascii=False),
            _groupes_to_json(outcome.groupes),
            json.dumps(outcome.notions, ensure_ascii=False),
            offer_id,
        ),
    )
    conn.execute(
        """
        INSERT INTO cv_corrections (offer_id, action, competence, maitrisee, groupe, created_at)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (offer_id, action, competence, int(outcome.maitrisee), outcome.groupe, _now()),
    )
    conn.commit()


def set_titre(conn: sqlite3.Connection, offer_id: int, titre: str) -> str:
    """Enregistre un titre choisi à la main pour le CV déjà généré d'une offre
    (EXE-130), à la place du titre calculé depuis l'intitulé de l'offre.
    Calcul 100% Python : aucun appel modèle. Une marque « Prête » (EXE-101)
    est effacée : le contenu change, la validation humaine est à refaire.
    """
    init_db(conn)
    row = conn.execute("SELECT * FROM cvs WHERE offer_id = ?", (offer_id,)).fetchone()
    if row is None or row["statut"] != "done":
        raise CvNotReadyError(f"aucun CV terminé pour l'offre {offer_id}")
    titre = titre.strip()
    if not titre:
        raise ValueError("le titre du CV ne peut pas être vide")

    groupes = _groupes_from_json(row["groupes_json"])
    notions = json.loads(row["notions_json"] or "[]")
    if not CV_REFERENCE_PATH.exists():
        raise FileNotFoundError(f"CV de référence manquant : {CV_REFERENCE_PATH}")
    cv_html_ref = CV_REFERENCE_PATH.read_text(encoding="utf-8")
    html = generate_cv_html(cv_html_ref, titre, row["localisation"], groupes, notions)

    conn.execute(
        "UPDATE cvs SET titre=?, html=?, marque_pret_at=NULL WHERE offer_id=?",
        (titre, html, offer_id),
    )
    conn.commit()
    return titre


def get_titre_defaut(conn: sqlite3.Connection) -> str | None:
    """Titre utilisé à la place de l'intitulé de l'offre pour les prochains CV
    générés (EXE-130), ou `None` si aucun n'est enregistré. Jamais appliqué
    aux CV déjà générés — il n'intervient qu'à la génération (`run_cv`)."""
    init_db(conn)
    row = conn.execute("SELECT titre_defaut FROM cv_settings WHERE id = 1").fetchone()
    return row["titre_defaut"] if row and row["titre_defaut"] else None


def set_titre_defaut(conn: sqlite3.Connection, titre_defaut: str) -> str:
    """Enregistre le titre par défaut (EXE-130). Calcul 100% Python : aucun
    appel modèle, aucune écriture sous un fichier suivi par git (table
    `cv_settings`, dans `data/job_search.sqlite`, hors git)."""
    init_db(conn)
    titre_defaut = titre_defaut.strip()
    if not titre_defaut:
        raise ValueError("le titre par défaut ne peut pas être vide")
    conn.execute(
        """
        INSERT INTO cv_settings (id, titre_defaut) VALUES (1, ?)
        ON CONFLICT(id) DO UPDATE SET titre_defaut=excluded.titre_defaut
        """,
        (titre_defaut,),
    )
    conn.commit()
    return titre_defaut


def clear_titre_defaut(conn: sqlite3.Connection) -> None:
    """Efface le titre par défaut (EXE-130) : les prochains CV reprennent
    l'intitulé de l'offre, comme avant son enregistrement."""
    init_db(conn)
    conn.execute(
        """
        INSERT INTO cv_settings (id, titre_defaut) VALUES (1, NULL)
        ON CONFLICT(id) DO UPDATE SET titre_defaut=NULL
        """
    )
    conn.commit()
