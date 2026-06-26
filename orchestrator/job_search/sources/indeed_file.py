"""Adapter fichier pour les offres Indeed récupérées via MCP.

Lit les artefacts JSONL déposés dans data/indeed_inbox/ par la commande
/ingest-indeed (orchestration Claude + MCP Indeed).  Chaque ligne = une offre
brute, mappée vers JobOffer ici et nulle part ailleurs (architecture.md §1).

0 appel réseau, 0 LLM (architecture.md §4).
"""

import hashlib
import json
import unicodedata
import warnings
from datetime import datetime, timezone
from pathlib import Path

from orchestrator.job_search.sources._clean import html_to_markdown
from orchestrator.job_search.sources.base import JobOffer, Source


def _normalize(s: str) -> str:
    nfd = unicodedata.normalize("NFD", s.lower())
    return "".join(c for c in nfd if unicodedata.category(c) != "Mn")


def _fingerprint(title: str, company: str, location: str) -> str:
    key = "|".join([_normalize(title), _normalize(company), _normalize(location)])
    return hashlib.sha256(key.encode()).hexdigest()[:16]


class IndeedFileSource(Source):
    """Lit les JSONL du inbox Indeed et produit des JobOffer."""

    def __init__(self, inbox_dir: str = "data/indeed_inbox") -> None:
        self.inbox_dir = Path(inbox_dir)

    def fetch(self) -> list[JobOffer]:
        if not self.inbox_dir.exists():
            return []

        files = sorted(self.inbox_dir.glob("*.jsonl"))
        if not files:
            return []

        offers: list[JobOffer] = []
        for path in files:
            for line_no, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
                line = line.strip()
                if not line:
                    continue
                try:
                    data = json.loads(line)
                    offers.append(self._map(data))
                except Exception as exc:
                    warnings.warn(
                        f"[IndeedFileSource] skipped {path.name}:{line_no}: {exc}"
                    )

        return offers

    def _map(self, data: dict) -> JobOffer:
        title = data.get("title", "")
        company = data.get("company", "")
        location = data.get("location", "")
        description_raw = data.get("description", "")

        # source_id : identifiant Indeed stable, sinon fallback sur un hash
        source_id = data.get("indeed_id") or data.get("id") or ""
        if not source_id:
            source_id = hashlib.sha256(
                f"{title}|{company}|{location}".encode()
            ).hexdigest()[:16]

        return JobOffer(
            source="indeed",
            source_id=str(source_id),
            fingerprint=_fingerprint(title, company, location),
            title=title,
            description=html_to_markdown(description_raw),
            description_raw=description_raw,
            company=company or None,
            location=location or None,
            remote=data.get("remote", False),
            contract_type=data.get("job_type") or None,
            url=data.get("url", ""),
            fetched_at=datetime.now(timezone.utc),
        )
