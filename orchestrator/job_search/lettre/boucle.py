"""Boucle de la lettre (EXE-147) : un tamis choisit le fait de l'entreprise et le
texte type, une rédaction écrit, un vérificateur relit (tournures interdites, lieux
absents de l'annonce, affirmations non soutenues — EXE-160) avant qu'un juge
recruteur renvoie à la rédaction — trois lettres jugées au plus (LangGraph,
architecture.md « Exception encadrée : banc de la lettre », stack.md « Boucle de la
lettre — LangGraph »). Une correction demandée par le vérificateur ne compte jamais
comme un tour.

Hors de l'application : aucune route, aucun run, aucun geste de retenir ne lance cette
boucle (elle sert au banc, EXE-148, et à l'usage manuel), et elle n'écrit dans aucune
table — lecture seule de `offers` et `fiches_entreprise`.

Un seul texte type est envoyé à la rédaction (le texte type choisi par le tamis),
jamais le répertoire entier, et un exemple sans texte n'est jamais envoyé (critères 11,
12). Le rédacteur, le vérificateur et le juge n'ont jamais la même session de modèle :
chacun a son répertoire de travail (cf. `paths.BOUCLE_*_CWD`).
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
    strip_style_and_script,
)
from orchestrator.job_search.lettre.repertoire import (
    Repertoire,
    TexteType,
    charger_repertoire,
    valider_juge_et_redaction,
)
from orchestrator.job_search.paths import (
    BOUCLE_JUGE_CWD,
    BOUCLE_REDACTION_CWD,
    BOUCLE_TAMIS_CWD,
    BOUCLE_VERIFICATEUR_CWD,
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
NUM_CTX_OLLAMA = 8192  # critère 18 : fenêtre de contexte d'un appel à un modèle local
_CWD_PAR_NOEUD = {
    "tamis": BOUCLE_TAMIS_CWD,
    "redaction": BOUCLE_REDACTION_CWD,
    "juge": BOUCLE_JUGE_CWD,
    "verificateur": BOUCLE_VERIFICATEUR_CWD,
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
        "ressenti": {"type": "string"},
        "details": {"type": "string"},
        "reussites": {"type": "string"},
        "verdict": {"type": "string"},
    },
    "required": ["rien_a_redire", "ressenti", "details", "reussites", "verdict"],
}

# EXE-160, critère 5 : le vérificateur relève les lieux et les affirmations par un
# appel de modèle — les tournures interdites sont relevées en Python (H4 du ticket).
_SCHEMA_VERIFICATEUR = {
    "type": "object",
    "properties": {
        "rien_a_signaler": {"type": "boolean"},
        "lieux": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "lieu": {"type": "string"},
                    "phrase": {"type": "string"},
                },
                "required": ["lieu", "phrase"],
            },
        },
        "affirmations": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "passage": {"type": "string"},
                    "manque": {"type": "string"},
                },
                "required": ["passage", "manque"],
            },
        },
    },
    "required": ["rien_a_signaler", "lieux", "affirmations"],
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
    nb_jetons: int | None = (
        None  # critère 19 : lu par un modèle local, jamais par Claude
    )


@dataclass
class Jugement:
    """Les quatre rubriques rendues par le juge (critère 5 du ticket EXE-158),
    pour la lettre qu'il vient de juger."""

    rien_a_redire: bool
    ressenti: str
    details: str
    reussites: str
    verdict: str


@dataclass
class Appel:
    """Trace d'un appel de modèle (critère 20) : jamais persisté, seulement rendu."""

    noeud: Literal["tamis", "redaction", "juge", "verificateur"]
    modele: str
    duree_s: float
    cout_usd: float | None
    demande: str
    reponse: str
    nb_jetons: int | None = None  # EXE-152, critères 19, 20


@dataclass
class ConfigBoucle:
    modele_tamis: str
    modele_redaction: str
    modele_juge: str
    # EXE-160, critère 15 : absent (None), le vérificateur tourne sur le modèle de
    # la rédaction — jamais un troisième modèle en dur.
    modele_verificateur: str | None = None

    def modele_verificateur_effectif(self) -> str:
        return self.modele_verificateur or self.modele_redaction


