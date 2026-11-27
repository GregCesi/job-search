"""Nettoyage des adresses du parcours (EXE-217, H4).

Nom de site en minuscules, pas de fragment, pas de barre finale, paramètres de
suivi retirés. La liste des paramètres de suivi vit dans profiles/a_postuler.yaml
(section `parcours`) : aucun nom de paramètre n'est écrit ici.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import yaml


@dataclass(frozen=True)
class Suivi:
    """Paramètres de suivi : ceux qui commencent par un préfixe, et ceux nommés."""

    prefixes: tuple[str, ...]
    noms: frozenset[str]

    def est_de_suivi(self, parametre: str) -> bool:
        bas = parametre.casefold()
        return bas in self.noms or any(bas.startswith(p) for p in self.prefixes)


def charger_suivi(chemin: str | Path) -> Suivi:
    """Lève OSError si le fichier est illisible, yaml.YAMLError s'il est mal formé."""
    data = yaml.safe_load(Path(chemin).read_text(encoding="utf-8")) or {}
    suivi = (data.get("parcours") or {}).get("parametres_suivi") or {}
    return Suivi(
        prefixes=tuple(p.casefold() for p in suivi.get("prefixes") or []),
        noms=frozenset(n.casefold() for n in suivi.get("noms") or []),
    )


def nettoyer(adresse: str, suivi: Suivi) -> str:
    parts = urlsplit(adresse.strip())
    requete = [
        (cle, valeur)
        for cle, valeur in parse_qsl(parts.query, keep_blank_values=True)
        if not suivi.est_de_suivi(cle)
    ]
    chemin = parts.path.rstrip("/")
    return urlunsplit(
        (parts.scheme.lower(), parts.netloc.lower(), chemin, urlencode(requete), "")
    )


def site(adresse: str) -> str:
    return urlsplit(adresse).netloc.lower()


def est_accueil(adresse: str) -> bool:
    return urlsplit(adresse).path in ("", "/")
