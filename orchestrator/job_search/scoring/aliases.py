"""
Chargement de alias.yaml et canonicalisation déterministe des technologies.

Transformation à la lecture (scoring), jamais à l'ingestion.
La trace LLM garde le vocabulaire brut. Python pur, 0 LLM (architecture.md §4).
"""
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
        index[canonical_lower] = canonical_lower

        for variant in (variants or []):
            v = str(variant).lower().strip()
            if v in index and index[v] != canonical_lower:
                raise DuplicateAliasError(
                    f"'{v}' est variante de '{index[v]}' ET de '{canonical_lower}'"
                )
            index[v] = canonical_lower

    exclude = frozenset(str(e).lower().strip() for e in exclude_raw)

    return AliasTable(_index=index, _exclude=exclude)


def canonicalize(tech: str, table: AliasTable) -> str | None:
    """
    - variante connue      → forme canonique
    - terme dans exclude    → None (retiré du calcul)
    - inconnu               → tech.lower().strip() inchangé (auto-canonicalisation)
    """
    normalized = tech.lower().strip()
    if normalized in table._exclude:
        return None
    return table._index.get(normalized, normalized)
