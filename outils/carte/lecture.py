"""Lecture du disque pour la carte : fichiers Python, docstrings et textes.

Tout se lit sans exécuter : les docstrings sortent de l'arbre syntaxique
(`ast`), jamais d'un import. Le fichier de textes est du TOML écrit à la main.
"""

from __future__ import annotations

import ast
import re
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

DOSSIERS_CARTE = ("api", "orchestrator")

# Mots abrégés après lesquels un point ne ferme pas la phrase.
_ABREVIATIONS = {"cf.", "ex.", "p.", "etc.", "env.", "resp.", "vs.", "c.-à-d."}
_FIN_DE_PHRASE = re.compile(r"[.!?…](?=\s|$)")


class ErreurTextes(Exception):
    """Le fichier de textes contredit le disque : la commande rend 1."""


@dataclass
class Fichier:
    chemin: str
    module: str
    lignes: int
    phrase_docstring: str | None


@dataclass
class Systeme:
    id: str
    nom: str
    role: str
    fichiers: list[str] = field(default_factory=list)


@dataclass
class Textes:
    systemes: list[Systeme]
    phrases: dict[str, str]


def _est_init_vide(texte: str) -> bool:
    return not any(
        ligne.strip() and not ligne.strip().startswith("#")
        for ligne in texte.splitlines()
    )


def module_de(chemin: str) -> str:
    """`api/cv.py` → `api.cv` ; `a/b/__init__.py` → `a.b`."""
    parties = chemin.removesuffix(".py").split("/")
    if parties[-1] == "__init__":
        parties = parties[:-1]
    return ".".join(parties)


def premiere_phrase(docstring: str | None) -> str | None:
    """Première phrase du premier paragraphe d'une docstring, espaces ramenés à un."""
    if not docstring or not docstring.strip():
        return None
    paragraphe = " ".join(docstring.strip().split("\n\n")[0].split())
    for fin in _FIN_DE_PHRASE.finditer(paragraphe):
        dernier_mot = paragraphe[: fin.end()].rsplit(" ", 1)[-1]
        if dernier_mot.lower() in _ABREVIATIONS:
            continue
        return paragraphe[: fin.end()]
    return paragraphe


def _docstring(texte: str) -> str | None:
    try:
        return ast.get_docstring(ast.parse(texte))
    except SyntaxError:
        return None


def fichiers_de_la_carte(racine: Path) -> list[Fichier]:
    """Fichiers Python de api/ et orchestrator/, sauf les `__init__.py` qui n'ont
    aucune ligne autre que vide ou commentaire."""
    trouves: list[Fichier] = []
    for dossier in DOSSIERS_CARTE:
        for p in sorted((racine / dossier).rglob("*.py")):
            if "__pycache__" in p.parts or not p.is_file():
                continue
            texte = p.read_text(encoding="utf-8")
            if p.name == "__init__.py" and _est_init_vide(texte):
                continue
            chemin = p.relative_to(racine).as_posix()
            trouves.append(
                Fichier(
                    chemin=chemin,
                    module=module_de(chemin),
                    lignes=len(texte.splitlines()),
                    phrase_docstring=premiere_phrase(_docstring(texte)),
                )
            )
    return trouves


def charger_textes(chemin: Path) -> Textes:
    if not chemin.is_file():
        raise ErreurTextes(f"fichier de textes introuvable : {chemin}")
    try:
        brut = tomllib.loads(chemin.read_text(encoding="utf-8"))
    except tomllib.TOMLDecodeError as exc:
        raise ErreurTextes(f"fichier de textes illisible : {chemin} ({exc})") from exc
    systemes = [
        Systeme(
            id=str(s["id"]),
            nom=str(s["nom"]),
            role=str(s.get("role", "")),
            fichiers=[str(f) for f in s.get("fichiers", [])],
        )
        for s in brut.get("systeme", [])
    ]
    phrases = {str(k): str(v) for k, v in brut.get("phrases", {}).items()}
    return Textes(systemes=systemes, phrases=phrases)


def verifier_textes(textes: Textes, racine: Path) -> list[str]:
    """Erreurs du fichier de textes contre le disque : fichier cité absent,
    fichier rangé dans deux systèmes."""
    erreurs: list[str] = []
    cites = [f for s in textes.systemes for f in s.fichiers] + list(textes.phrases)
    for chemin in dict.fromkeys(cites):
        if not (racine / chemin).is_file():
            erreurs.append(
                f"fichier cité par le fichier de textes introuvable : {chemin}"
            )
    rangement: dict[str, list[str]] = {}
    for s in textes.systemes:
        for chemin in s.fichiers:
            rangement.setdefault(chemin, []).append(s.nom)
    for chemin, noms in rangement.items():
        if len(noms) > 1:
            erreurs.append(
                f"fichier rangé dans plusieurs systèmes : {chemin} ({', '.join(noms)})"
            )
    return erreurs
