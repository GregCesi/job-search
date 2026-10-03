"""Comparaison offre par offre et agrégats du rejeu (TCK-221, EXE-107).

Fonctions pures, testables sans Ollama ni base : canonicalisation des
technos comme au scoring (architecture.md §4), catégorie recalculée en
Python pur sur le profil courant. Importance des technos et langues
exigées ne sont pas scorées ici (H4 du ticket).
"""

from __future__ import annotations

from dataclasses import dataclass, field

from orchestrator.job_search.matching.profile import Profile
from orchestrator.job_search.scoring.aliases import AliasTable, canonicalize
from orchestrator.job_search.scoring.attainability import compute_attainability
from orchestrator.job_search.scoring.categorize import Category, categorize
from orchestrator.job_search.scoring.desirability import compute_desirability
from orchestrator.job_search.sources.base import ExtractedFacts

_TRI_CATEGORIES = {Category.parfait, Category.reve}


def canonical_tech_names(facts: ExtractedFacts, table: AliasTable) -> set[str]:
    names = {canonicalize(t.name, table) for t in facts.techs_required}
    names.discard(None)
    return names  # type: ignore[return-value]


def compare_techs(
    extracted: ExtractedFacts, expected: ExtractedFacts, table: AliasTable
) -> tuple[list[str], list[str], list[str]]:
    """Technos trouvées (intersection), manquées (attendues non trouvées) et
    inventées (trouvées non attendues), après canonicalisation (critère 4)."""
    ext = canonical_tech_names(extracted, table)
    exp = canonical_tech_names(expected, table)
    return sorted(ext & exp), sorted(exp - ext), sorted(ext - exp)


def compare_fields(
    extracted: ExtractedFacts, expected: ExtractedFacts
) -> dict[str, bool]:
    """Séniorité, domaine, niveau de rôle : égaux à l'attendu ? (critère 5)."""
    return {
        "seniority": extracted.seniority_required == expected.seniority_required,
        "domain": extracted.domain == expected.domain,
        "role_level": extracted.role_level == expected.role_level,
    }


def compute_category(
    facts: ExtractedFacts, profile: Profile, table: AliasTable
) -> Category:
    """Catégorie désirabilité × atteignabilité sur le profil courant (critère 6)."""
    d = compute_desirability(facts, profile.search_criteria, profile, table)
    a = compute_attainability(facts, profile, table)
    return categorize(d.score, a.score)


@dataclass
class OfferComparison:
    """Le résultat d'une offre rejouée. `categorie_extrait=None` et tous les
    champs comparés à `False` si l'extraction a échoué — l'attendu, lui,
    reste calculable (indépendant de l'extraction)."""

    offer_id: str
    extraction_failed: bool
    techs_trouvees: list[str] = field(default_factory=list)
    techs_manquees: list[str] = field(default_factory=list)
    techs_inventees: list[str] = field(default_factory=list)
    champs_ok: dict[str, bool] = field(default_factory=dict)
    categorie_extrait: Category | None = None
    categorie_attendu: Category | None = None
    duration_seconds: float = 0.0


def compare_offer(
    offer_id: str,
    extracted: ExtractedFacts | None,
    expected: ExtractedFacts,
    profile: Profile,
    table: AliasTable,
    duration_seconds: float,
) -> OfferComparison:
    categorie_attendu = compute_category(expected, profile, table)
    if extracted is None:
        return OfferComparison(
            offer_id=offer_id,
            extraction_failed=True,
            techs_manquees=sorted(canonical_tech_names(expected, table)),
            champs_ok={"seniority": False, "domain": False, "role_level": False},
            categorie_attendu=categorie_attendu,
            duration_seconds=duration_seconds,
        )
    trouvees, manquees, inventees = compare_techs(extracted, expected, table)
    return OfferComparison(
        offer_id=offer_id,
        extraction_failed=False,
        techs_trouvees=trouvees,
        techs_manquees=manquees,
        techs_inventees=inventees,
        champs_ok=compare_fields(extracted, expected),
        categorie_extrait=compute_category(extracted, profile, table),
        categorie_attendu=categorie_attendu,
        duration_seconds=duration_seconds,
    )


@dataclass
class AggregateMetrics:
    n_offres: int
    technos_precision: float
    technos_rappel: float
    seniorite_part_juste: float
    domaine_part_juste: float
    niveau_role_part_juste: float
    extractions_echouees_part: float
    duree_mediane_s: float
    rappel_tri: float

    def as_dict(self) -> dict[str, float]:
        return {
            "technos_precision": self.technos_precision,
            "technos_rappel": self.technos_rappel,
            "seniorite_part_juste": self.seniorite_part_juste,
            "domaine_part_juste": self.domaine_part_juste,
            "niveau_role_part_juste": self.niveau_role_part_juste,
            "extractions_echouees_part": self.extractions_echouees_part,
            "duree_mediane_s": self.duree_mediane_s,
            "rappel_tri": self.rappel_tri,
        }


def _ratio(numerator: int, denominator: int) -> float:
    return numerator / denominator if denominator else 1.0


def _median(values: list[float]) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    n = len(ordered)
    mid = n // 2
    if n % 2:
        return ordered[mid]
    return (ordered[mid - 1] + ordered[mid]) / 2


def aggregate(comparisons: list[OfferComparison]) -> AggregateMetrics:
    """Précision/rappel technos, part juste par champ, part d'échecs, durée
    médiane (critères 7, 8) et rappel du tri (critère 9)."""
    n = len(comparisons)
    n_trouvees = sum(len(c.techs_trouvees) for c in comparisons)
    n_manquees = sum(len(c.techs_manquees) for c in comparisons)
    n_inventees = sum(len(c.techs_inventees) for c in comparisons)

    cibles = [c for c in comparisons if c.categorie_attendu in _TRI_CATEGORIES]

    return AggregateMetrics(
        n_offres=n,
        technos_precision=_ratio(n_trouvees, n_trouvees + n_inventees),
        technos_rappel=_ratio(n_trouvees, n_trouvees + n_manquees),
        seniorite_part_juste=_ratio(
            sum(1 for c in comparisons if c.champs_ok.get("seniority")), n
        ),
        domaine_part_juste=_ratio(
            sum(1 for c in comparisons if c.champs_ok.get("domain")), n
        ),
        niveau_role_part_juste=_ratio(
            sum(1 for c in comparisons if c.champs_ok.get("role_level")), n
        ),
        extractions_echouees_part=_ratio(
            sum(1 for c in comparisons if c.extraction_failed), n
        ),
        duree_mediane_s=_median([c.duration_seconds for c in comparisons]),
        rappel_tri=_ratio(
            sum(1 for c in cibles if c.categorie_extrait in _TRI_CATEGORIES),
            len(cibles),
        ),
    )
