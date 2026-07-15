import os
import time
import warnings
from datetime import datetime, timezone

import requests
from dotenv import load_dotenv

from orchestrator.job_search.sources.base import JobOffer, Source
from orchestrator.job_search.sources.fingerprint import fingerprint as _fingerprint

load_dotenv()

_TOKEN_URL = "https://entreprise.francetravail.fr/connexion/oauth2/access_token"
_SEARCH_URL = "https://api.francetravail.io/partenaire/offresdemploi/v2/offres/search"

_REMOTE_KEYWORDS = {"télétravail", "teletravail", "remote", "full remote", "full-remote"}


def _detect_remote(raw: dict) -> bool:
    text = " ".join([
        raw.get("intitule", ""),
        raw.get("description", ""),
        raw.get("lieuTravail", {}).get("libelle", ""),
    ]).lower()
    return any(kw in text for kw in _REMOTE_KEYWORDS)



class FranceTravailSource(Source):
    def __init__(
        self,
        keywords: list[str],
        commune: str | None = None,
        radius_km: int = 30,
        max_results: int = 150,
    ) -> None:
        self.client_id = os.environ["FRANCE_TRAVAIL_CLIENT_ID"]
        self.client_secret = os.environ["FRANCE_TRAVAIL_CLIENT_SECRET"]
        self.commune = commune
        self.radius_km = radius_km
        self.max_results = max_results
        self.keywords = keywords
        self._token: str | None = None
        self._token_expires_at: float = 0.0

    # ------------------------------------------------------------------
    # Auth
    # ------------------------------------------------------------------

    def _get_token(self) -> str:
        if self._token and time.time() < self._token_expires_at - 30:
            return self._token
        resp = requests.post(
            _TOKEN_URL,
            params={"realm": "/partenaire"},
            data={
                "grant_type": "client_credentials",
                "client_id": self.client_id,
                "client_secret": self.client_secret,
                "scope": "api_offresdemploiv2 o2dsoffre",
            },
            timeout=15,
        )
        resp.raise_for_status()
        payload = resp.json()
        self._token = payload["access_token"]
        self._token_expires_at = time.time() + payload.get("expires_in", 1200)
        return self._token

    # ------------------------------------------------------------------
    # Pagination
    # ------------------------------------------------------------------

    def _search_page(self, params: dict, start: int, end: int) -> list[dict]:
        resp = requests.get(
            _SEARCH_URL,
            headers={"Authorization": f"Bearer {self._get_token()}"},
            params={**params, "range": f"{start}-{end}"},
            timeout=20,
        )
        if resp.status_code == 204:
            return []
        resp.raise_for_status()
        return resp.json().get("resultats", [])

    def _fetch_all(self, params: dict, limit: int | None = None) -> list[dict]:
        cap = limit or self.max_results
        results: list[dict] = []
        page_size = 100
        start = 0
        while start < cap:
            end = min(start + page_size - 1, cap - 1)
            batch = self._search_page(params, start, end)
            results.extend(batch)
            if len(batch) < page_size:
                break
            start += page_size
        return results

    # ------------------------------------------------------------------
    # Mapping (FT payload → JobOffer — ne fuit jamais en dehors de ce module)
    # ------------------------------------------------------------------

    def _map(self, raw: dict) -> JobOffer:
        title = raw.get("intitule", "")
        company = raw.get("entreprise", {}).get("nom") or ""
        location = raw.get("lieuTravail", {}).get("libelle") or ""
        offer_id = raw["id"]
        url = (
            raw.get("origineOffre", {}).get("urlOrigine")
            or f"https://candidat.francetravail.fr/offres/recherche/detail/{offer_id}"
        )
        duree = raw.get("dureeTravailLibelleConverti", "")
        full_time: bool | None = ("plein" in duree.lower()) if duree else None
        return JobOffer(
            source="france_travail",
            source_id=offer_id,
            fingerprint=_fingerprint(title, company, location),
            title=title,
            description=raw.get("description", ""),
            description_raw=raw.get("description", ""),
            company=company or None,
            location=location or None,
            remote=_detect_remote(raw),
            contract_type=raw.get("typeContrat"),
            nature_contract=raw.get("natureContrat") or None,
            alternance=raw.get("alternance", False),
            full_time=full_time,
            company_size=raw.get("trancheEffectifEtab") or None,
            experience_required=raw.get("experienceExige") or None,
            rome_code=raw.get("romeCode") or None,
            rome_label=raw.get("romeLibelle") or None,
            url=url,
            fetched_at=datetime.now(timezone.utc),
        )

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    def fetch(self) -> list[JobOffer]:
        seen_ids: set[str] = set()
        raw_offers: list[dict] = []
        per_kw = max(10, self.max_results // len(self.keywords))

        for kw in self.keywords:
            params: dict = {"motsCles": kw}
            if self.commune:
                params["commune"] = self.commune
                params["distance"] = self.radius_km
            batch = self._fetch_all(params, limit=per_kw)
            for raw in batch:
                if raw["id"] not in seen_ids:
                    seen_ids.add(raw["id"])
                    raw_offers.append(raw)

        offers: list[JobOffer] = []
        for raw in raw_offers:
            try:
                offers.append(self._map(raw))
            except Exception as exc:
                warnings.warn(f"[FranceTravailSource] skipped offer {raw.get('id', '?')}: {exc}")

        return offers