@dataclass
class ResultatBoucle:
    fait_retenu: dict | str  # dict (position/citation/url) ou "generique" (critère 17)
    texte_type_id: str
    lettres: list[dict]
    nb_tours: int
    raison_fin: str
    appels: list[Appel]
    # EXE-152, critères 14, 15 : nature de l'arrêt pour le banc, sans reparser
    # `raison_fin` — None si la boucle s'est terminée sans erreur.
    erreur_type: Literal["reponse_illisible", "appel_echoue"] | None = None


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
            options={"temperature": 0.1, "num_ctx": NUM_CTX_OLLAMA},
            think=False,
        )
    except Exception as exc:  # noqa: BLE001 — l'échec est une donnée pour le nœud
        raise AppelModeleError(str(exc)) from exc
    duree = time.monotonic() - debut
    texte = (resp.message.content or "").strip()
    if not texte:
        raise AppelModeleError("réponse vide du modèle")
    nb_jetons = getattr(resp, "prompt_eval_count", None)
    return ReponseModele(texte=texte, duree_s=duree, cout_usd=None, nb_jetons=nb_jetons)


def appeler_modele(
    noeud: Literal["tamis", "redaction", "juge", "verificateur"],
    modele: str,
    prompt_text: str,
    schema: dict | None = None,
) -> ReponseModele:
    """Point d'appel unique des trois nœuds — c'est lui que les tests doublent."""
    if modele in MODELES_CLAUDE:
        return _appeler_claude(modele, prompt_text, _CWD_PAR_NOEUD[noeud], schema)
    return _appeler_ollama(modele, prompt_text, schema)


def _texte_point(point: dict) -> str:
    # EXE-150, critères 3, 4, 9, 10 ; EXE-161, critère 9 : sujet, famille et date,
    # omis entièrement si absents — jamais de mention vide, de « None » ou de
    # « aucune ».
    extras = []
    if point.get("sujet"):
        extras.append(f"sujet : {point['sujet']}")
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


