"""Routes de l'API lues par ast, et leur accès à la base, sans rien importer.

Une route est un décorateur `@nom.get|post|put|patch|delete("chemin")` posé sur
une fonction de premier niveau d'un fichier de api/, où `nom` est assigné dans
ce fichier à `APIRouter(...)` (avec son `prefix`) ou à `FastAPI(...)`.

L'accès à la base reprend les définitions de `docs/recon/outils/routes_base.py`
(EXE-203) :

- une fonction « touche la base » si son texte contient « .execute( » ;
- depuis la fonction de la route, on suit toute référence à une fonction connue
  de api/ ou de orchestrator/, à travers les imports, transitivement ;
- « base directe » : une fonction de api/ atteinte (la route comprise) touche
  la base ; « délègue » : seules des fonctions de orchestrator/ atteintes la
  touchent ; « les deux » : les deux cas ; « aucune » : aucune ne la touche.
"""

from __future__ import annotations

import ast
from dataclasses import dataclass
from pathlib import Path

RACINES = ("api", "orchestrator")
METHODES = ("get", "post", "put", "patch", "delete")
_FONCTION = (ast.FunctionDef, ast.AsyncFunctionDef)


@dataclass
class Route:
    methode: str
    chemin: str
    fichier: str
    fonction: str
    ligne: int
    base: str

    @property
    def id(self) -> str:
        return f"{self.methode} {self.chemin}"


@dataclass
class _Module:
    chemin: str
    arbre: ast.Module
    texte: str


def _nom_module(rel: str) -> str:
    parts = rel.removesuffix(".py").split("/")
    if parts[-1] == "__init__":
        parts = parts[:-1]
    return ".".join(parts)


def _charger(racine: Path) -> dict[str, _Module]:
    modules = {}
    for dossier in RACINES:
        for p in sorted((racine / dossier).rglob("*.py")):
            if "__pycache__" in p.parts:
                continue
            texte = p.read_text(encoding="utf-8")
            try:
                arbre = ast.parse(texte)
            except SyntaxError:
                continue
            rel = p.relative_to(racine).as_posix()
            modules[_nom_module(rel)] = _Module(rel, arbre, texte)
    return modules


def _absolu(module: str, est_paquet: bool, niveau: int, cible: str | None) -> str:
    if niveau == 0:
        return cible or ""
    base = module.split(".")
    if not est_paquet:
        base = base[:-1]
    if niveau > 1:
        base = base[: len(base) - (niveau - 1)]
    return ".".join(base + ([cible] if cible else []))


def _table_des_noms(module: str, m: _Module) -> dict[str, str]:
    """Nom local → cible qualifiée (module ou module.symbole)."""
    est_paquet = m.chemin.endswith("__init__.py")
    table: dict[str, str] = {}
    for noeud in ast.walk(m.arbre):
        if isinstance(noeud, ast.Import):
            for alias in noeud.names:
                if alias.asname:
                    table[alias.asname] = alias.name
                else:
                    tete = alias.name.split(".")[0]
                    table[tete] = tete
        elif isinstance(noeud, ast.ImportFrom):
            source = _absolu(module, est_paquet, noeud.level, noeud.module)
            for alias in noeud.names:
                table[alias.asname or alias.name] = f"{source}.{alias.name}"
    for noeud in m.arbre.body:
        if isinstance(noeud, _FONCTION):
            table[noeud.name] = f"{module}.{noeud.name}"
    return table


