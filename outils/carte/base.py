"""La base vue depuis le code : tables créées, tables lues et écrites par
fichier, couche du fichier et appels directs à la base. Rien n'ouvre la base.

- Une table est un nom qui suit `CREATE TABLE` dans une chaîne du code.
- Lecture ou écriture se décide sur le mot SQL qui précède le nom d'une table
  créée : `FROM`, `JOIN` lisent ; `INSERT INTO`, `INSERT OR ... INTO`,
  `UPDATE`, `DELETE FROM`, `CREATE TABLE`, `ALTER TABLE` écrivent. Seules les
  chaînes du code sont lues, docstrings exclues.
- Une chaîne construite dont un de ces mots est suivi d'une valeur calculée à
  l'exécution est une « table illisible ».
- Un appel direct est une occurrence de « .execute( », comptée comme
  `scripts/cliquet.py` la compte ; un fichier de stockage suit sa règle
  `est_stockage`, reprise ici telle quelle.
"""

from __future__ import annotations

import ast
import re
from dataclasses import dataclass, field

EXECUTE = re.compile(r"\.execute\(")
_CREATION = re.compile(r"\bCREATE\s+TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?[\"'`\[]?(\w+)")
_ACCES = re.compile(
    r"\b(DELETE\s+FROM|FROM|JOIN|INSERT\s+(?:OR\s+\w+\s+)?INTO|UPDATE"
    r"|CREATE\s+TABLE(?:\s+IF\s+NOT\s+EXISTS)?|ALTER\s+TABLE)\s+[\"'`\[]?(\w+)"
)
_MOT_AVANT_VALEUR = re.compile(r"\b(FROM|JOIN|INTO|UPDATE|TABLE)\s*[\"'`\[]?$")
_LECTURES = ("FROM", "JOIN")


def est_stockage(rel: str) -> bool:
    """Règle de `scripts/cliquet.py` : un fichier sous un dossier storage/ ou
    stockage/, ou nommé storage.py ou stockage.py."""
    parts = rel.split("/")
    return (
        "storage" in parts[:-1]
        or "stockage" in parts[:-1]
        or parts[-1] in ("storage.py", "stockage.py")
    )


def appels_directs(texte: str) -> int:
    return len(EXECUTE.findall(texte))


@dataclass
class AccesTables:
    lues: set[str] = field(default_factory=set)
    ecrites: set[str] = field(default_factory=set)
    illisibles: list[int] = field(default_factory=list)


def _docstrings(arbre: ast.Module) -> set[int]:
    ids = set()
    for noeud in ast.walk(arbre):
        if isinstance(
            noeud, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)
        ):
            corps = noeud.body
            if (
                corps
                and isinstance(corps[0], ast.Expr)
                and isinstance(corps[0].value, ast.Constant)
                and isinstance(corps[0].value.value, str)
            ):
                ids.add(id(corps[0].value))
    return ids


def _chaines(arbre: ast.Module) -> list[str]:
    exclues = _docstrings(arbre)
    return [
        n.value
        for n in ast.walk(arbre)
        if isinstance(n, ast.Constant)
        and isinstance(n.value, str)
        and id(n) not in exclues
    ]


def tables_creees(arbre: ast.Module) -> set[str]:
    noms: set[str] = set()
    for chaine in _chaines(arbre):
        noms.update(_CREATION.findall(chaine))
    return noms


def _construite_illisible(noeud: ast.AST) -> bool:
    """Un mot SQL suivi d'une valeur calculée : f-chaîne ou concaténation."""
    if isinstance(noeud, ast.JoinedStr):
        for avant, apres in zip(noeud.values, noeud.values[1:]):
            if (
                isinstance(avant, ast.Constant)
                and isinstance(apres, ast.FormattedValue)
                and _MOT_AVANT_VALEUR.search(str(avant.value))
            ):
                return True
    if isinstance(noeud, ast.BinOp) and isinstance(noeud.op, ast.Add):
        gauche, droite = noeud.left, noeud.right
        return (
            isinstance(gauche, ast.Constant)
            and isinstance(gauche.value, str)
            and not isinstance(droite, ast.Constant)
            and bool(_MOT_AVANT_VALEUR.search(gauche.value))
        )
    return False


def acces_tables(arbre: ast.Module, tables: set[str]) -> AccesTables:
    acces = AccesTables()
    for chaine in _chaines(arbre):
        for mot, nom in _ACCES.findall(chaine):
            if nom not in tables:
                continue
            if mot in _LECTURES:
                acces.lues.add(nom)
            else:
                acces.ecrites.add(nom)
    acces.illisibles = sorted(
        {n.lineno for n in ast.walk(arbre) if _construite_illisible(n)}
    )
    return acces
