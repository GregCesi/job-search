"""Liste des intermédiaires connus (`profiles/intermediaires.yaml`) — lecture + ajout.

Source unique de la normalisation et de l'écriture : `cascade.py` (lecture) et l'écran fiche
(ajout, via `api/fiche.py`) passent tous les deux par ce module.
"""

from ruamel.yaml import YAML

from orchestrator.job_search.paths import INTERMEDIAIRES_PATH

_yaml = YAML()
_yaml.preserve_quotes = True
_yaml.indent(
    mapping=2, sequence=4, offset=2
)  # items indentés à 2 (comme le fichier d'origine)


def normalize(name: str) -> str:
    """Comparaison insensible à la casse et aux espaces de bord — même règle que `cascade.py`."""
    return name.strip().lower()


def load_normalized() -> set[str]:
    data = _yaml.load(INTERMEDIAIRES_PATH.read_text(encoding="utf-8")) or {}
    return {normalize(str(n)) for n in data.get("intermediaires") or []}


def is_known(company: str) -> bool:
    company = (company or "").strip()
    return bool(company) and normalize(company) in load_normalized()


def add(company: str) -> bool:
    """Ajoute `company` à `intermediaires:` si absent. Round-trip ruamel : commentaires préservés.
    Retourne True si une écriture a eu lieu, False si le nom était déjà présent (idempotent)."""
    company = company.strip()
    data = _yaml.load(INTERMEDIAIRES_PATH.read_text(encoding="utf-8")) or {}
    existing = data.setdefault("intermediaires", [])
    if any(normalize(str(n)) == normalize(company) for n in existing):
        return False
    existing.append(company)
    with INTERMEDIAIRES_PATH.open("w", encoding="utf-8") as f:
        _yaml.dump(data, f)
    return True
