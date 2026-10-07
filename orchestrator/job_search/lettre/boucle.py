"""Boucle de la lettre (EXE-147) : un tamis choisit le fait de l'entreprise et le
texte type, une rédaction écrit, un juge recruteur renvoie à la rédaction — trois
lettres au plus (LangGraph, architecture.md « Exception encadrée : banc de la lettre »,
stack.md « Boucle de la lettre — LangGraph »).

Hors de l'application : aucune route, aucun run, aucun geste de retenir ne lance cette
boucle (elle sert au banc, EXE-148, et à l'usage manuel), et elle n'écrit dans aucune
table — lecture seule de `offers` et `fiches_entreprise`.

Un seul texte type est envoyé à la rédaction (le texte type choisi par le tamis),
jamais le répertoire entier, et un exemple sans texte n'est jamais envoyé (critères 11,
12). Le rédacteur et le juge n'ont jamais la même session de modèle : chacun a son
répertoire de travail (cf. `paths.BOUCLE_*_CWD`).
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sqlite3
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, TypedDict

import ollama
from claude_agent_sdk import ClaudeAgentOptions, ResultMessage, query
from langgraph.graph import END, StateGraph

from orchestrator.job_search.lettre.redaction import (
    count_words,
    detect_tournures,
    load_tournures_interdites,
    resolve_offer_text,
    strip_html,
)
from orchestrator.job_search.lettre.repertoire import (
    Repertoire,
    TexteType,
    charger_repertoire,
)
from orchestrator.job_search.paths import (
    BOUCLE_JUGE_CWD,
    BOUCLE_REDACTION_CWD,
    BOUCLE_TAMIS_CWD,
    CV_REFERENCE_PATH,
    LETTRE_TOURNURES_PATH,
    REPERTOIRE_LETTRE_PATH,
)

MAX_TOURS = 3  # H1 du ticket : plafond de trois lettres
GENERIQUE_ID = "generique"

# H5/H6 du ticket : alias Claude Agent SDK vs modèle local Ollama.
MODELES_CLAUDE = {"sonnet", "opus"}
TIMEOUT_CLAUDE_S = 300  # H8, repris de la lettre actuelle
TIMEOUT_OLLAMA_S = 900  # H8, défaut non mesuré

_OLLAMA_HOST = "http://localhost:11434"
_CWD_PAR_NOEUD = {
    "tamis": BOUCLE_TAMIS_CWD,
    "redaction": BOUCLE_REDACTION_CWD,
    "juge": BOUCLE_JUGE_CWD,
}
_FORBIDDEN_TOOLS = ["Bash", "Write", "Edit", "NotebookEdit", "WebSearch", "WebFetch"]

RAISON_GENERIQUE_MANQUANT = "Le texte générique n'est pas écrit dans le répertoire"
RAISON_RIEN_A_REDIRE = "Le juge n'a rien à redire"
RAISON_PLAFOND = "Le plafond de tours est atteint"

_SCHEMA_TAMIS = {
    "type": "object",
    "properties": {
        "point_index": {"type": ["integer", "null"]},
        "texte_type_id": {"type": "string"},
    },
    "required": ["texte_type_id"],
}

_SCHEMA_JUGE = {
    "type": "object",
    "properties": {
        "rien_a_redire": {"type": "boolean"},
        "remarques": {"type": ["string", "null"]},
    },
    "required": ["rien_a_redire"],
}


def raison_reponse_illisible(noeud: str) -> str:
    return f"Le {noeud} a rendu une réponse que le code ne sait pas lire"


def raison_appel_echoue(noeud: str, detail: str) -> str:
    return f"L'appel au modèle du nœud « {noeud} » a échoué : {detail}"


class AppelModeleError(RuntimeError):
    """Un appel de modèle a échoué ou dépassé son délai (critère 26)."""


@dataclass
class ReponseModele:
    texte: str
    duree_s: float
    cout_usd: float | None


@dataclass
class Appel:
    """Trace d'un appel de modèle (critère 20) : jamais persisté, seulement rendu."""

    noeud: Literal["tamis", "redaction", "juge"]
    modele: str
    duree_s: float
    cout_usd: float | None
    demande: str
    reponse: str


