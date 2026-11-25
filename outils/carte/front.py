"""Lecture du front (web/app/) pour la carte, par simple recherche de texte :
rien n'est compilé, importé ni lancé.

- Un appel est `$fetch(...)`, `$fetch.raw(...)` ou `fetch(...)`. Son adresse
  est le premier argument ; sa méthode, celle écrite dans l'appel
  (`method: 'PUT'`), GET sinon.
- L'adresse se lit quand elle commence par la base de l'API
  (`config.public.apiBase`), écrite telle quelle ou par un nom posé dans le même
  fichier (`const base = ...`, `const cvUrl = () => ...`, `function mailUrl()
  { return ... }`). Sinon elle est
  illisible. Le chemin s'arrête au `?` ; une variable du gabarit occupe un
  segment entier.
- Un store est un import de valeur depuis le dossier stores (`import type`
  n'importe qu'un type) ; un composant est utilisé par sa balise dans le
  `<template>`, sous son nom Nuxt ou en kebab-case.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

DOSSIER_FRONT = "web/app"
EXTENSIONS = (".vue", ".ts")
BASES = ("config.public.apiBase", "useRuntimeConfig().public.apiBase")
VARIABLE = "{}"

_DEBUT_APPEL = re.compile(r"(?<![\w.$])\$?fetch(?:\.raw)?\s*")
_DEFINITION = re.compile(
    r"(?:const|let|var)\s+([A-Za-z_$][\w$]*)\s*(?::[^=\n]+)?=\s*(?:\(\)\s*=>\s*)?"
)
_FONCTION_RETOUR = re.compile(
    r"function\s+([A-Za-z_$][\w$]*)\s*\(\s*\)\s*(?::[^{\n]+)?\{\s*return\s+"
)
_NOM = re.compile(r"([A-Za-z_$][\w$]*)(?:\(\))?")
_METHODE = re.compile(r"\bmethod\s*:\s*['\"]([A-Za-z]+)['\"]")
_IMPORT = re.compile(r"\bimport\s+(?!type\s)([^;]*?)\s+from\s+['\"]([^'\"]+)['\"]")
_PAIRES = {"(": ")", "[": "]", "{": "}"}


@dataclass
class Appel:
    ligne: int
    methode: str
    adresse: str
    segments: list[str] | None


@dataclass
class FichierFront:
    chemin: str
    lignes: int
    appels: list[Appel] = field(default_factory=list)
    stores: list[str] = field(default_factory=list)
    composants: list[str] = field(default_factory=list)


# ── Balayage du texte : chaînes, gabarits et groupes parenthésés ──────────────


def _fin_chaine(t: str, i: int) -> int:
    """t[i] ouvre une chaîne (' " `) : indice qui suit sa fermeture."""
    q, i = t[i], i + 1
    while i < len(t):
        c = t[i]
        if c == "\\":
            i += 2
            continue
        if c == q:
            return i + 1
        if q == "`" and t.startswith("${", i):
            i = _fin_groupe(t, i + 1)
            continue
        i += 1
    return len(t)


def _fin_groupe(t: str, i: int) -> int:
    """t[i] ouvre ( [ ou { : indice qui suit le fermant correspondant."""
    pile: list[str] = []
    while i < len(t):
        c = t[i]
        if c in "'\"`":
            i = _fin_chaine(t, i)
            continue
        if c in _PAIRES:
            pile.append(_PAIRES[c])
        elif pile and c == pile[-1]:
            pile.pop()
            if not pile:
                return i + 1
        i += 1
    return len(t)


def _decouper(t: str, sep: str) -> list[str]:
    """Découpe t sur `sep` hors chaînes et hors groupes."""
    morceaux, debut, i = [], 0, 0
    while i < len(t):
        c = t[i]
        if c in "'\"`":
            i = _fin_chaine(t, i)
            continue
        if c in _PAIRES:
            i = _fin_groupe(t, i)
            continue
        if c == sep:
            morceaux.append(t[debut:i])
            debut = i + 1
        i += 1
    morceaux.append(t[debut:])
    return [m.strip() for m in morceaux]


def _fin_expression(t: str, i: int) -> int:
    """Fin d'une expression d'affectation : fin de ligne ou `;` hors groupes."""
    while i < len(t):
        c = t[i]
        if c in "'\"`":
            i = _fin_chaine(t, i)
            continue
        if c in _PAIRES:
            i = _fin_groupe(t, i)
            continue
        if c in "\n;":
            return i
        i += 1
    return i


def _apres_generique(t: str, i: int) -> int:
    """Saute un paramètre de type `<...>` qui commence en t[i], s'il y en a un."""
    if i >= len(t) or t[i] != "<":
        return i
    profondeur = 0
    while i < len(t):
        c = t[i]
        if c in "'\"`":
            i = _fin_chaine(t, i)
            continue
        if c == "<":
            profondeur += 1
        elif c == ">" and t[i - 1] != "=":
            profondeur -= 1
            if profondeur == 0:
                return i + 1
        i += 1
    return i


# ── Adresses ─────────────────────────────────────────────────────────────────


def _definitions(texte: str) -> dict[str, list[str]]:
    """Nom → valeurs posées dans le fichier : `const x = v`, `const x = () => v`
    et `function x() { return v }`."""
    defs: dict[str, list[str]] = {}
    for motif in (_DEFINITION, _FONCTION_RETOUR):
        for m in motif.finditer(texte):
            valeur = texte[m.end() : _fin_expression(texte, m.end())].strip()
            if valeur:
                defs.setdefault(m.group(1), []).append(valeur)
    return defs


def _gabarit(interieur: str) -> list[tuple[str, str]]:
    morceaux, i, debut = [], 0, 0
    while i < len(interieur):
        if interieur.startswith("${", i):
            if i > debut:
                morceaux.append(("t", interieur[debut:i]))
            fin = _fin_groupe(interieur, i + 1)
            morceaux.append(("e", interieur[i + 2 : fin - 1].strip()))
            i = debut = fin
            continue
        if interieur[i] == "\\":
            i += 2
            continue
        i += 1
    if debut < len(interieur):
        morceaux.append(("t", interieur[debut:]))
    return morceaux


def _morceaux(expr: str, defs: dict[str, list[str]], prof: int = 0):
    """L'adresse en morceaux : ("t", texte), ("e", expression) ou ("base", "")."""
    if prof > 6:
        return [("e", expr)]
    res: list[tuple[str, str]] = []
    for part in _decouper(expr, "+"):
        if part[:1] in ("'", '"', "`") and _fin_chaine(part, 0) == len(part):
            brut = part[1:-1]
            res.extend(_gabarit(brut) if part[0] == "`" else [("t", brut)])
        else:
            res.append(("e", part))
    sortie: list[tuple[str, str]] = []
    for genre, valeur in res:
        nom = _NOM.fullmatch(valeur) if genre == "e" else None
        if genre == "e" and valeur in BASES:
            sortie.append(("base", ""))
        elif nom and len(defs.get(nom.group(1), [])) == 1:
            sortie.extend(_morceaux(defs[nom.group(1)][0], defs, prof + 1))
        else:
            sortie.append((genre, valeur))
    return sortie


def _segments(morceaux: list[tuple[str, str]]) -> list[str] | None:
    if not morceaux or morceaux[0][0] != "base":
        return None
    chemin = ""
    for genre, valeur in morceaux[1:]:
        if genre == "base":
            return None
        if genre == "t" and "?" in valeur:
            chemin += valeur.split("?", 1)[0]
            break
        chemin += valeur if genre == "t" else "\x00"
    if not chemin.startswith("/"):
        return None
    segments = []
    for seg in chemin.strip("/").split("/"):
        if seg == "\x00":
            segments.append(VARIABLE)
        elif "\x00" in seg or "{" in seg or not seg:
            return None
        else:
            segments.append(seg)
    return segments


def _appels(texte: str) -> list[Appel]:
    defs = _definitions(texte)
    appels = []
    for m in _DEBUT_APPEL.finditer(texte):
        i = _apres_generique(texte, m.end())
        if i >= len(texte) or texte[i] != "(":
            continue
        arguments = _decouper(texte[i + 1 : _fin_groupe(texte, i) - 1], ",")
        if not arguments or not arguments[0]:
            continue
        options = arguments[1] if len(arguments) > 1 else ""
        methode = _METHODE.search(options)
        segments = _segments(_morceaux(arguments[0], defs))
        if "method" in options and not methode:
            segments = None
        appels.append(
            Appel(
                ligne=texte.count("\n", 0, m.start()) + 1,
                methode=methode.group(1).upper() if methode else "GET",
                adresse=" ".join(arguments[0].split()),
                segments=segments,
            )
        )
    return appels


# ── Stores et composants ─────────────────────────────────────────────────────


def _nom_composant(rel_composant: str) -> str:
    parties = rel_composant.removesuffix(".vue").split("/")
    return "".join(p[:1].upper() + p[1:] for p in parties)


def _kebab(nom: str) -> str:
    return re.sub(r"(?<=[a-z0-9])(?=[A-Z])|(?<=[A-Z])(?=[A-Z][a-z])", "-", nom).lower()


def _template(texte: str) -> str:
    debut, fin = texte.find("<template"), texte.rfind("</template>")
    return texte[debut:fin] if 0 <= debut < fin else ""


def _stores(texte: str, racine: Path) -> list[str]:
    trouves = set()
    for _, source in _IMPORT.findall(texte):
        m = re.search(r"(?:^|/)stores/([\w.-]+)$", source)
        if not m:
            continue
        nom = m.group(1).removesuffix(".ts")
        rel = f"{DOSSIER_FRONT}/stores/{nom}.ts"
        if (racine / rel).is_file():
            trouves.add(rel)
    return sorted(trouves)


def _composants(texte: str, chemin: str, composants: dict[str, str]) -> list[str]:
    gabarit = _template(texte)
    trouves = set()
    for nom, rel in composants.items():
        if rel == chemin:
            continue
        motif = rf"<(?:Lazy)?(?:{re.escape(nom)}|{re.escape(_kebab(nom))})(?=[\s/>])"
        if re.search(motif, gabarit):
            trouves.add(rel)
    return sorted(trouves)


def fichiers_front(racine: Path) -> list[Path]:
    dossier = racine / DOSSIER_FRONT
    if not dossier.is_dir():
        return []
    trouves = []
    for p in sorted(dossier.rglob("*")):
        parts = p.relative_to(racine).parts
        if p.suffix not in EXTENSIONS or not p.is_file():
            continue
        if "node_modules" in parts or ".nuxt" in parts or ".output" in parts:
            continue
        trouves.append(p)
    return trouves


def lire_front(racine: Path) -> list[FichierFront]:
    chemins = fichiers_front(racine)
    dossier_composants = racine / DOSSIER_FRONT / "components"
    composants = {
        _nom_composant(p.relative_to(dossier_composants).as_posix()): (
            p.relative_to(racine).as_posix()
        )
        for p in chemins
        if p.suffix == ".vue" and dossier_composants in p.parents
    }
    lus = []
    for p in chemins:
        texte = p.read_text(encoding="utf-8")
        rel = p.relative_to(racine).as_posix()
        lus.append(
            FichierFront(
                chemin=rel,
                lignes=len(texte.splitlines()),
                appels=_appels(texte),
                stores=[s for s in _stores(texte, racine) if s != rel],
                composants=_composants(texte, rel, composants)
                if p.suffix == ".vue"
                else [],
            )
        )
    return lus


def segments_de_route(chemin: str) -> list[str]:
    """`/offers/{offer_id}/cv` → ["offers", "{}", "cv"]."""
    return [
        VARIABLE if s.startswith("{") and s.endswith("}") else s
        for s in chemin.strip("/").split("/")
    ]
