"""Classe chaque route déclarée sous api/ selon son accès à la base (EXE-203, mesure 14).

Lecture statique par ast, sans rien importer ni exécuter du dépôt.

- Une fonction « touche la base » si son texte contient « .execute( ».
- Depuis la fonction de la route, on suit toute référence à une fonction connue
  de api/ ou de orchestrator/ (appel, ou fonction passée en argument), à travers
  les imports de module et les imports locaux, transitivement.
- « base directe » : une fonction de api/ atteinte (la route comprise) touche la base.
- « délègue » : seules des fonctions de orchestrator/ atteintes touchent la base.
- « les deux » : les deux cas.
- « aucune » : aucune fonction atteinte ne touche la base.

Usage, depuis la racine du dépôt : python docs/recon/outils/routes_base.py
"""

import ast
from collections import Counter
from pathlib import Path

RACINES = ("api", "orchestrator")
METHODES = {"get", "post", "put", "patch", "delete"}


def nom_module(chemin: Path) -> str:
    parts = list(chemin.with_suffix("").parts)
    if parts[-1] == "__init__":
        parts = parts[:-1]
    return ".".join(parts)


def charger() -> dict[str, tuple[Path, ast.Module, str]]:
    modules = {}
    for racine in RACINES:
        for chemin in sorted(Path(racine).rglob("*.py")):
            texte = chemin.read_text(encoding="utf-8")
            modules[nom_module(chemin)] = (chemin, ast.parse(texte), texte)
    return modules


def absolu(module: str, est_paquet: bool, niveau: int, cible: str | None) -> str:
    if niveau == 0:
        return cible or ""
    base = module.split(".")
    if not est_paquet:
        base = base[:-1]
    if niveau > 1:
        base = base[: len(base) - (niveau - 1)]
    return ".".join(base + ([cible] if cible else []))


def espaces(modules):
    """Pour chaque module : nom local -> cible qualifiée (module ou module.symbole)."""
    noms = {}
    for module, (chemin, arbre, _) in modules.items():
        est_paquet = chemin.name == "__init__.py"
        table = {}
        for noeud in ast.walk(arbre):
            if isinstance(noeud, ast.Import):
                for alias in noeud.names:
                    if alias.asname:
                        table[alias.asname] = alias.name
                    else:
                        table[alias.name.split(".")[0]] = alias.name.split(".")[0]
            elif isinstance(noeud, ast.ImportFrom):
                source = absolu(module, est_paquet, noeud.level, noeud.module)
                for alias in noeud.names:
                    table[alias.asname or alias.name] = f"{source}.{alias.name}"
            elif isinstance(noeud, (ast.FunctionDef, ast.AsyncFunctionDef)):
                if noeud in arbre.body:
                    table[noeud.name] = f"{module}.{noeud.name}"
        for noeud in arbre.body:
            if isinstance(noeud, (ast.FunctionDef, ast.AsyncFunctionDef)):
                table[noeud.name] = f"{module}.{noeud.name}"
        noms[module] = table
    return noms


def fonctions(modules):
    """Fonctions de premier niveau : nom qualifié -> (module, noeud, touche la base)."""
    table = {}
    for module, (_, arbre, texte) in modules.items():
        for noeud in arbre.body:
            if isinstance(noeud, (ast.FunctionDef, ast.AsyncFunctionDef)):
                source = ast.get_source_segment(texte, noeud) or ""
                table[f"{module}.{noeud.name}"] = (module, noeud, ".execute(" in source)
    return table


def resoudre(qualifie, modules, noms, fns, vus=None):
    """Suit les réexports jusqu'à une fonction connue, ou None."""
    vus = vus or set()
    if qualifie in fns:
        return qualifie
    if qualifie in vus:
        return None
    vus.add(qualifie)
    module, _, symbole = qualifie.rpartition(".")
    if module in noms and symbole in noms[module]:
        return resoudre(noms[module][symbole], modules, noms, fns, vus)
    return None


def references(module, noeud, modules, noms, fns):
    table = noms[module]
    trouvees = set()
    for sous in ast.walk(noeud):
        qualifie = None
        if isinstance(sous, ast.Name) and isinstance(sous.ctx, ast.Load):
            qualifie = table.get(sous.id)
        elif isinstance(sous, ast.Attribute) and isinstance(sous.value, ast.Name):
            base = table.get(sous.value.id)
            if base:
                qualifie = f"{base}.{sous.attr}"
        if qualifie:
            cible = resoudre(qualifie, modules, noms, fns)
            if cible:
                trouvees.add(cible)
    return trouvees


def atteintes(depart, modules, noms, fns):
    vus, pile = set(), [depart]
    while pile:
        courante = pile.pop()
        if courante in vus:
            continue
        vus.add(courante)
        module, noeud, _ = fns[courante]
        pile.extend(references(module, noeud, modules, noms, fns) - vus)
    return vus


def prefixes(arbre):
    table = {}
    for noeud in arbre.body:
        if isinstance(noeud, ast.Assign) and isinstance(noeud.value, ast.Call):
            appel = noeud.value
            if getattr(appel.func, "id", None) == "APIRouter":
                prefixe = ""
                for mot in appel.keywords:
                    if mot.arg == "prefix" and isinstance(mot.value, ast.Constant):
                        prefixe = mot.value.value
                for cible in noeud.targets:
                    if isinstance(cible, ast.Name):
                        table[cible.id] = prefixe
    return table


def main():
    modules = charger()
    noms = espaces(modules)
    fns = fonctions(modules)
    lignes, compte = [], Counter()
    for module, (chemin, arbre, _) in modules.items():
        if not module.startswith("api"):
            continue
        pref = prefixes(arbre)
        for noeud in arbre.body:
            if not isinstance(noeud, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            for deco in noeud.decorator_list:
                if not (
                    isinstance(deco, ast.Call)
                    and isinstance(deco.func, ast.Attribute)
                    and deco.func.attr in METHODES
                    and isinstance(deco.func.value, ast.Name)
                    and deco.func.value.id in {"router", "app"}
                ):
                    continue
                chemin_route = deco.args[0].value if deco.args else ""
                prefixe = pref.get(deco.func.value.id, "")
                reach = atteintes(f"{module}.{noeud.name}", modules, noms, fns)
                api_base = any(fns[f][2] for f in reach if f.startswith("api"))
                orch_base = any(
                    fns[f][2] for f in reach if f.startswith("orchestrator")
                )
                if api_base and orch_base:
                    valeur = "les deux"
                elif api_base:
                    valeur = "base directe"
                elif orch_base:
                    valeur = "délègue"
                else:
                    valeur = "aucune"
                compte[valeur] += 1
                lignes.append(
                    f"{deco.func.attr.upper()} {prefixe}{chemin_route} | "
                    f"{chemin}:{deco.lineno} | {valeur}"
                )
    for ligne in lignes:
        print(ligne)
    print()
    print(f"routes : {len(lignes)}")
    for valeur in ("base directe", "délègue", "les deux", "aucune"):
        print(f"{valeur} : {compte[valeur]}")


if __name__ == "__main__":
    main()
