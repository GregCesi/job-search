"""Coordonnées du candidat pour les PDF CV/lettre (EXE-102, H4 du ticket).

Fichier hors git `data/lettre/coordonnees.txt`, quatre lignes « clé : valeur »
(nom, mail, telephone, ville). Absent → refus nommant le fichier (critère 15),
jamais de valeur de repli : le prénom et le nom du fichier PDF en dépendent.
"""

from __future__ import annotations

from dataclasses import dataclass

from orchestrator.job_search.paths import COORDONNEES_PATH

_CLES = ("nom", "mail", "telephone", "ville")


class CoordonneesManquantesError(Exception):
    def __init__(self, path) -> None:
        super().__init__(f"Fichier de coordonnées absent : {path}")
        self.path = path


@dataclass(frozen=True)
class Coordonnees:
    nom: str
    mail: str
    telephone: str
    ville: str

    @property
    def prenom(self) -> str:
        parts = self.nom.split()
        return parts[0] if parts else ""

    @property
    def nom_de_famille(self) -> str:
        parts = self.nom.split()
        return " ".join(parts[1:]) if len(parts) > 1 else ""


def _parse(text: str) -> dict[str, str]:
    values: dict[str, str] = {}
    for line in text.splitlines():
        cle, sep, valeur = line.partition(":")
        if not sep:
            continue
        cle = cle.strip().lower()
        if cle in _CLES:
            values[cle] = valeur.strip()
    return values


def load_coordonnees() -> Coordonnees:
    """Lit `COORDONNEES_PATH` (module global, monkeypatché dans les tests —
    même convention que `cv_service.CV_REFERENCE_PATH`)."""
    if not COORDONNEES_PATH.exists():
        raise CoordonneesManquantesError(COORDONNEES_PATH)
    values = _parse(COORDONNEES_PATH.read_text(encoding="utf-8"))
    return Coordonnees(
        nom=values.get("nom", ""),
        mail=values.get("mail", ""),
        telephone=values.get("telephone", ""),
        ville=values.get("ville", ""),
    )
