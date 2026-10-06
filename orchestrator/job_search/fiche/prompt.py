"""Construction du prompt fiche entreprise — source unique : .claude/commands/fiche-entreprise.md."""

import re
import sqlite3

from orchestrator.job_search.fiche.cascade import CascadeResult
from orchestrator.job_search.paths import FICHE_COMMAND_PATH

_FRONTMATTER = re.compile(r"\A---\n.*?\n---\n", re.DOTALL)
_MANUEL = re.compile(r"<!-- MANUEL -->.*?<!-- /MANUEL -->\n?", re.DOTALL)

# Consigne ajoutée en code (EXE-132) : le format de réponse de la fiche gagne un champ
# `points_pour_lettre`, le texte de .claude/commands/fiche-entreprise.md reste inchangé
# (H5 du ticket — aucune écriture sous .claude/).
_CONSIGNE_POINTS_POUR_LETTRE = (
    "En plus de l'objet JSON demandé ci-dessus, ajoute un champ `points_pour_lettre` : "
    "un tableau des index (0-based, dans l'ordre où tu les rends dans `points`) des "
    "points qui donnent une raison précise de vouloir ce poste dans cette entreprise, "
    "en lien avec le profil du candidat — quatre au plus, un tableau vide si aucun "
    "point ne s'y prête."
)


def load_template() -> str:
    text = FICHE_COMMAND_PATH.read_text(encoding="utf-8")
    text = _FRONTMATTER.sub("", text, count=1)
    return _MANUEL.sub("", text).strip()


def build_prompt(offer: sqlite3.Row, cascade: CascadeResult) -> str:
    desc = (offer["description_raw"] or offer["description"] or "").strip()
    url_line = f"URL de l'annonce : {offer['url']}\n" if offer["url"] else ""
    return (
        f"{load_template()}\n\n---\n"
        f"Résultat de la cascade d'identification (étape identifiante : {cascade.etape}) :\n"
        f"{cascade.model_dump_json(indent=2)}\n\n---\n"
        f"Titre : {offer['title'] or '—'}\n"
        f"Entreprise annoncée : {offer['company'] or 'non précisée'}\n"
        f"Lieu : {offer['location'] or 'non précisé'}\n"
        f"{url_line}"
        f"Description :\n{desc[:12000]}\n\n---\n"
        f"{_CONSIGNE_POINTS_POUR_LETTRE}"
    )