@dataclass
class ConfigBoucle:
    modele_tamis: str
    modele_redaction: str
    modele_juge: str


@dataclass
class ResultatBoucle:
    fait_retenu: dict | str  # dict (position/citation/url) ou "generique" (critère 17)
    texte_type_id: str
    lettres: list[dict]
    nb_tours: int
    raison_fin: str
    appels: list[Appel]


class EtatBoucle(TypedDict):
    titre: str
    texte_offre: str
    entreprise: str
    points_fiche: list[dict]
    cv_reference_text: str
    tournures_interdites: list[str]
    repertoire: Repertoire
    config: ConfigBoucle
    fait_retenu: dict | None
    texte_type: TexteType | None
    lettres: list[dict]
    tour: int
    appels: list[Appel]
    erreur: dict | None
    fin: bool
    raison_fin: str | None


def _appeler_claude(
    modele: str, prompt_text: str, cwd: Path, schema: dict | None
) -> ReponseModele:
    cwd.mkdir(parents=True, exist_ok=True)
    options_kwargs: dict = {
        "tools": [],
        "allowed_tools": [],
        "disallowed_tools": _FORBIDDEN_TOOLS,
        "model": modele,
        "setting_sources": [],
        "cwd": str(cwd),
        "max_turns": 5,
    }
    if schema is not None:
        options_kwargs["output_format"] = {"type": "json_schema", "schema": schema}
    options = ClaudeAgentOptions(**options_kwargs)

    result: ResultMessage | None = None

    async def _consume() -> None:
        nonlocal result
        async for msg in query(prompt=prompt_text, options=options):
            if isinstance(msg, ResultMessage):
                result = msg

    debut = time.monotonic()
    try:
        asyncio.run(asyncio.wait_for(_consume(), timeout=TIMEOUT_CLAUDE_S))
    except TimeoutError as exc:
        raise AppelModeleError("a dépassé son délai") from exc
    except Exception as exc:  # noqa: BLE001 — l'échec est une donnée pour le nœud
        raise AppelModeleError(str(exc)) from exc
    duree = time.monotonic() - debut

    if result is None:
        raise AppelModeleError("aucun ResultMessage reçu du SDK")
    if result.is_error:
        raise AppelModeleError(f"SDK en erreur ({result.subtype})")
    texte = (result.result or "").strip()
    if not texte:
        raise AppelModeleError("réponse vide du modèle")
    return ReponseModele(texte=texte, duree_s=duree, cout_usd=result.total_cost_usd)


def _appeler_ollama(
    modele: str, prompt_text: str, schema: dict | None
) -> ReponseModele:
    client = ollama.Client(host=_OLLAMA_HOST, timeout=TIMEOUT_OLLAMA_S)
    debut = time.monotonic()
    try:
        resp = client.chat(
            model=modele,
            messages=[{"role": "user", "content": prompt_text}],
            format=schema if schema is not None else "",
            options={"temperature": 0.1},
            think=False,
        )
    except Exception as exc:  # noqa: BLE001 — l'échec est une donnée pour le nœud
        raise AppelModeleError(str(exc)) from exc
    duree = time.monotonic() - debut
    texte = (resp.message.content or "").strip()
    if not texte:
        raise AppelModeleError("réponse vide du modèle")
    return ReponseModele(texte=texte, duree_s=duree, cout_usd=None)


def appeler_modele(
    noeud: Literal["tamis", "redaction", "juge"],
    modele: str,
    prompt_text: str,
    schema: dict | None = None,
) -> ReponseModele:
    """Point d'appel unique des trois nœuds — c'est lui que les tests doublent."""
    if modele in MODELES_CLAUDE:
        return _appeler_claude(modele, prompt_text, _CWD_PAR_NOEUD[noeud], schema)
    return _appeler_ollama(modele, prompt_text, schema)


