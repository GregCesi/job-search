"""
Adapter Forem — offres informatiques bruxelloises republiées par le Forem
(Jobat, StepStone, References…) en open data (EXE-164).

Deux étapes par offre : liste paginée (GET sur le jeu de données Opendatasoft
`offres-d-emploi-forem`, filtrée par région NUTS et date de début de diffusion)
puis détail JSON (GET /recherche-offres/api/Diffusion/DetailOffre/{numero}),
qui porte le texte complet de l'annonce. Le détail n'est ouvert que pour un
nombre plafonné d'offres par run — les diffusions les plus récentes en
premier, le reste attend le run suivant.

Le détail porte aussi `howToApply` (coordonnées d'une personne), `logoEmployeur`
et `logoMimeType` : ces champs ne sont jamais lus par cet adapter (liste
blanche, pas de passe générique sur le JSON).
"""

import re
import time
import unicodedata
import warnings
from datetime import datetime, timedelta, timezone

import requests

from orchestrator.job_search.sources._clean import html_to_markdown
from orchestrator.job_search.sources.base import JobOffer, Source
from orchestrator.job_search.sources.fingerprint import fingerprint as _fingerprint

_DATASET_URL = (
    "https://www.odwb.be/api/explore/v2.1/catalog/datasets/"
    "offres-d-emploi-forem/records"
)
_DETAIL_URL = (
    "https://www.leforem.be/recherche-offres/api/Diffusion/DetailOffre/{numero}"
)
_OFFER_PAGE_URL = "https://www.leforem.be/recherche-offres/offre-detail/{numero}"

# Code NUTS de la Région de Bruxelles-Capitale (critère 3).
BRUSSELS_NUTS = "BE1"

# Préfixe des codes métier informatiques Dimeco (critère 4).
IT_METIER_PREFIX = "M18"

_PAGE_SIZE = 100

# Au plus une requête toutes les 0.5s, partagée entre le jeu de données
# (odwb.be) et le détail (leforem.be) — garantit ≤2 requêtes/s vers chacun
# des deux hôtes (critère 6).
_MIN_INTERVAL = 0.5

_GENDER_SUFFIX_RE = re.compile(
    r"\s*\(?\s*[hm]\s*/\s*[fvw]\s*/\s*x\s*\)?\s*$", re.IGNORECASE
)


def _strip_gender_suffix(title: str) -> str:
    """Retire le suffixe de genre en fin de titre (critère 8)."""
    return _GENDER_SUFFIX_RE.sub("", title).rstrip()


def _normalize(s: str) -> str:
    nfd = unicodedata.normalize("NFD", s.lower())
    return "".join(c for c in nfd if unicodedata.category(c) != "Mn")


def _title_matches_keyword(title: str, keywords: list[str]) -> bool:
    norm_title = _normalize(title)
    return any(_normalize(kw) in norm_title for kw in keywords if kw)


class ForemSource(Source):
    def __init__(
        self,
        keywords: list[str],
        since_days: int = 3,
        detail_cap: int = 200,
    ) -> None:
        self.keywords = keywords
        self.since_days = since_days
        self.detail_cap = detail_cap
        self._last_request_at: float | None = None

    def fetch(self) -> list[JobOffer]:
        candidates = self._list_all()
        # Diffusions les plus récentes d'abord — le reste attend le run
        # suivant (critère 5).
        candidates.sort(
            key=lambda c: str(c.get("datedebutdiffusion") or ""), reverse=True
        )
        capped = candidates[: self.detail_cap]

        offers: list[JobOffer] = []
        n_detail = 0
        for item in capped:
            numero = str(item.get("numerooffreforem") or "").strip()
            if not numero:
                continue
            n_detail += 1
            offers.append(self._map(numero, item))
        print(f"[ForemSource] {n_detail} pages de détail ouvertes")
        return offers

    # ── Liste ────────────────────────────────────────────────────────────

    def _list_all(self) -> list[dict]:
        since = (
            (datetime.now(timezone.utc) - timedelta(days=self.since_days))
            .date()
            .isoformat()
        )
        where = (
            f'lieuxtravailregionnuts="{BRUSSELS_NUTS}" '
            f"AND datedebutdiffusion >= date'{since}'"
        )
        results: list[dict] = []
        seen_numeros: set[str] = set()
        offset = 0
        total: int | None = None

        while total is None or offset < total:
            params = {"where": where, "limit": _PAGE_SIZE, "offset": offset}
            self._throttle()
            try:
                resp = requests.get(_DATASET_URL, params=params, timeout=20)
                resp.raise_for_status()
                data = resp.json()
            except Exception as exc:
                warnings.warn(
                    f"[ForemSource] jeu de données injoignable (offset={offset}): {exc}"
                )
                break

            page_results = data.get("results") or []
            if not page_results:
                break
            for item in page_results:
                numero = str(item.get("numerooffreforem") or "")
                if numero and numero not in seen_numeros:
                    seen_numeros.add(numero)
                    results.append(item)
            total = data.get("total_count")
            offset += _PAGE_SIZE

        return [item for item in results if self._in_scope(item)]

    def _in_scope(self, item: dict) -> bool:
        nuts = item.get("lieuxtravailregionnuts") or []
        if BRUSSELS_NUTS not in nuts:
            return False
        metier_code = str(item.get("metiercodedimeco") or "")
        if metier_code.startswith(IT_METIER_PREFIX):
            return True
        return _title_matches_keyword(str(item.get("titreoffre") or ""), self.keywords)

    # ── Détail + mapping ─────────────────────────────────────────────────

    def _map(self, numero: str, item: dict) -> JobOffer:
        detail = self._fetch_detail(numero)

        title_raw = (
            (detail or {}).get("titreOffre") or item.get("titreoffre") or "Sans titre"
        )
        title = _strip_gender_suffix(str(title_raw).strip()) or "Sans titre"

        company = (detail or {}).get("nomEmployeur") or item.get("nomemployeur") or None

        localites = item.get("lieuxtravaillocalite") or []
        location_line = f"Localisation : {', '.join(localites)}" if localites else ""
        description_html = (detail or {}).get("descriptionJob") or ""
        body = html_to_markdown(description_html) if description_html else ""
        description = "\n\n".join(p for p in (location_line, body) if p)

        type_contrat = (detail or {}).get("typeContrat") or item.get("typecontrat")
        regime = (detail or {}).get("regimeTravail") or item.get("regimetravail")
        full_time = ("plein" in regime.lower()) if regime else None

        return JobOffer(
            source="forem",
            source_id=numero,
            fingerprint=_fingerprint(title, company or "", "Bruxelles"),
            title=title,
            description=description,
            description_raw=description_html or None,
            company=company,
            location="Bruxelles",
            remote=False,
            contract_type=None,
            nature_contract=type_contrat or None,
            full_time=full_time,
            url=_OFFER_PAGE_URL.format(numero=numero),
            fetched_at=datetime.now(timezone.utc),
        )

    def _fetch_detail(self, numero: str) -> dict | None:
        self._throttle()
        try:
            resp = requests.get(_DETAIL_URL.format(numero=numero), timeout=20)
            resp.raise_for_status()
            return resp.json()
        except Exception as exc:
            warnings.warn(f"[ForemSource] détail injoignable (numero={numero}): {exc}")
            return None

    def _throttle(self) -> None:
        now = time.monotonic()
        if self._last_request_at is not None:
            elapsed = now - self._last_request_at
            if elapsed < _MIN_INTERVAL:
                time.sleep(_MIN_INTERVAL - elapsed)
        self._last_request_at = time.monotonic()
