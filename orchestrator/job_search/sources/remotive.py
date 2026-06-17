import hashlib
import unicodedata
import warnings
from datetime import datetime, timezone

import requests

from orchestrator.job_search.sources._clean import html_to_markdown
from orchestrator.job_search.sources.base import JobOffer, Source


def _normalize(s: str) -> str:
    nfd = unicodedata.normalize("NFD", s.lower())
    return "".join(c for c in nfd if unicodedata.category(c) != "Mn")


def _fingerprint(title: str, company: str, location: str) -> str:
    key = "|".join([_normalize(title), _normalize(company), _normalize(location)])
    return hashlib.sha256(key.encode()).hexdigest()[:16]


_API_URL = "https://remotive.com/api/remote-jobs"


class RemotiveSource(Source):
    def __init__(self, limit: int = 100) -> None:
        self.limit = limit

    def fetch(self) -> list[JobOffer]:
        try:
            resp = requests.get(
                _API_URL,
                params={"category": "software-dev", "limit": self.limit},
                timeout=20,
            )
            resp.raise_for_status()
        except Exception as exc:
            warnings.warn(f"[RemotiveSource] API error: {exc}")
            return []

        jobs = resp.json().get("jobs", [])
        offers: list[JobOffer] = []
        for item in jobs:
            try:
                title = item.get("title", "")
                company = item.get("company_name", "")
                location = item.get("candidate_required_location", "")
                raw_html = item.get("description", "")
                offers.append(JobOffer(
                    source="remotive",
                    source_id=str(item["id"]),
                    fingerprint=_fingerprint(title, company, location),
                    title=title,
                    description=html_to_markdown(raw_html),
                    description_raw=raw_html,
                    company=company or None,
                    location=location or None,
                    remote=True,
                    contract_type=None,
                    url=item.get("url", ""),
                    fetched_at=datetime.now(timezone.utc),
                    full_time=item.get("job_type") == "full_time",
                ))
            except Exception as exc:
                warnings.warn(f"[RemotiveSource] skipped offer {item.get('id', '?')}: {exc}")

        return offers