def _texte_point(point: dict) -> str:
    # EXE-150, critères 3, 4, 9, 10 : famille et date, omises entièrement si
    # absentes — jamais de mention vide, de « None » ou de « aucune ».
    extras = []
    if point.get("famille"):
        extras.append(f"famille : {point['famille']}")
    if point.get("date"):
        extras.append(f"date : {point['date']}")
    extras_txt = f" ({', '.join(extras)})" if extras else ""
    return (
        f"{point.get('position') or ''} — « {point.get('citation') or ''} » "
        f"(lien : {point.get('url') or 'aucun'}){extras_txt}"
    )


def _sujets_interdits_txt(repertoire: Repertoire) -> str:
    # EXE-150, critères 5, 6 : motif omis s'il est absent, jamais rendu « None »
    # ni en parenthèses vides — même convention que fiche/prompt.py.
    return (
        "\n".join(
            f"- {s.sujet}"
            + (f" ({s.motif})" if s.motif else "")
            + (f" sauf : {s.exception}" if s.exception else "")
            for s in repertoire.sujets_interdits
        )
        or "(aucun)"
    )


def _prompt_tamis(
    titre: str, texte_offre: str, points: list[dict], repertoire: Repertoire
) -> str:
    points_txt = (
        "\n".join(f"{i}. {_texte_point(p)}" for i, p in enumerate(points))
        or "(aucun point)"
    )
    textes_types_txt = "\n".join(
        f"- {tt.id} : {tt.sujet}"
        + (f" — s'applique si : {tt.s_applique_si}" if tt.s_applique_si else "")
        + (
            f" — ne s'applique pas si : {tt.ne_s_applique_pas_si}"
            if tt.ne_s_applique_pas_si
            else ""
        )
        for tt in repertoire.textes_types
    )
    sujets_interdits_txt = _sujets_interdits_txt(repertoire)
    bonne_accroche_txt = (
        "\n".join(f"- {b}" for b in repertoire.ce_qui_fait_une_bonne_accroche)
        or "(non précisé)"
    )
    conditions_txt = (
        "\n".join(f"- {c}" for c in repertoire.conditions_generales) or "(aucune)"
    )
    return (
        "Tu choisis, parmi les points de la fiche entreprise ci-dessous, celui qui "
        "donne une raison précise de vouloir rejoindre cette entreprise, entre dans "
        "une des familles de bonne accroche, et auquel un texte type répond sans "
        "forcer. Une accroche faible vaut « générique ».\n\n"
        f"**Offre** :\n{titre}\n\n{texte_offre}\n\n"
        f"**Points de la fiche entreprise** :\n{points_txt}\n\n"
        f"**Textes types disponibles** (id : sujet) :\n{textes_types_txt}\n\n"
        f"**Ce qui fait une bonne accroche** :\n{bonne_accroche_txt}\n\n"
        f"**Sujets interdits** :\n{sujets_interdits_txt}\n\n"
        f"**Conditions générales** :\n{conditions_txt}\n\n"
        'Rends un JSON {"point_index": <index ou null>, "texte_type_id": <id>}. '
        "Si aucun point ne donne une accroche assez forte, rends "
        '{"point_index": null, "texte_type_id": "generique"}.'
    )


def _parser_tamis(texte: str) -> tuple[int | None, str]:
    data = json.loads(texte)
    if not isinstance(data, dict):
        raise ValueError("réponse du tamis : pas un objet JSON")
    texte_type_id = data.get("texte_type_id")
    if not isinstance(texte_type_id, str):
        raise ValueError("réponse du tamis : texte_type_id manquant")
    point_index = data.get("point_index")
    if point_index is not None and (
        not isinstance(point_index, int) or isinstance(point_index, bool)
    ):
        raise ValueError("réponse du tamis : point_index invalide")
    return point_index, texte_type_id


