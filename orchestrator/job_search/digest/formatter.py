import json
from datetime import datetime

from orchestrator.job_search.storage.offers import StoredOffer

_TOP_N = 10
_MIN_DESIRABILITY = 40.0  # sous ce seuil, pas dans le digest


def _bar(score: float, width: int = 20) -> str:
    filled = round(score / 100 * width)
    return "█" * filled + "░" * (width - filled)


def _format_offer(rank: int, offer: StoredOffer) -> str:
    d = offer.desirability or 0.0
    a = offer.attainability or "?"
    company = offer.company or "?"
    location = f"{offer.location or '?'}" + (" · remote" if offer.remote else "")
    contract = offer.contract_type or "?"

    lines = [
        f"#{rank}  {offer.title}",
        f"    {company} — {location} — {contract}",
        f"    Désirabilité : {d:.1f}/100  {_bar(d)}   Atteignabilité : {a}",
    ]

    if offer.attainability_detail:
        try:
            detail = json.loads(offer.attainability_detail)
            matched = detail.get("techs_matched", [])
            missing = detail.get("techs_missing", [])
            if matched:
                lines.append(f"    ✓ {', '.join(matched)}")
            if missing:
                lines.append(f"    ✗ {', '.join(missing)}")
        except (json.JSONDecodeError, KeyError):
            pass

    lines.append(f"    {offer.url}")
    return "\n".join(lines)


def generate_digest(offers: list[StoredOffer], run_at: datetime | None = None) -> str:
    run_at = run_at or datetime.now()

    # Digest = atteignables (at_level ou one_step_up) ET suffisamment désirables
    relevant = [
        o for o in offers
        if (o.desirability or 0.0) >= _MIN_DESIRABILITY
        and o.attainability in ("at_level", "one_step_up")
    ]
    relevant = sorted(relevant, key=lambda o: o.desirability or 0.0, reverse=True)[:_TOP_N]

    header = (
        f"╔══════════════════════════════════════════╗\n"
        f"  JOB DIGEST — {run_at.strftime('%Y-%m-%d %H:%M')}\n"
        f"  {len(offers)} offres · {len(relevant)} retenues (désirabilité ≥ {_MIN_DESIRABILITY}, atteignables)\n"
        f"╚══════════════════════════════════════════╝"
    )

    if not relevant:
        return header + "\n\nAucune offre pertinente aujourd'hui.\n"

    blocks = [_format_offer(i + 1, o) for i, o in enumerate(relevant)]
    return header + "\n\n" + "\n\n".join(blocks) + "\n"
