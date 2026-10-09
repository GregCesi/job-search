"""Construction du prompt fiche entreprise — source unique : .claude/commands/fiche-entreprise.md."""

import re
import sqlite3

from orchestrator.job_search.fiche.cascade import CascadeResult
from orchestrator.job_search.lettre.repertoire import (
    Repertoire,
    RepertoireError,
    charger_repertoire,
)
from orchestrator.job_search.paths import FICHE_COMMAND_PATH, REPERTOIRE_LETTRE_PATH

_FRONTMATTER = re.compile(r"\A---\n.*?\n---\n", re.DOTALL)
_MANUEL = re.compile(r"<!-- MANUEL -->.*?<!-- /MANUEL -->\n?", re.DOTALL)

# Identifiants des trois familles de point décrites dans la demande générale
# (.claude/commands/fiche-entreprise.md) — produits par le chat, TCK-251 (EXE-149, H4).
FAMILLE_FACON_DE_TRAVAILLER = "facon_de_travailler"
FAMILLE_CE_QUE_LE_POSTE_FAIT_FAIRE = "ce_que_le_poste_fait_faire"
FAMILLE_PREUVE_IA = "preuve_ia"
FAMILLES = (
    FAMILLE_FACON_DE_TRAVAILLER,
    FAMILLE_CE_QUE_LE_POSTE_FAIT_FAIRE,
    FAMILLE_PREUVE_IA,
)

# Consigne ajoutée en code (EXE-149) : chaque point gagne sa famille (parmi les trois
# décrites plus haut) et la date de la page d'où il vient, inconditionnelle — elle ne
# dépend pas du répertoire de la lettre (critères 4, 5).
_CONSIGNE_FAMILLE_DATE = (
    "Pour chaque point de `points`, ajoute aussi :\n"
    f"- `famille` : l'identifiant de la famille parmi `{FAMILLE_FACON_DE_TRAVAILLER}`, "
    f"`{FAMILLE_CE_QUE_LE_POSTE_FAIT_FAIRE}`, `{FAMILLE_PREUVE_IA}` — celle décrite plus "
    "haut dans laquelle ce point entre.\n"
    "- `date` : la date portée par la page d'où vient le point, telle qu'elle y est "
    "écrite, mot pour mot — absente si la page ne porte aucune date."
)


def load_template() -> str:
    text = FICHE_COMMAND_PATH.read_text(encoding="utf-8")
    text = _FRONTMATTER.sub("", text, count=1)
    return _MANUEL.sub("", text).strip()


def _charger_repertoire_pour_prompt() -> Repertoire | None:
    """Répertoire absent ou mal formé (critères 9, 10) : la fiche continue avec la
    demande générale seule, jamais d'exception remontée jusqu'à `run_fiche`."""
    try:
        return charger_repertoire(REPERTOIRE_LETTRE_PATH).repertoire
    except RepertoireError:
        return None


def _sujets_non_generiques(repertoire: Repertoire) -> list:
    return [tt for tt in repertoire.textes_types if tt.id != "generique" and tt.sujet]


def sujets_valides() -> frozenset[str]:
    """Identifiants que le champ `sujet` d'un point peut porter (critère 5 du
    ticket EXE-161) : ceux listés dans la demande, le générique exclu — répertoire
    absent ou mal formé donne un ensemble vide, et tout `sujet` rendu par le modèle
    devient alors null (critère 3)."""
    repertoire = _charger_repertoire_pour_prompt()
    if repertoire is None:
        return frozenset()
    return frozenset(tt.id for tt in _sujets_non_generiques(repertoire))


def _section_repertoire(repertoire: Repertoire | None) -> str:
    """Sujets des textes types autres que le générique (avec leur identifiant,
    critère 1 EXE-161), leurs conditions d'usage et les sujets interdits (critères
    1 à 3 EXE-149) — jamais un exemple, un avis ou la posture (« ce qui ne doit pas
    arriver » du ticket) : seuls `id`, `sujet`, `s_applique_si` et
    `ne_s_applique_pas_si` sont lus. Un champ à trou est déjà absent de `repertoire`
    (nettoyé par `charger_repertoire` — critère 11)."""
    if repertoire is None:
        return ""
    sujets_txt = "\n".join(
        f"- {tt.id} : {tt.sujet}"
        + (f" — s'applique si : {tt.s_applique_si}" if tt.s_applique_si else "")
        + (
            f" — ne s'applique pas si : {tt.ne_s_applique_pas_si}"
            if tt.ne_s_applique_pas_si
            else ""
        )
        for tt in _sujets_non_generiques(repertoire)
    )
    interdits_txt = "\n".join(
        f"- {s.sujet}"
        + (f" ({s.motif})" if s.motif else "")
        + (f" sauf : {s.exception}" if s.exception else "")
        for s in repertoire.sujets_interdits
        if s.sujet
    )
    parts = []
    if sujets_txt:
        parts.append(
            "J'ai déjà des textes prêts qui répondent à ces sujets : fais-en une "
            f"priorité quand un fait précis y répond sans forcer.\n{sujets_txt}"
        )
    if interdits_txt:
        parts.append(
            f"Sujets que je ne veux jamais voir dans un point :\n{interdits_txt}"
        )
    return "\n\n".join(parts)


def build_prompt(offer: sqlite3.Row, cascade: CascadeResult) -> str:
    desc = (offer["description_raw"] or offer["description"] or "").strip()
    url_line = f"URL de l'annonce : {offer['url']}\n" if offer["url"] else ""
    section_repertoire = _section_repertoire(_charger_repertoire_pour_prompt())
    consignes = _CONSIGNE_FAMILLE_DATE
    if section_repertoire:
        consignes = f"{consignes}\n\n---\n{section_repertoire}"
    return (
        f"{load_template()}\n\n---\n"
        f"Résultat de la cascade d'identification (étape identifiante : {cascade.etape}) :\n"
        f"{cascade.model_dump_json(indent=2)}\n\n---\n"
        f"Titre : {offer['title'] or '—'}\n"
        f"Entreprise annoncée : {offer['company'] or 'non précisée'}\n"
        f"Lieu : {offer['location'] or 'non précisé'}\n"
        f"{url_line}"
        f"Description :\n{desc[:12000]}\n\n---\n"
        f"{consignes}"
    )