def noeud_tamis(state: EtatBoucle) -> dict:
    repertoire = state["repertoire"]
    prompt = _prompt_tamis(
        state["titre"], state["texte_offre"], state["points_fiche"], repertoire
    )
    try:
        reponse = appeler_modele(
            "tamis", state["config"].modele_tamis, prompt, schema=_SCHEMA_TAMIS
        )
    except AppelModeleError as exc:
        return {
            "erreur": {
                "noeud": "tamis",
                "raison": raison_appel_echoue("tamis", str(exc)),
            }
        }

    try:
        point_index, texte_type_id = _parser_tamis(reponse.texte)
    except (ValueError, json.JSONDecodeError):
        return {
            "erreur": {"noeud": "tamis", "raison": raison_reponse_illisible("tamis")}
        }

    appel = Appel(
        noeud="tamis",
        modele=state["config"].modele_tamis,
        duree_s=reponse.duree_s,
        cout_usd=reponse.cout_usd,
        demande=prompt,
        reponse=reponse.texte,
    )

    texte_type = next(
        (tt for tt in repertoire.textes_types if tt.id == texte_type_id), None
    )
    point = None
    if (
        texte_type is not None
        and texte_type.id != GENERIQUE_ID
        and point_index is not None
        and 0 <= point_index < len(state["points_fiche"])
    ):
        point = state["points_fiche"][point_index]

    if texte_type is None or (texte_type.id != GENERIQUE_ID and point is None):
        # Critères 5 et 6 : point ou texte type hors répertoire → générique entier.
        texte_type = next(tt for tt in repertoire.textes_types if tt.id == GENERIQUE_ID)
        point = None

    if texte_type.id == GENERIQUE_ID and not (texte_type.texte or "").strip():
        return {
            "appels": state["appels"] + [appel],
            "erreur": {"noeud": "tamis", "raison": RAISON_GENERIQUE_MANQUANT},
        }

    return {
        "appels": state["appels"] + [appel],
        "fait_retenu": point,
        "texte_type": texte_type,
    }


def _exemples_avec_texte(texte_type: TexteType) -> list:
    return [ex for ex in texte_type.exemples if (ex.texte or "").strip()]


def _prompt_redaction(state: EtatBoucle) -> str:
    repertoire = state["repertoire"]
    posture = repertoire.posture
    forme = repertoire.forme
    texte_type = state["texte_type"]
    fait = state["fait_retenu"]

    posture_txt = (
        f"Rôle : {posture.role or ''}\n"
        f"Quatre temps : {', '.join(posture.quatre_temps)}\n"
        f"Règles : {'; '.join(posture.regles)}\n"
        "Formulations rejetées : "
        + "; ".join(
            f"{f.texte} ({f.motif})" for f in posture.formulations_rejetees if f.texte
        )
    )
    forme_txt = (
        f"Blocs : {', '.join(forme.blocs)}\n"
        f"Longueur cible : {forme.longueur_cible_mots or '?'} mots\n"
        f"Lettre de référence : {forme.lettre_de_reference or '(aucune)'}"
    )
    sujets_interdits_txt = _sujets_interdits_txt(repertoire)

    if fait is not None:
        fait_txt = f"**Fait retenu de l'entreprise** :\n{_texte_point(fait)}\n\n"
    else:
        fait_txt = "**Aucun fait d'entreprise retenu** : lettre générique.\n\n"

    exemples_txt = (
        "\n".join(
            f"- {ex.entreprise} : {ex.fait} — texte : {ex.texte}"
            for ex in _exemples_avec_texte(texte_type)
        )
        or "(aucun exemple avec texte)"
    )
    # EXE-150, critères 1, 2 : le texte générique écrit à la main est envoyé en
    # entier à la rédaction, seulement quand le tamis a choisi « generique » —
    # un autre texte type ne reçoit jamais ce texte.
    texte_generique_txt = (
        f"Texte générique :\n{texte_type.texte or ''}\n\n"
        if texte_type.id == GENERIQUE_ID
        else ""
    )
    texte_type_txt = (
        f"{texte_generique_txt}"
        f"Conviction : {texte_type.conviction or ''}\n"
        f"Ce que j'ai fait : {texte_type.ce_que_j_ai_fait or ''}\n"
        f"Exemples :\n{exemples_txt}"
    )

    reprise_txt = ""
    if state["lettres"]:
        derniere = state["lettres"][-1]
        reprise_txt = (
            "\n\n**Lettre précédente** :\n"
            f"{derniere['texte']}\n\n"
            "**Remarques du juge à corriger** :\n"
            f"{derniere['remarques_juge']}\n"
        )

    return (
        "Tu écris une lettre de motivation, en français, en suivant la forme et la "
        "posture ci-dessous, bâtie sur le fait et le texte type reçus. Rends "
        "uniquement le texte de la lettre.\n\n"
        f"**Offre** : {state['titre']}\n"
        f"**Entreprise** : {state['entreprise']}\n\n"
        f"**Posture** :\n{posture_txt}\n\n"
        f"**Forme** :\n{forme_txt}\n\n"
        f"**Sujets interdits** :\n{sujets_interdits_txt}\n\n"
        f"{fait_txt}"
        f"**Texte type** :\n{texte_type_txt}\n\n"
        f"**CV de référence** :\n{state['cv_reference_text']}"
        f"{reprise_txt}"
    )