def _bloc_ce_qui_est_vrai_sur_moi(repertoire: Repertoire) -> str:
    """EXE-152, critères 1-3 : présentation identique pour la rédaction et le
    juge — bloc entièrement omis (jamais de rubrique vide ni de « None »)
    quand le répertoire ne porte pas la liste, ou qu'elle est vide."""
    phrases = repertoire.ce_qui_est_vrai_sur_moi
    if not phrases:
        return ""
    lignes = "\n".join(f"- {p}" for p in phrases)
    return (
        "**Ce qui est vrai sur moi, qu'une lettre ne doit jamais contredire** :\n"
        f"{lignes}\n\n"
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
        f"**Offre** :\n{titre}\n\n{strip_style_and_script(texte_offre)}\n\n"
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

    # EXE-155, critères 5-10 : le banc demande la lettre générique via
    # `modele_tamis == GENERIQUE_ID` — aucun modèle n'est appelé pour le tamis, le
    # nœud résout directement le texte type générique (même porte de disponibilité
    # que la résolution normale : texte absent du répertoire → même arrêt).
    if state["config"].modele_tamis == GENERIQUE_ID:
        texte_type = next(tt for tt in repertoire.textes_types if tt.id == GENERIQUE_ID)
        if not (texte_type.texte or "").strip():
            return {"erreur": {"noeud": "tamis", "raison": RAISON_GENERIQUE_MANQUANT}}
        return {"fait_retenu": None, "texte_type": texte_type}

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
                "type": "appel_echoue",
            }
        }

    try:
        point_index, texte_type_id = _parser_tamis(reponse.texte)
    except (ValueError, json.JSONDecodeError):
        return {
            "erreur": {
                "noeud": "tamis",
                "raison": raison_reponse_illisible("tamis"),
                "type": "reponse_illisible",
            }
        }

    appel = Appel(
        noeud="tamis",
        modele=state["config"].modele_tamis,
        duree_s=reponse.duree_s,
        cout_usd=reponse.cout_usd,
        demande=prompt,
        reponse=reponse.texte,
        nb_jetons=reponse.nb_jetons,
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


def _blocs_communs_redaction(state: EtatBoucle) -> str:
    """Contenu partagé par la rédaction normale et la correction du vérificateur
    (EXE-160) : offre, posture, forme, sujets interdits, ce qui est vrai sur moi,
    fait retenu, texte type, CV — jamais la reprise du juge ni le relevé du
    vérificateur, construits par leurs blocs de queue respectifs."""
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

    return (
        f"**Offre** : {state['titre']}\n"
        f"**Entreprise** : {state['entreprise']}\n\n"
        # EXE-155, critères 1-4 : le texte intégral de l'annonce, sans bloc de
        # style/script ni balise (`strip_html`), jamais raccourci — à chaque tour,
        # y compris les reprises après remarques du juge et les corrections du
        # vérificateur.
        f"**Texte de l'offre** :\n{strip_html(state['texte_offre'])}\n\n"
        f"**Posture** :\n{posture_txt}\n\n"
        f"**Forme** :\n{forme_txt}\n\n"
        f"**Sujets interdits** :\n{sujets_interdits_txt}\n\n"
        f"{_bloc_ce_qui_est_vrai_sur_moi(repertoire)}"
        f"{fait_txt}"
        f"**Texte type** :\n{texte_type_txt}\n\n"
        f"**CV de référence** :\n{state['cv_reference_text']}"
    )


def _prompt_redaction(state: EtatBoucle) -> str:
    repertoire = state["repertoire"]

    # EXE-158, critères 9-11 : à partir du deuxième tour, la rédaction reçoit la
    # lettre précédente, les quatre rubriques du dernier jugement telles que le
    # juge les a rendues (jamais celles des tours d'avant), et la consigne de
    # reprise de mon répertoire — absent au premier tour (critère 11).
    reprise_txt = ""
    if state["lettres"]:
        derniere = state["lettres"][-1]
        jugement = derniere["jugement"]
        reprise_txt = (
            "\n\n**Lettre précédente** :\n"
            f"{derniere['texte']}\n\n"
            "**Ce que le juge a ressenti à la lecture** :\n"
            f"{jugement.ressenti}\n\n"
            "**Détails relevés par le juge** :\n"
            f"{jugement.details}\n\n"
            "**Ce que la lettre réussit, selon le juge** :\n"
            f"{jugement.reussites}\n\n"
            "**Verdict du juge** :\n"
            f"{jugement.verdict}\n\n"
            "**Consigne de reprise** :\n"
            f"{repertoire.redaction.consigne_reprise}\n"
        )

    return (
        "Tu écris une lettre de motivation, en français, en suivant la forme et la "
        "posture ci-dessous, bâtie sur le fait et le texte type reçus. Rends "
        "uniquement le texte de la lettre.\n\n"
        f"{_blocs_communs_redaction(state)}"
        f"{reprise_txt}"
    )


def _tournures_releve_txt(tournures: list[str]) -> str:
    if not tournures:
        return ""
    lignes = "\n".join(f"- {t}" for t in tournures)
    return f"Tournures interdites relevées :\n{lignes}"


def _lieux_releve_txt(lieux: list[dict]) -> str:
    if not lieux:
        return ""
    lignes = "\n".join(f"- {lieu['lieu']} — « {lieu['phrase']} »" for lieu in lieux)
    return f"Lieux absents de l'annonce :\n{lignes}"


def _affirmations_releve_txt(affirmations: list[dict]) -> str:
    if not affirmations:
        return ""
    lignes = "\n".join(f"- « {a['passage']} » — {a['manque']}" for a in affirmations)
    return f"Affirmations non soutenues :\n{lignes}"


def releve_vide(releve: dict | None) -> bool:
    if releve is None:
        return True
    return (
        not releve["tournures"] and not releve["lieux"] and not releve["affirmations"]
    )


def releve_txt(releve: dict) -> str:
    """EXE-160, critère 6 : chaque liste vide est omise entièrement — jamais une
    rubrique vide ni le mot « None » — et un relevé entièrement vide dit « rien à
    signaler »."""
    blocs = [
        bloc
        for bloc in (
            _tournures_releve_txt(releve["tournures"]),
            _lieux_releve_txt(releve["lieux"]),
            _affirmations_releve_txt(releve["affirmations"]),
        )
        if bloc
    ]
    if not blocs:
        return "Rien à signaler."
    return "\n\n".join(blocs)


def releves_de_lettre(lettre: dict) -> list[dict]:
    """Les un ou deux relevés qu'une lettre a traversés (critère 13 du banc :
    « total sur tous les relevés »)."""
    releves = []
    if lettre.get("releve_redaction") is not None:
        releves.append(lettre["releve_redaction"])
    if lettre.get("releve_correction") is not None:
        releves.append(lettre["releve_correction"])
    return releves


def dernier_releve(lettre: dict) -> dict | None:
    """Le relevé qui précède le juge — après correction s'il y en a eu une
    (critère 13 du banc : « lettres finales encore signalées »)."""
    return lettre.get("releve_correction") or lettre.get("releve_redaction")


def _prompt_correction(state: EtatBoucle, derniere: dict) -> str:
    """EXE-160, critères 7, 10 : la rédaction corrige la lettre que le vérificateur
    vient de relire, sans jamais recevoir les rubriques du juge."""
    repertoire = state["repertoire"]
    releve = derniere["releve_redaction"]
    correction_txt = (
        "\n\n**Lettre à corriger** :\n"
        f"{derniere['texte_redige']}\n\n"
        "**Relevé du vérificateur** :\n"
        f"{releve_txt(releve)}\n\n"
        "**Consigne de correction** :\n"
        f"{repertoire.redaction.consigne_verification}\n"
    )
    return (
        "Tu corriges la lettre de motivation ci-dessous, en suivant la forme et la "
        "posture ci-dessous, à partir du relevé du vérificateur. Rends uniquement "
        "le texte corrigé de la lettre.\n\n"
        f"{_blocs_communs_redaction(state)}"
        f"{correction_txt}"
    )


def noeud_redaction(state: EtatBoucle) -> dict:
    lettres = state["lettres"]
    derniere = lettres[-1] if lettres else None
    # EXE-160, critère 9 : une correction porte sur la dernière lettre déjà écrite
    # ce tour (pas encore jugée, déjà relue une fois, pas encore corrigée) — elle
    # ne crée jamais une nouvelle entrée et ne compte jamais comme un tour.
    en_correction = (
        derniere is not None
        and derniere["jugement"] is None
        and derniere.get("releve_redaction") is not None
        and derniere.get("texte_corrige") is None
    )
    prompt = (
        _prompt_correction(state, derniere)
        if en_correction
        else _prompt_redaction(state)
    )
    try:
        reponse = appeler_modele("redaction", state["config"].modele_redaction, prompt)
    except AppelModeleError as exc:
        return {
            "erreur": {
                "noeud": "redaction",
                "raison": raison_appel_echoue("redaction", str(exc)),
                "type": "appel_echoue",
            }
        }

    texte = reponse.texte
    appel = Appel(
        noeud="redaction",
        modele=state["config"].modele_redaction,
        duree_s=reponse.duree_s,
        cout_usd=reponse.cout_usd,
        demande=prompt,
        reponse=texte,
        nb_jetons=reponse.nb_jetons,
    )

    if en_correction:
        nouvelle = {
            **derniere,
            "texte": texte,
            "nb_mots": count_words(texte),
            "texte_corrige": texte,
        }
        return {
            "appels": state["appels"] + [appel],
            "lettres": lettres[:-1] + [nouvelle],
        }

    lettre = {
        "texte": texte,
        "texte_redige": texte,
        "nb_mots": count_words(texte),
        "tournures_signalees": None,  # rempli par le vérificateur
        "releve_redaction": None,
        "texte_corrige": None,
        "releve_correction": None,
        "jugement": None,
    }
    return {
        "appels": state["appels"] + [appel],
        "lettres": lettres + [lettre],
        "tour": state["tour"] + 1,
    }


def _prompt_verificateur(state: EtatBoucle, texte_lettre: str) -> str:
    """EXE-160, critère 5 : consigne du vérificateur, lettre, offre, ce qui est
    vrai sur moi, CV de référence, fait retenu avec sa citation — jamais la
    posture, les sujets interdits ni les rubriques du juge."""
    repertoire = state["repertoire"]
    fait = state["fait_retenu"]
    if fait is not None:
        fait_txt = f"**Fait retenu de l'entreprise** :\n{_texte_point(fait)}\n\n"
    else:
        fait_txt = "**Aucun fait d'entreprise retenu** : lettre générique.\n\n"
    return (
        f"{repertoire.verificateur.consigne}\n\n"
        f"**Offre** : {state['titre']}\n"
        f"**Entreprise** : {state['entreprise']}\n\n"
        f"**Texte de l'offre** :\n{strip_html(state['texte_offre'])}\n\n"
        f"{_bloc_ce_qui_est_vrai_sur_moi(repertoire)}"
        f"{fait_txt}"
        f"**CV de référence** :\n{state['cv_reference_text']}\n\n"
        f"**Lettre à relire** :\n{texte_lettre}\n\n"
        'Rends un JSON {"rien_a_signaler": <bool>, "lieux": [{"lieu": <texte>, '
        '"phrase": <texte>}], "affirmations": [{"passage": <texte>, "manque": '
        "<texte>}]}."
    )


def _parser_verificateur(texte: str) -> tuple[list[dict], list[dict]]:
    """EXE-160, H4 : la réponse à qui manque rien_a_signaler, lieux ou
    affirmations est une réponse illisible — même raison que pour les autres
    nœuds."""
    data = json.loads(texte)
    if not isinstance(data, dict):
        raise ValueError("réponse du vérificateur : pas un objet JSON")
    for champ in ("rien_a_signaler", "lieux", "affirmations"):
        if champ not in data:
            raise ValueError(f"réponse du vérificateur : {champ} manquant")
    if not isinstance(data["rien_a_signaler"], bool):
        raise ValueError(
            "réponse du vérificateur : rien_a_signaler n'est pas un booléen"
        )
    lieux = data["lieux"]
    affirmations = data["affirmations"]
    if not isinstance(lieux, list) or not isinstance(affirmations, list):
        raise ValueError(
            "réponse du vérificateur : lieux ou affirmations n'est pas une liste"
        )
    for lieu in lieux:
        if (
            not isinstance(lieu, dict)
            or not isinstance(lieu.get("lieu"), str)
            or not isinstance(lieu.get("phrase"), str)
        ):
            raise ValueError("réponse du vérificateur : lieu invalide")
    for affirmation in affirmations:
        if (
            not isinstance(affirmation, dict)
            or not isinstance(affirmation.get("passage"), str)
            or not isinstance(affirmation.get("manque"), str)
        ):
            raise ValueError("réponse du vérificateur : affirmation invalide")
    return lieux, affirmations


def noeud_verificateur(state: EtatBoucle) -> dict:
    lettres = state["lettres"]
    derniere = lettres[-1]
    apres_correction = derniere["texte_corrige"] is not None
    texte_a_verifier = (
        derniere["texte_corrige"] if apres_correction else derniere["texte_redige"]
    )

    # Critère 2 : les tournures interdites sont relevées en Python, sans aucun
    # appel de modèle.
    tournures = detect_tournures(texte_a_verifier, state["tournures_interdites"])

    modele = state["config"].modele_verificateur_effectif()
    prompt = _prompt_verificateur(state, texte_a_verifier)
    try:
        reponse = appeler_modele(
            "verificateur", modele, prompt, schema=_SCHEMA_VERIFICATEUR
        )
    except AppelModeleError as exc:
        return {
            "erreur": {
                "noeud": "verificateur",
                "raison": raison_appel_echoue("verificateur", str(exc)),
                "type": "appel_echoue",
            }
        }

    try:
        lieux, affirmations = _parser_verificateur(reponse.texte)
    except (ValueError, json.JSONDecodeError):
        return {
            "erreur": {
                "noeud": "verificateur",
                "raison": raison_reponse_illisible("verificateur"),
                "type": "reponse_illisible",
            }
        }

    releve = {"tournures": tournures, "lieux": lieux, "affirmations": affirmations}
    appel = Appel(
        noeud="verificateur",
        modele=modele,
        duree_s=reponse.duree_s,
        cout_usd=reponse.cout_usd,
        demande=prompt,
        reponse=reponse.texte,
        nb_jetons=reponse.nb_jetons,
    )

    champ = "releve_correction" if apres_correction else "releve_redaction"
    nouvelle = {**derniere, champ: releve, "tournures_signalees": tournures}
    return {
        "appels": state["appels"] + [appel],
        "lettres": lettres[:-1] + [nouvelle],
    }


def _exemples_relecture_txt(repertoire: Repertoire) -> str:
    """EXE-158, critères 3, 8 : chaque exemple de relecture de mon répertoire, le
    titre ne portant que son passage lu et sa relecture — bloc entièrement omis
    (jamais de rubrique vide ni de « None ») quand le répertoire n'en porte
    aucun."""
    exemples = repertoire.juge.exemples
    if not exemples:
        return ""
    blocs = "\n\n".join(
        f"**{ex.titre}**\nPassage lu :\n{ex.passage_lu}\n\nRelecture :\n{ex.relecture}"
        for ex in exemples
    )
    return f"**Exemples de relecture** :\n{blocs}\n\n"


def _prompt_juge(state: EtatBoucle) -> str:
    """EXE-158, critères 1-4 : le juge reçoit la lettre, l'intitulé du poste, le
    nom de l'entreprise, le texte de l'annonce, et la consigne/le contexte/les
    exemples de relecture de mon répertoire — rien d'autre. Aucune règle de
    posture, formulation rejetée, sujet interdit, phrase de ce qui est vrai sur
    moi, lettre de référence, fait retenu ni CV ne lui parvient : ces blocs sont
    réservés à la rédaction."""
    repertoire = state["repertoire"]
    juge = repertoire.juge
    derniere = state["lettres"][-1]
    return (
        f"{juge.consigne}\n\n"
        f"{juge.contexte}\n\n"
        f"{_exemples_relecture_txt(repertoire)}"
        f"**Offre** : {state['titre']}\n"
        f"**Entreprise** : {state['entreprise']}\n\n"
        f"**Texte de l'offre** :\n{strip_html(state['texte_offre'])}\n\n"
        f"**Lettre à juger** :\n{derniere['texte']}\n\n"
        'Rends un JSON {"ressenti": <texte>, "details": <texte>, '
        '"reussites": <texte>, "verdict": <texte>, "rien_a_redire": <bool>}.'
    )


def _parser_juge(texte: str) -> Jugement:
    """EXE-158, critère 6 : la réponse à qui manque l'une des quatre rubriques
    (ou son indicateur rien_a_redire) est une réponse illisible — même raison
    que pour les autres nœuds."""
    data = json.loads(texte)
    if not isinstance(data, dict):
        raise ValueError("réponse du juge : pas un objet JSON")
    for champ in ("rien_a_redire", "ressenti", "details", "reussites", "verdict"):
        if champ not in data:
            raise ValueError(f"réponse du juge : {champ} manquant")
    rien_a_redire = data["rien_a_redire"]
    if not isinstance(rien_a_redire, bool):
        raise ValueError("réponse du juge : rien_a_redire n'est pas un booléen")
    for champ in ("ressenti", "details", "reussites", "verdict"):
        if not isinstance(data[champ], str):
            raise ValueError(f"réponse du juge : {champ} n'est pas un texte")
    return Jugement(
        rien_a_redire=rien_a_redire,
        ressenti=data["ressenti"],
        details=data["details"],
        reussites=data["reussites"],
        verdict=data["verdict"],
    )


def noeud_juge(state: EtatBoucle) -> dict:
    prompt = _prompt_juge(state)
    try:
        reponse = appeler_modele(
            "juge", state["config"].modele_juge, prompt, schema=_SCHEMA_JUGE
        )
    except AppelModeleError as exc:
        return {
            "erreur": {
                "noeud": "juge",
                "raison": raison_appel_echoue("juge", str(exc)),
                "type": "appel_echoue",
            }
        }

    try:
        jugement = _parser_juge(reponse.texte)
    except (ValueError, json.JSONDecodeError):
        return {
            "erreur": {
                "noeud": "juge",
                "raison": raison_reponse_illisible("juge"),
                "type": "reponse_illisible",
            }
        }

    appel = Appel(
        noeud="juge",
        modele=state["config"].modele_juge,
        duree_s=reponse.duree_s,
        cout_usd=reponse.cout_usd,
        demande=prompt,
        reponse=reponse.texte,
        nb_jetons=reponse.nb_jetons,
    )
    lettres = list(state["lettres"])
    lettres[-1] = {**lettres[-1], "jugement": jugement}

    if jugement.rien_a_redire:
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
    return END if state.get("erreur") else "verificateur"


def _route_apres_verificateur(state: EtatBoucle) -> str:
    """EXE-160, critères 7, 8 : un relevé non vide sur la lettre juste rédigée (pas
    encore corrigée) renvoie à la rédaction pour une correction ; sinon — relevé
    vide, ou relevé déjà corrigé une fois — la lettre part au juge."""
    if state.get("erreur"):
        return END
    derniere = state["lettres"][-1]
    if derniere["texte_corrige"] is None and not releve_vide(
        derniere["releve_redaction"]
    ):
        return "redaction"
    return "juge"


def _route_apres_juge(state: EtatBoucle) -> str:
    if state.get("erreur") or state.get("fin"):
        return END
    return "redaction"


def _construire_graphe():
    graphe = StateGraph(EtatBoucle)
    graphe.add_node("tamis", noeud_tamis)
    graphe.add_node("redaction", noeud_redaction)
    graphe.add_node("verificateur", noeud_verificateur)
    graphe.add_node("juge", noeud_juge)
    graphe.set_entry_point("tamis")
    graphe.add_conditional_edges(
        "tamis", _route_apres_tamis, {"redaction": "redaction", END: END}
    )
    graphe.add_conditional_edges(
        "redaction",
        _route_apres_redaction,
        {"verificateur": "verificateur", END: END},
    )
    graphe.add_conditional_edges(
        "verificateur",
        _route_apres_verificateur,
        {"redaction": "redaction", "juge": "juge", END: END},
    )
    graphe.add_conditional_edges(
        "juge", _route_apres_juge, {"redaction": "redaction", END: END}
    )
    return graphe.compile()


_GRAPHE = _construire_graphe()


def dessiner_graphe() -> str:
    """Mermaid texte du graphe (critère 27) : tamis, rédaction, vérificateur, juge,
    le retour du vérificateur vers la rédaction (correction) et celui du juge vers
    la rédaction (reprise)."""
    return _GRAPHE.get_graph().draw_mermaid()


def _invoquer_graphe(etat_initial: EtatBoucle) -> ResultatBoucle:
    etat_final = _GRAPHE.invoke(etat_initial)

    erreur = etat_final.get("erreur")
    raison = erreur["raison"] if erreur else etat_final["raison_fin"]
    # RAISON_GENERIQUE_MANQUANT (texte générique absent du répertoire) ne porte
    # pas de "type" : ni une réponse illisible, ni un appel échoué.
    erreur_type = erreur.get("type") if erreur else None
    fait = etat_final.get("fait_retenu")
    texte_type = etat_final.get("texte_type")

    return ResultatBoucle(
        fait_retenu=fait if fait is not None else GENERIQUE_ID,
        texte_type_id=texte_type.id if texte_type is not None else GENERIQUE_ID,
        lettres=etat_final["lettres"],
        nb_tours=etat_final["tour"],
        raison_fin=raison,
        appels=etat_final["appels"],
        erreur_type=erreur_type,
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
    # EXE-158, critères 13-14 : refus avant tout appel de modèle si la
    # consigne/le contexte du juge ou la consigne de reprise manquent.
    valider_juge_et_redaction(charge.repertoire)
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
