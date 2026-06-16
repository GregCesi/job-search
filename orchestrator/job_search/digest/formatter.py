from datetime import datetime

from orchestrator.job_search.storage.offers import StoredOffer

_TOP_N = 15

_CATEGORY_ORDER = {"parfait": 0, "reve": 1, "atteignable": 2, "hors": 3}


def _format_offer(rank: int, offer: StoredOffer) -> str:
    company = offer.company or "?"
    location = f"{offer.location or '?'}" + (" · remote" if offer.remote else "")
    contract = offer.contract_type or "?"
    cat = offer.category or "?"

    lines = [
        f"#{rank}  [{cat}]  {offer.title}",
        f"    {company} — {location} — {contract}",
        f"    {offer.url}",
    ]
    return "\n".join(lines)


def generate_digest(offers: list[StoredOffer], run_at: datetime | None = None) -> str:
    run_at = run_at or datetime.now()

    relevant = [o for o in offers if o.category in ("parfait", "reve", "atteignable")]
    relevant.sort(key=lambda o: _CATEGORY_ORDER.get(o.category or "", 99))
    relevant = relevant[:_TOP_N]

    header = (
        f"╔══════════════════════════════════════════╗\n"
        f"  JOB DIGEST — {run_at.strftime('%Y-%m-%d %H:%M')}\n"
        f"  {len(offers)} offres · {len(relevant)} retenues (parfait/rêve/atteignable)\n"
        f"╚══════════════════════════════════════════╝"
    )

    if not relevant:
        return header + "\n\nAucune offre pertinente aujourd'hui.\n"

    blocks = [_format_offer(i + 1, o) for i, o in enumerate(relevant)]
    return header + "\n\n" + "\n\n".join(blocks) + "\n"