def noeud_redaction(state: EtatBoucle) -> dict:
    prompt = _prompt_redaction(state)
    try:
        reponse = appeler_modele("redaction", state["config"].modele_redaction, prompt)
    except AppelModeleError as exc:
        return {
            "erreur": {
                "noeud": "redaction",
                "raison": raison_appel_echoue("redaction", str(exc)),
            }
        }

    texte = reponse.texte
    tournures = detect_tournures(texte, state["tournures_interdites"])
    lettre = {
        "texte": texte,
        "nb_mots": count_words(texte),
        "tournures_signalees": tournures,
        "remarques_juge": None,
    }
    appel = Appel(
        noeud="redaction",
        modele=state["config"].modele_redaction,
        duree_s=reponse.duree_s,
        cout_usd=reponse.cout_usd,
        demande=prompt,
        reponse=texte,
    )
    return {
        "appels": state["appels"] + [appel],
        "lettres": state["lettres"] + [lettre],
        "tour": state["tour"] + 1,
    }


def _prompt_juge(state: EtatBoucle) -> str:
    repertoire = state["repertoire"]
    posture = repertoire.posture
    derniere = state["lettres"][-1]
    regles_txt = "\n".join(f"- {r}" for r in posture.regles) or "(aucune)"
    formulations_txt = (
        "\n".join(
            f"- {f.texte} ({f.motif})" for f in posture.formulations_rejetees if f.texte
        )
        or "(aucune)"
    )
    sujets_interdits_txt = _sujets_interdits_txt(repertoire)
    return (
        "Tu lis cette lettre de motivation comme un recruteur qui ne connaît pas le "
        "candidat. Dis ce que tu ressens à la lecture, relève les passages qui gênent "
        "au regard des règles de posture et des formulations rejetées ci-dessous. Ne "
        "dis « rien à redire » que si tu n'as rien relevé.\n\n"
        f"**Offre** : {state['titre']}\n"
        f"**Entreprise** : {state['entreprise']}\n\n"
        f"**Lettre à juger** :\n{derniere['texte']}\n\n"
        f"**Règles de posture** :\n{regles_txt}\n\n"
        f"**Formulations rejetées** :\n{formulations_txt}\n\n"
        f"**Sujets interdits** :\n{sujets_interdits_txt}\n\n"
        'Rends un JSON {"rien_a_redire": <bool>, "remarques": <texte ou null>}.'
    )


