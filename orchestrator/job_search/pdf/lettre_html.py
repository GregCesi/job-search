"""Mise en page HTML de la lettre pour son PDF (EXE-102, H2 du ticket ; EXE-176).

Forme usuelle d'une lettre française, sans bloc destinataire — aucune adresse
n'est inventée (faute d'adresse, H2). Le texte de la lettre n'est jamais corrigé :
chaque paragraphe devient un <p> au caractère près, seul le HTML est échappé.
Noir uniquement, aucune image ni logo.

EXE-176 : un bloc à droite, même hauteur que mes coordonnées, porte le nom de
l'entreprise (déjà résolu par l'appelant, même résolution que le nom de fichier
— `pdf/filename.py:resolve_entreprise`) et la ville de l'offre sans son préfixe
département. Sans entreprise résolue, le bloc est absent (critère 15).
"""

from __future__ import annotations

import html as html_lib
import re
from datetime import date

from orchestrator.job_search.pdf.coordonnees import Coordonnees

_DEPT_PREFIX = re.compile(r"^\d+\s*-\s*")
_DEPT_SUFFIX = re.compile(r"\s*\(dept\.?\)\s*$", re.IGNORECASE)


def ville_sans_departement(location: str | None) -> str | None:
    """« 67 - Obernai » → « Obernai » ; « 75 - Paris (Dept.) » → « Paris » ;
    « Bruxelles » inchangé (critère 14). `None`/vide → `None` (critère 15)."""
    if not location:
        return None
    ville = _DEPT_PREFIX.sub("", location.strip())
    ville = _DEPT_SUFFIX.sub("", ville).strip()
    return ville or None


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


_MONTHS_EN = [
    "January",
    "February",
    "March",
    "April",
    "May",
    "June",
    "July",
    "August",
    "September",
    "October",
    "November",
    "December",
]

# EXE-209, H4 : seule Bruxelles se traduit ; toute autre ville reste telle
# qu'elle est écrite dans mes coordonnées.
_VILLES_EN = {"Bruxelles": "Brussels"}


def format_date_en(d: date) -> str:
    """« 2 November 2026 » (EXE-209, H4 : usage britannique)."""
    return f"{d.day} {_MONTHS_EN[d.month - 1]} {d.year}"


def _date_et_objet(ville: str, intitule: str, d: date, langue: str) -> tuple[str, str]:
    if langue == "en":
        ville_en = _VILLES_EN.get(ville.strip(), ville)
        return (
            f"{ville_en}, {format_date_en(d)}",
            f"Subject: Application for the position of {intitule}",
        )
    return (
        f"{ville}, le {format_date_fr(d)}",
        f"Objet : candidature au poste de {intitule}",
    )


def _paragraphs(texte: str) -> list[str]:
    blocs = re.split(r"\n\s*\n", texte)
    return [b.strip("\n") for b in blocs if b.strip()]


def build_lettre_html(
    coordonnees: Coordonnees,
    intitule: str,
    texte: str,
    entreprise: str | None = None,
    location: str | None = None,
    aujourdhui: date | None = None,
    langue: str = "fr",
) -> str:
    """`langue="en"` (EXE-209) : ligne de date et objet en anglais ; le reste
    de la page est le même. Le français ne change pas (critère 12)."""
    d = aujourdhui or date.today()
    date_ligne, objet = _date_et_objet(coordonnees.ville, intitule, d, langue)
    paragraphs_html = "\n".join(
        f"  <p>{html_lib.escape(p)}</p>" for p in _paragraphs(texte)
    )
    nom = html_lib.escape(coordonnees.nom)

    entreprise_bloc = ""
    if entreprise:
        lignes = [html_lib.escape(entreprise)]
        ville = ville_sans_departement(location)
        if ville:
            lignes.append(html_lib.escape(ville))
        lignes_html = "\n      ".join(f"<div>{ligne}</div>" for ligne in lignes)
        entreprise_bloc = f"""
    <div class="entreprise">
      {lignes_html}
    </div>"""

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
  .header {{ display: flex; justify-content: space-between; align-items: flex-start; }}
  .coordonnees div {{ margin: 0; }}
  .entreprise {{ text-align: right; }}
  .entreprise div {{ margin: 0; }}
  .date-line {{ text-align: right; margin: 2em 0 1.5em; }}
  .objet {{ font-weight: bold; margin-bottom: 1.5em; }}
  p {{ margin: 0 0 1em 0; white-space: pre-wrap; }}
  .signature {{ margin-top: 1.5em; text-align: right; }}
</style>
</head>
<body>
  <div class="header">
    <div class="coordonnees">
      <div>{nom}</div>
      <div>{html_lib.escape(coordonnees.mail)}</div>
      <div>{html_lib.escape(coordonnees.telephone)}</div>
      <div>{html_lib.escape(coordonnees.ville)}</div>
    </div>{entreprise_bloc}
  </div>
  <div class="date-line">{html_lib.escape(date_ligne)}</div>
  <div class="objet">{html_lib.escape(objet)}</div>
{paragraphs_html}
  <div class="signature">{nom}</div>
</body>
</html>"""
