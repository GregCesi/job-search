"""
Calcul de distance de désaccord humain↔IA — L10.

Fonction pure : prend un HumanReview + ai_snapshot déjà parsé, retourne
un DisagreementScore. N'accède jamais à la DB.

Règle : seuls les critères co-notés (note humaine non-None ET note IA présente)
contribuent à la distance. Les critères non renseignés sont ignorés, jamais
comptés 0.
"""
from __future__ import annotations

from pydantic import BaseModel

from orchestrator.job_search.storage.reviews import HumanReview


class DisagreementScore(BaseModel):
    offer_id: str
    distance_desirability: float | None  # None si aucun critère co-noté axe désir
    distance_attainability: float | None # None si aucun critère co-noté axe attein.
    distance_total: float                # agrégat des deux axes (None = absent)
    n_criteria_rated: int                # couverture — métadonnée, n'influence pas le tri
    created_at: str


def disagreement(review: HumanReview) -> DisagreementScore:
    """Calcule la distance de désaccord à partir d'une HumanReview.

    ratings_json  : {nom: {note: int|null, justif: str|null}}
    ai_snapshot_json : [{nom, note, justif, axe}, ...]
    """
    import json

    ratings: dict = json.loads(review.ratings_json)
    snapshot: list[dict] = json.loads(review.ai_snapshot_json)

    # Index snapshot par nom de critère
    ai_by_nom = {c["nom"]: c for c in snapshot}

    desr_diffs: list[float] = []
    att_diffs: list[float] = []
    n_rated = 0

    for nom, human_val in ratings.items():
        h_note = human_val.get("note") if isinstance(human_val, dict) else None
        if h_note is None:
            continue
        if nom not in ai_by_nom:
            continue
        ai_note = ai_by_nom[nom].get("note")
        if ai_note is None:
            continue

        diff = abs(float(h_note) - float(ai_note))
        axe = ai_by_nom[nom].get("axe", "")
        if axe == "desirability":
            desr_diffs.append(diff)
        else:
            att_diffs.append(diff)
        n_rated += 1

    distance_desirability = (sum(desr_diffs) / len(desr_diffs)) if desr_diffs else None
    distance_attainability = (sum(att_diffs) / len(att_diffs)) if att_diffs else None

    components = [d for d in (distance_desirability, distance_attainability) if d is not None]
    distance_total = (sum(components) / len(components)) if components else 0.0

    return DisagreementScore(
        offer_id=review.offer_id,
        distance_desirability=distance_desirability,
        distance_attainability=distance_attainability,
        distance_total=distance_total,
        n_criteria_rated=n_rated,
        created_at=review.created_at,
    )