def _parser_juge(texte: str) -> tuple[bool, str | None]:
    data = json.loads(texte)
    if not isinstance(data, dict) or "rien_a_redire" not in data:
        raise ValueError("réponse du juge : rien_a_redire manquant")
    rien_a_redire = data["rien_a_redire"]
    if not isinstance(rien_a_redire, bool):
        raise ValueError("réponse du juge : rien_a_redire n'est pas un booléen")
    remarques = data.get("remarques")
    if remarques is not None and not isinstance(remarques, str):
        raise ValueError("réponse du juge : remarques invalides")
    return rien_a_redire, remarques


def noeud_juge(state: EtatBoucle) -> dict:
    prompt = _prompt_juge(state)
    try:
        reponse = appeler_modele(
            "juge", state["config"].modele_juge, prompt, schema=_SCHEMA_JUGE
        )
    except AppelModeleError as exc:
        return {
            "erreur": {"noeud": "juge", "raison": raison_appel_echoue("juge", str(exc))}
        }

    try:
        rien_a_redire, remarques = _parser_juge(reponse.texte)
    except (ValueError, json.JSONDecodeError):
        return {"erreur": {"noeud": "juge", "raison": raison_reponse_illisible("juge")}}

    appel = Appel(
        noeud="juge",
        modele=state["config"].modele_juge,
        duree_s=reponse.duree_s,
        cout_usd=reponse.cout_usd,
        demande=prompt,
        reponse=reponse.texte,
    )
    lettres = list(state["lettres"])
    lettres[-1] = {
        **lettres[-1],
        "remarques_juge": None if rien_a_redire else remarques,
    }

    if rien_a_redire:
        return {
            "appels": state["appels"] + [appel],
            "lettres": lettres,
            "fin": True,
            "raison_fin": RAISON_RIEN_A_REDIRE,
        }
    if state["tour"] >= MAX_TOURS:
        return {
            "appels": state["appels"] + [appel],
            "lettres": lettres,
            "fin": True,
            "raison_fin": RAISON_PLAFOND,
        }
    return {"appels": state["appels"] + [appel], "lettres": lettres, "fin": False}


def _route_apres_tamis(state: EtatBoucle) -> str:
    return END if state.get("erreur") else "redaction"


def _route_apres_redaction(state: EtatBoucle) -> str:
    return END if state.get("erreur") else "juge"


def _route_apres_juge(state: EtatBoucle) -> str:
    if state.get("erreur") or state.get("fin"):
        return END
    return "redaction"


def _construire_graphe():
    graphe = StateGraph(EtatBoucle)
    graphe.add_node("tamis", noeud_tamis)
    graphe.add_node("redaction", noeud_redaction)
    graphe.add_node("juge", noeud_juge)
    graphe.set_entry_point("tamis")
    graphe.add_conditional_edges(
        "tamis", _route_apres_tamis, {"redaction": "redaction", END: END}
    )
    graphe.add_conditional_edges(
        "redaction", _route_apres_redaction, {"juge": "juge", END: END}
    )
    graphe.add_conditional_edges(
        "juge", _route_apres_juge, {"redaction": "redaction", END: END}
    )
    return graphe.compile()


_GRAPHE = _construire_graphe()


def dessiner_graphe() -> str:
    """Mermaid texte du graphe (critère 27) : tamis, rédaction, juge, et le retour du
    juge vers la rédaction."""
    return _GRAPHE.get_graph().draw_mermaid()


def _invoquer_graphe(etat_initial: EtatBoucle) -> ResultatBoucle:
    etat_final = _GRAPHE.invoke(etat_initial)

    erreur = etat_final.get("erreur")
    raison = erreur["raison"] if erreur else etat_final["raison_fin"]
    fait = etat_final.get("fait_retenu")
    texte_type = etat_final.get("texte_type")

    return ResultatBoucle(
        fait_retenu=fait if fait is not None else GENERIQUE_ID,
        texte_type_id=texte_type.id if texte_type is not None else GENERIQUE_ID,
        lettres=etat_final["lettres"],
        nb_tours=etat_final["tour"],
        raison_fin=raison,
        appels=etat_final["appels"],
    )


