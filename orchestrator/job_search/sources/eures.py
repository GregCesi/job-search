"""
Adapter EURES — offres belges via l'API du portail européen.

Une seule étape par offre : POST /public/jv-search/search retourne titre,
employeur, description complète et localisation. Le détail n'est pas nécessaire.

EURES API base : https://europa.eu/eures/api/jv-searchengine
URL candidature : portail construit depuis l'id (pas de webProfiles dans search).
"""
import time
import warnings
from datetime import datetime, timezone

import requests

from orchestrator.job_search.sources._clean import html_to_markdown
from orchestrator.job_search.sources.base import JobOffer, Source
from orchestrator.job_search.sources.fingerprint import fingerprint as _fingerprint

_BASE = "https://europa.eu/eures/api/jv-searchengine"
_SEARCH_URL = f"{_BASE}/public/jv-search/search"
_PORTAL_URL = "https://europa.eu/eures/portal/jv-se/jv-details/{id}?lang=fr"

_HEADERS = {
    "Content-Type": "application/json",
    "Accept": "application/json",
}

# Délai minimal entre pages de recherche
_SLEEP = 0.5


def _location_from_map(location_map: dict) -> str:
    """Convertit un locationMap NUTS (ex: {'BE': ['BE100']}) en chaîne lisible.

    BE1xx → Bruxelles (correspond au keyword 'bruxelles' dans belgique_area).
    Autre → Belgique (fallback, keyword 'belgique' dans belgique_area).
    """
    for codes in location_map.values():
        if isinstance(codes, list):
            for code in codes:
                code_upper = str(code).upper()
                if code_upper.startswith("BE1"):
                    return "Bruxelles"
    return "Belgique"


def _best_description(jv: dict) -> str:
    """Retourne la meilleure description HTML disponible.

    Priorité : translations.fr → translations.en → description racine (brut).
    """
    translations: dict = jv.get("translations") or {}
    for lang in ("fr", "en"):
        block = translations.get(lang)
        if isinstance(block, dict):
            desc = block.get("description")
            if desc:
                return str(desc)
    # description à la racine (langue principale — souvent nl)
    return str(jv.get("description") or "")


class EuresSource(Source):
    def __init__(
        self,
        keywords: list[str],
        location_codes: list[str] | None = None,
        max_per_keyword: int = 200,
    ) -> None:
        self.keywords = keywords
        # be1 = Bruxelles, be3 = Wallonie (codes NUTS-1 EURES)
        self.location_codes = location_codes if location_codes is not None else ["be1", "be3"]
        self.max_per_keyword = max_per_keyword

    def fetch(self) -> list[JobOffer]:
        offers: list[JobOffer] = []
        seen_ids: set[str] = set()

        for keyword in self.keywords:
            for jv in self._search_all(keyword):
                jv_id = str(jv.get("id", "") or "").strip()
                if not jv_id or jv_id in seen_ids:
                    continue
                seen_ids.add(jv_id)
                offer = self._map(jv_id, jv)
                if offer is not None:
                    offers.append(offer)

        return offers

    # ── Pagination search ──────────────────────────────────────────────────

    def _search_all(self, keyword: str) -> list[dict]:
        results: list[dict] = []
        page = 1
        per_page = min(50, self.max_per_keyword)

        while len(results) < self.max_per_keyword:
            payload = {
                "keywords": [{"keyword": keyword, "specificSearchCode": "EVERYWHERE"}],
                "locationCodes": self.location_codes,
                "resultsPerPage": per_page,
                "page": page,
                "sortSearch": "BEST_MATCH",
            }
            try:
                resp = requests.post(
                    _SEARCH_URL, json=payload, headers=_HEADERS, timeout=20
                )
                resp.raise_for_status()
                jvs = resp.json().get("jvs", [])
            except Exception as exc:
                warnings.warn(f"[EuresSource] search error (kw={keyword!r} p={page}): {exc}")
                break

            if not jvs:
                break  # fin de pagination

            results.extend(jvs)
            page += 1
            time.sleep(_SLEEP)

        return results[: self.max_per_keyword]

    # ── Mapping ────────────────────────────────────────────────────────────

    def _map(self, jv_id: str, jv: dict) -> JobOffer | None:
        try:
            title: str = str(jv.get("title") or "Sans titre")

            emp = jv.get("employer")
            company: str | None = (
                emp.get("name") if isinstance(emp, dict) else None
            ) or None

            location = _location_from_map(jv.get("locationMap") or {})

            description_html = _best_description(jv)
            description = html_to_markdown(description_html)

            url = _PORTAL_URL.format(id=jv_id)

            # positionOfferingCode : directhire / contract / selfemployed / …
            contract_type = jv.get("positionOfferingCode")

            return JobOffer(
                source="eures",
                source_id=jv_id,
                fingerprint=_fingerprint(title, company or "", location),
                title=title,
                description=description,
                description_raw=description_html or None,
                company=company,
                location=location,
                remote=False,
                contract_type=contract_type,
                url=url,
                fetched_at=datetime.now(timezone.utc),
            )
        except Exception as exc:
            warnings.warn(f"[EuresSource] mapping error (id={jv_id}): {exc}")
            return None
