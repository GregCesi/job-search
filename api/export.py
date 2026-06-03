"""Génération du rapport markdown de calibration — L12.

GET /export/calibration
    → texte markdown, offres notées triées par désaccord décroissant, lots de 15.
"""
import json
import math
from datetime import timezone

from fastapi import APIRouter
from fastapi.responses import PlainTextResponse

from .db import get_conn
from orchestrator.job_search.storage.reviews import HumanReview
from orchestrator.job_search.calibration.disagreement import disagreement, DisagreementScore

router = APIRouter()

_PAGE_SIZE = 15


@router.get("/export/calibration", response_class=PlainTextResponse)
def export_calibration() -> str:
    conn = get_conn()
    try:
        rows = conn.execute(
            """
            SELECT hr.offer_id, hr.ratings_json, hr.ai_snapshot_json,
                   hr.global_audit_text, hr.global_score, hr.seen_at_review, hr.created_at,
                   o.title, o.company
            FROM human_reviews hr
            LEFT JOIN offers o ON CAST(hr.offer_id AS INTEGER) = o.id
            """
        ).fetchall()
    finally:
        conn.close()

    if not rows:
        return "# Calibration\n\nAucune review enregistrée.\n"

    scored: list[tuple[DisagreementScore, dict]] = []
    for row in rows:
        review = HumanReview(
            offer_id=row["offer_id"],
            ratings_json=row["ratings_json"],
            ai_snapshot_json=row["ai_snapshot_json"],
            global_audit_text=row["global_audit_text"],
            global_score=row["global_score"],
            seen_at_review=bool(row["seen_at_review"]),
            created_at=row["created_at"],
        )
        score = disagreement(review)
        scored.append((score, {
            "title": row["title"] or f"offre #{row['offer_id']}",
            "company": row["company"] or "?",
            "review": review,
        }))

    scored.sort(key=lambda x: x[0].distance_total, reverse=True)

    n_pages = max(1, math.ceil(len(scored) / _PAGE_SIZE))
    lines: list[str] = [
        f"# Calibration — {len(scored)} offre(s) notée(s)",
        f"Triées par désaccord décroissant · lots de {_PAGE_SIZE}\n",
    ]

    for page in range(n_pages):
        batch = scored[page * _PAGE_SIZE : (page + 1) * _PAGE_SIZE]
        if n_pages > 1:
            lines.append(f"---\n## Lot {page + 1}/{n_pages}\n")

        for ds, meta in batch:
            review: HumanReview = meta["review"]
            ratings: dict = json.loads(review.ratings_json)
            snapshot: list[dict] = json.loads(review.ai_snapshot_json)
            ai_by_nom = {c["nom"]: c for c in snapshot}

            lines.append(f"### {meta['title']} — {meta['company']}")
            lines.append(
                f"distance_total={ds.distance_total:.2f}"
                + (f"  désir={ds.distance_desirability:.2f}" if ds.distance_desirability is not None else "")
                + (f"  attein={ds.distance_attainability:.2f}" if ds.distance_attainability is not None else "")
                + f"  couverture={ds.n_criteria_rated} critère(s)"
                + f"  date={review.created_at[:10]}"
            )

            # Détail par critère co-noté
            for nom, human_val in ratings.items():
                h_note = human_val.get("note") if isinstance(human_val, dict) else None
                if h_note is None:
                    continue
                ai_c = ai_by_nom.get(nom)
                if ai_c is None:
                    continue
                ai_note = ai_c.get("note")
                diff = abs(float(h_note) - float(ai_note)) if ai_note is not None else None
                diff_str = f"Δ={diff:.1f}" if diff is not None else "Δ=?"
                h_justif = (human_val.get("justif") or "").strip()
                lines.append(
                    f"- **{nom}** : IA={ai_note}/10 → humain={h_note}/10 ({diff_str})"
                    + (f" — {h_justif}" if h_justif else "")
                )

            if review.global_score is not None:
                lines.append(f"- Note globale humaine : {review.global_score}/10")
            if review.global_audit_text:
                lines.append(f"> {review.global_audit_text}")

            lines.append("")

    return "\n".join(lines)