def generer_lettre_depuis_donnees(
    titre: str,
    texte_offre: str,
    entreprise: str,
    points_fiche: list[dict],
    config: ConfigBoucle,
    repertoire_path: str | Path = REPERTOIRE_LETTRE_PATH,
    cv_reference_path: str | Path = CV_REFERENCE_PATH,
    tournures_path: str | Path = LETTRE_TOURNURES_PATH,
) -> ResultatBoucle:
    """Lance la boucle tamis → rédaction → juge sur des données déjà résolues
    (EXE-151) — n'ouvre et ne lit aucune table, contrairement à
    `generer_lettre_boucle` qui résout depuis `offers` et `fiches_entreprise`.
    Sert la préparation du jeu du banc (`lettre/jeu.py`), qui résout ses offres
    depuis le jeu plutôt que depuis la base."""
    charge = charger_repertoire(repertoire_path)
    cv_reference_text = strip_html(Path(cv_reference_path).read_text(encoding="utf-8"))
    tournures = load_tournures_interdites(Path(tournures_path))

    etat_initial: EtatBoucle = {
        "titre": titre,
        "texte_offre": texte_offre,
        "entreprise": entreprise,
        "points_fiche": points_fiche,
        "cv_reference_text": cv_reference_text,
        "tournures_interdites": tournures,
        "repertoire": charge.repertoire,
        "config": config,
        "fait_retenu": None,
        "texte_type": None,
        "lettres": [],
        "tour": 0,
        "appels": [],
        "erreur": None,
        "fin": False,
        "raison_fin": None,
    }
    return _invoquer_graphe(etat_initial)


def generer_lettre_boucle(
    conn: sqlite3.Connection,
    offer_id: int,
    config: ConfigBoucle,
    repertoire_path: str | Path = REPERTOIRE_LETTRE_PATH,
    cv_reference_path: str | Path = CV_REFERENCE_PATH,
    tournures_path: str | Path = LETTRE_TOURNURES_PATH,
) -> ResultatBoucle:
    """Lance la boucle tamis → rédaction → juge sur une offre (critère 1).

    Lecture seule de `offers` et `fiches_entreprise` — n'écrit dans aucune table."""
    offer = conn.execute(
        "SELECT title, description_raw, description, company FROM offers WHERE id = ?",
        (offer_id,),
    ).fetchone()
    if offer is None:
        raise ValueError(f"offre {offer_id} introuvable")
    texte_offre = resolve_offer_text(offer["description_raw"], offer["description"])

    fiche = conn.execute(
        "SELECT points_json, employeur_nom FROM fiches_entreprise "
        "WHERE offer_id = ? AND statut = 'done'",
        (offer_id,),
    ).fetchone()
    if fiche is None:
        raise ValueError(f"fiche entreprise terminée manquante pour l'offre {offer_id}")
    points_fiche = json.loads(fiche["points_json"] or "[]")
    entreprise = fiche["employeur_nom"] or offer["company"] or ""

    return generer_lettre_depuis_donnees(
        offer["title"] or "",
        texte_offre,
        entreprise,
        points_fiche,
        config,
        repertoire_path=repertoire_path,
        cv_reference_path=cv_reference_path,
        tournures_path=tournures_path,
    )


def main() -> int:
    """python -m orchestrator.job_search.lettre.boucle --graphe — imprime le dessin
    mermaid du graphe (critère 27)."""
    parser = argparse.ArgumentParser(description="Boucle de la lettre (LangGraph)")
    parser.add_argument(
        "--graphe", action="store_true", help="imprime le dessin du graphe"
    )
    args = parser.parse_args()
    if args.graphe:
        print(dessiner_graphe())
        return 0
    parser.print_help()
    return 1


if __name__ == "__main__":
    sys.exit(main())
