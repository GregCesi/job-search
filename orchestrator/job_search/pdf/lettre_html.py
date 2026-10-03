"""Mise en page HTML de la lettre pour son PDF (EXE-102, H2 du ticket).

Forme usuelle d'une lettre française, sans bloc destinataire — aucune adresse
n'est inventée (faute d'adresse, H2). Le texte de la lettre n'est jamais corrigé :
chaque paragraphe devient un <p> au caractère près, seul le HTML est échappé.
Noir uniquement, aucune image ni logo.
"""

from __future__ import annotations

import html as html_lib
import re
from datetime import date

from orchestrator.job_search.pdf.coordonnees import Coordonnees

_MOIS_FR = [
    "janvier",
    "février",
    "mars",
    "avril",
    "mai",
    "juin",
    "juillet",
    "août",
    "septembre",
    "octobre",
    "novembre",
    "décembre",
]


def format_date_fr(d: date) -> str:
    jour = "1er" if d.day == 1 else str(d.day)
    return f"{jour} {_MOIS_FR[d.month - 1]} {d.year}"


def _paragraphs(texte: str) -> list[str]:
    blocs = re.split(r"\n\s*\n", texte)
    return [b.strip("\n") for b in blocs if b.strip()]


def build_lettre_html(
    coordonnees: Coordonnees,
    intitule: str,
    texte: str,
    aujourdhui: date | None = None,
) -> str:
    d = aujourdhui or date.today()
    paragraphs_html = "\n".join(
        f"  <p>{html_lib.escape(p)}</p>" for p in _paragraphs(texte)
    )
    nom = html_lib.escape(coordonnees.nom)
    return f"""<!doctype html>
<html>
<head>
<meta charset="utf-8">
<style>
  body {{
    font-family: Helvetica, Arial, sans-serif;
    font-size: 10.5pt;
    line-height: 1.35;
    color: #000;
    margin: 2cm 2.5cm;
    font-variant-ligatures: none;
  }}
  .coordonnees div {{ margin: 0; }}
  .date-line {{ text-align: right; margin: 2em 0 1.5em; }}
  .objet {{ font-weight: bold; margin-bottom: 1.5em; }}
  p {{ margin: 0 0 1em 0; white-space: pre-wrap; }}
  .signature {{ margin-top: 1.5em; text-align: right; }}
</style>
</head>
<body>
  <div class="coordonnees">
    <div>{nom}</div>
    <div>{html_lib.escape(coordonnees.mail)}</div>
    <div>{html_lib.escape(coordonnees.telephone)}</div>
    <div>{html_lib.escape(coordonnees.ville)}</div>
  </div>
  <div class="date-line">{html_lib.escape(coordonnees.ville)}, le {format_date_fr(d)}</div>
  <div class="objet">Objet : candidature au poste de {html_lib.escape(intitule)}</div>
{paragraphs_html}
  <div class="signature">{nom}</div>
</body>
</html>"""
