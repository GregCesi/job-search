import json
from datetime import datetime

from job_search.storage.offers import StoredOffer

_TOP_N = 10
_MIN_SCORE = 1.0  # skip perfect 0s (clearly irrelevant)


def _bar(score: float, width: int = 20) -> str:
    filled = round(score / 100 * width)
    return "█" * filled + "░" * (width - filled)


def _format_offer(rank: int, offer: StoredOffer) -> str:
    score = offer.score or 0.0
    company = offer.company or "?"
    location = f"{offer.location or '?'}" + (" · remote" if offer.remote else "")
    contract = offer.contract_type or "?"

    lines = [
        f"#{rank}  {offer.title}",
        f"    {company} — {location} — {contract}",
        f"    Score : {score:.1f}/100  {_bar(score)}",
    ]

    if offer.criteria_json:
        try:
            criteria = json.loads(offer.criteria_json)
            for c in criteria:
                if c.get("parse_failed"):
                    continue
                key = c["key"].replace("_", " ")
                lines.append(f"    · {key:<18} {c['score']:>4}/10  {c['justification'][:70]}")
        except (json.JSONDecodeError, KeyError):
            pass

    lines.append(f"    {offer.url}")
    return "\n".join(lines)


def generate_digest(offers: list[StoredOffer], run_at: datetime | None = None) -> str:
    run_at = run_at or datetime.now()
    relevant = [o for o in offers if (o.score or 0.0) >= _MIN_SCORE]
    relevant = sorted(relevant, key=lambda o: o.score or 0.0, reverse=True)[:_TOP_N]

    header = (
        f"╔══════════════════════════════════════════╗\n"
        f"  JOB DIGEST — {run_at.strftime('%Y-%m-%d %H:%M')}\n"
        f"  {len(offers)} offres scorées · {len(relevant)} retenues (score ≥ {_MIN_SCORE})\n"
        f"╚══════════════════════════════════════════╝"
    )

    if not relevant:
        return header + "\n\nAucune offre pertinente aujourd'hui.\n"

    blocks = [_format_offer(i + 1, o) for i, o in enumerate(relevant)]
    return header + "\n\n" + "\n\n".join(blocks) + "\n"
