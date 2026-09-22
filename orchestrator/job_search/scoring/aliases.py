"""
Chargement de alias.yaml et canonicalisation déterministe des technologies.

Transformation à la lecture (scoring), jamais à l'ingestion.
La trace LLM garde le vocabulaire brut. Python pur, 0 LLM (architecture.md §4).
"""
import re
from dataclasses import dataclass, field
from pathlib import Path

import yaml


class DuplicateAliasError(Exception):
    """Une variante est déclarée sous deux formes canoniques différentes."""


@dataclass(frozen=True)
class AliasTable:
    """Index inverse variante→canonique + set d'exclusions."""
    _index: dict[str, str] = field(default_factory=dict)    # variante.lower() → canonique
    _exclude: frozenset[str] = field(default_factory=frozenset)  # termes exclus du calcul


def _key(term: str) -> str:
    """Clé de rapprochement : minuscules, espaces / _ / - fusionnés en un espace (TCK-211).

    `vector_databases`, `vector-databases` et `vector databases` donnent la même clé.
    Les autres caractères (`/`, `+`, `#`, `.`) sont conservés : ci/cd, c++, c#, .net.
    """
    return re.sub(r"[\s_\-]+", " ", str(term).lower().strip()).strip()


def _register(index: dict[str, str], variant: str, canonical: str) -> None:
    """Indexe la variante brute et sa clé normalisée ; lève si elles pointent ailleurs."""
    for k in {str(variant).lower().strip(), _key(variant)}:
        if k in index and index[k] != canonical:
            raise DuplicateAliasError(
                f"'{k}' est variante de '{index[k]}' ET de '{canonical}'"
            )
        index[k] = canonical


def load_alias_table(path: str | Path) -> AliasTable:
    """Charge alias.yaml, construit l'index inverse, détecte les doublons."""
    data = yaml.safe_load(Path(path).read_text(encoding="utf-8"))

    aliases_raw: dict[str, list[str]] = data.get("aliases", {})
    exclude_raw: list[str] = data.get("exclude", [])

    index: dict[str, str] = {}

    for canonical, variants in aliases_raw.items():
        canonical_lower = str(canonical).lower().strip()
        # La forme canonique se mappe aussi à elle-même
        if canonical_lower in index and index[canonical_lower] != canonical_lower:
            raise DuplicateAliasError(
                f"'{canonical_lower}' est déjà variante de '{index[canonical_lower]}', "
                f"ne peut pas être aussi forme canonique"
            )
        _register(index, canonical_lower, canonical_lower)

        for variant in (variants or []):
            _register(index, variant, canonical_lower)

    exclude = frozenset(_key(e) for e in exclude_raw)

    return AliasTable(_index=index, _exclude=exclude)


def canonicalize(tech: str, table: AliasTable) -> str | None:
    """
    - variante connue      → forme canonique (écriture brute ou clé normalisée)
    - terme dans exclude    → None (retiré du calcul)
    - inconnu               → clé normalisée (auto-canonicalisation : les écritures
                              `vector_databases` / `vector databases` convergent)
    """
    raw = tech.lower().strip()
    key = _key(tech)
    if key in table._exclude:
        return None
    return table._index.get(raw) or table._index.get(key) or key
