"""Rendu texte du rapport d'un rejeu — agrégats + détail par offre (critère 11,
TCK-221, EXE-107)."""

from __future__ import annotations

from orchestrator.job_search.reference.metrics import AggregateMetrics, OfferComparison


def render_report(
    model: str,
    jeu_fp: str,
    aggregates: AggregateMetrics,
    comparisons: list[OfferComparison],
) -> str:
    lines = [
        f"# Rejeu du jeu de référence — {model}",
        f"Empreinte du jeu : {jeu_fp}",
        f"Offres rejouées : {aggregates.n_offres}",
        "",
        "## Agrégats",
        f"- Précision technos : {aggregates.technos_precision:.2%}",
        f"- Rappel technos : {aggregates.technos_rappel:.2%}",
        f"- Séniorité juste : {aggregates.seniorite_part_juste:.2%}",
        f"- Domaine juste : {aggregates.domaine_part_juste:.2%}",
        f"- Niveau de rôle juste : {aggregates.niveau_role_part_juste:.2%}",
        f"- Extractions échouées : {aggregates.extractions_echouees_part:.2%}",
        f"- Durée médiane : {aggregates.duree_mediane_s:.2f}s",
        f"- Rappel du tri : {aggregates.rappel_tri:.2%}",
        "",
        "## Détail par offre",
    ]
    for c in comparisons:
        if c.extraction_failed:
            lines.append(f"- {c.offer_id} : extraction échouée")
            continue
        extrait = c.categorie_extrait.value if c.categorie_extrait else "-"
        attendu = c.categorie_attendu.value if c.categorie_attendu else "-"
        lines.append(
            f"- {c.offer_id} : trouvées={c.techs_trouvees} "
            f"manquées={c.techs_manquees} inventées={c.techs_inventees} | "
            f"séniorité={'ok' if c.champs_ok['seniority'] else 'faux'} "
            f"domaine={'ok' if c.champs_ok['domain'] else 'faux'} "
            f"niveau_role={'ok' if c.champs_ok['role_level'] else 'faux'} | "
            f"catégorie extrait={extrait} attendu={attendu}"
        )
    return "\n".join(lines) + "\n"