class _Atteinte:
    """Fonctions de premier niveau de api/ et orchestrator/, et qui touche la base."""

    def __init__(self, modules: dict[str, _Module]):
        self.noms = {mod: _table_des_noms(mod, m) for mod, m in modules.items()}
        self.fonctions: dict[str, tuple[str, ast.AST, bool]] = {}
        for mod, m in modules.items():
            for noeud in m.arbre.body:
                if isinstance(noeud, _FONCTION):
                    source = ast.get_source_segment(m.texte, noeud) or ""
                    self.fonctions[f"{mod}.{noeud.name}"] = (
                        mod,
                        noeud,
                        ".execute(" in source,
                    )

    def _resoudre(self, qualifie: str, vus: set[str]) -> str | None:
        if qualifie in self.fonctions:
            return qualifie
        if qualifie in vus:
            return None
        vus.add(qualifie)
        module, _, symbole = qualifie.rpartition(".")
        if symbole in self.noms.get(module, {}):
            return self._resoudre(self.noms[module][symbole], vus)
        return None

    def _references(self, module: str, noeud: ast.AST) -> set[str]:
        table = self.noms[module]
        trouvees = set()
        for sous in ast.walk(noeud):
            qualifie = None
            if isinstance(sous, ast.Name) and isinstance(sous.ctx, ast.Load):
                qualifie = table.get(sous.id)
            elif isinstance(sous, ast.Attribute) and isinstance(sous.value, ast.Name):
                base = table.get(sous.value.id)
                if base:
                    qualifie = f"{base}.{sous.attr}"
            cible = qualifie and self._resoudre(qualifie, set())
            if cible:
                trouvees.add(cible)
        return trouvees

    def acces(self, depart: str) -> str:
        vus: set[str] = set()
        pile = [depart]
        while pile:
            courante = pile.pop()
            if courante in vus:
                continue
            vus.add(courante)
            module, noeud, _ = self.fonctions[courante]
            pile.extend(self._references(module, noeud) - vus)
        api = any(self.fonctions[f][2] for f in vus if f.startswith("api."))
        orch = any(self.fonctions[f][2] for f in vus if f.startswith("orchestrator."))
        if api and orch:
            return "les deux"
        if api:
            return "base directe"
        return "délègue" if orch else "aucune"


def _routeurs(arbre: ast.Module) -> dict[str, str]:
    """Nom assigné à `APIRouter(...)` ou `FastAPI(...)` → préfixe de ses routes."""
    table = {}
    for noeud in arbre.body:
        if not (isinstance(noeud, ast.Assign) and isinstance(noeud.value, ast.Call)):
            continue
        appel = noeud.value
        if getattr(appel.func, "id", None) not in ("APIRouter", "FastAPI"):
            continue
        prefixe = ""
        for mot in appel.keywords:
            if mot.arg == "prefix" and isinstance(mot.value, ast.Constant):
                prefixe = str(mot.value.value)
        for cible in noeud.targets:
            if isinstance(cible, ast.Name):
                table[cible.id] = prefixe
    return table


def _chemin_du_decorateur(deco: ast.Call) -> str | None:
    if deco.args and isinstance(deco.args[0], ast.Constant):
        return str(deco.args[0].value)
    for mot in deco.keywords:
        if mot.arg == "path" and isinstance(mot.value, ast.Constant):
            return str(mot.value.value)
    return None


def _decorateurs_de_route(noeud: ast.AST, routeurs: dict[str, str]):
    for deco in noeud.decorator_list:
        if (
            isinstance(deco, ast.Call)
            and isinstance(deco.func, ast.Attribute)
            and deco.func.attr in METHODES
            and isinstance(deco.func.value, ast.Name)
            and deco.func.value.id in routeurs
        ):
            chemin = _chemin_du_decorateur(deco)
            if chemin is not None:
                yield deco, routeurs[deco.func.value.id] + chemin


def lire_routes(racine: Path) -> list[Route]:
    """Les routes déclarées par les fichiers de api/, avec leur accès à la base."""
    modules = _charger(racine)
    atteinte = _Atteinte(modules)
    routes = []
    for module, m in modules.items():
        if not module.startswith("api"):
            continue
        routeurs = _routeurs(m.arbre)
        for noeud in m.arbre.body:
            if not isinstance(noeud, _FONCTION):
                continue
            for deco, chemin in _decorateurs_de_route(noeud, routeurs):
                routes.append(
                    Route(
                        methode=deco.func.attr.upper(),
                        chemin=chemin,
                        fichier=m.chemin,
                        fonction=noeud.name,
                        ligne=deco.lineno,
                        base=atteinte.acces(f"{module}.{noeud.name}"),
                    )
                )
    return sorted(routes, key=lambda r: (r.chemin, r.methode, r.fichier))
