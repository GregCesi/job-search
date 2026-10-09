"""
Adapter Actiris — offres informatiques bruxelloises du service public de
l'emploi de la Région de Bruxelles-Capitale (EXE-163).

Deux étapes par offre : liste paginée (POST /api/Offer/GetAllOffers, filtrée
par code postal, domaine IMT et date de dernière modification) puis page de
détail HTML (texte complet de l'annonce, nom de l'employeur). Le détail n'est
ouvert que pour un nombre plafonné d'offres par run — les plus récemment
modifiées en premier, le reste attend le run suivant.

Pas de bibliothèque de parsing HTML dans ce dépôt (ni BeautifulSoup, ni lxml) :
la page de détail est découpée par les repères stables de son gabarit
(`bloc-emploi__text`, `bloc-emploi__disclaimer`, `bloc-emploi__apply`, la
rubrique « Nom de l'employeur »), pas par une passe générique de nettoyage.
"""

import html
import re
import time
import warnings
from datetime import datetime, timedelta, timezone

import requests

from orchestrator.job_search.sources._clean import html_to_markdown
from orchestrator.job_search.sources.base import JobOffer, Source
from orchestrator.job_search.sources.fingerprint import fingerprint as _fingerprint

_LIST_URL = "https://www.actiris.brussels/api/Offer/GetAllOffers"
_DETAIL_URL = "https://www.actiris.brussels/fr/citoyens/detail-offre-demploi/"

_HEADERS = {"Content-Type": "application/json", "Accept": "application/json"}

# 22 codes postaux de la Région de Bruxelles-Capitale (critère 3).
BRUSSELS_POSTAL_CODES = [
    "1000",
    "1020",
    "1030",
    "1040",
    "1050",
    "1060",
    "1070",
    "1080",
    "1081",
    "1082",
    "1083",
    "1090",
    "1120",
    "1130",
    "1140",
    "1150",
    "1160",
    "1170",
    "1180",
    "1190",
    "1200",
    "1210",
]

# Domaines IMT Actiris retenus : Logiciel (Q'1), Services informatiques (Q'3).
IT_DOMAINS = ["Q'1", "Q'3"]

_PAGE_SIZE = 200

# Au plus une requête toutes les 0.5s vers actiris.brussels (critère 5 : jamais
# plus de 2 requêtes par seconde), partagé entre la liste et le détail.
_MIN_INTERVAL = 0.5

_GENDER_SUFFIX_RE = re.compile(
    r"\s*\(?\s*[hm]\s*/\s*[fvw]\s*/\s*x\s*\)?\s*$", re.IGNORECASE
)


def _strip_gender_suffix(title: str) -> str:
    """Retire le suffixe de genre Actiris en fin de titre (critère 9)."""
    return _GENDER_SUFFIX_RE.sub("", title).rstrip()


def _strip_tags(fragment: str) -> str:
    return re.sub(r"<[^>]+>", " ", fragment)


def _collapse_spaces(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


class ActirisSource(Source):
    def __init__(
        self,
        since_days: int = 3,
        detail_cap: int = 200,
        postal_codes: list[str] | None = None,
        domains: list[str] | None = None,
    ) -> None:
        self.since_days = since_days
        self.detail_cap = detail_cap
        self.postal_codes = (
            postal_codes if postal_codes is not None else list(BRUSSELS_POSTAL_CODES)
        )
        self.domains = domains if domains is not None else list(IT_DOMAINS)
        self._last_request_at: float | None = None

    def fetch(self) -> list[JobOffer]:
        candidates = self._list_all()
        # Tri par date de modification décroissante — l'API ne garantit pas
        # l'ordre de ses résultats (critère 4).
        candidates.sort(
            key=lambda c: str(c.get("dateModification") or ""), reverse=True
        )
        capped = candidates[: self.detail_cap]

        offers: list[JobOffer] = []
        n_pages_detail = 0
        for item in capped:
            reference = str(item.get("reference") or "").strip()
            if not reference:
                continue
            n_pages_detail += 1
            offer = self._map(reference, item)
            if offer is not None:
                offers.append(offer)
        print(f"[ActirisSource] {n_pages_detail} pages de détail ouvertes")
        return offers

    # ── Liste ────────────────────────────────────────────────────────────

    def _list_all(self) -> list[dict]:
        since = (
            (datetime.now(timezone.utc) - timedelta(days=self.since_days))
            .date()
            .isoformat()
        )
        results: list[dict] = []
        seen_refs: set[str] = set()
        page = 1
        total: int | None = None

        while total is None or len(results) < total:
            payload = {
                "pageOption": {
                    "page": page,
                    "from": (page - 1) * _PAGE_SIZE,
                    "pageSize": _PAGE_SIZE,
                },
                "offreFilter": {
                    "texte": "",
                    "regimesTravail": [],
                    "dateDerniereModification": since,
                    "langue": None,
                    "codesPostal": self.postal_codes,
                    "codesContrat": [],
                    "domainesImt": self.domains,
                    "secteursPanorama": [],
                    "references": [],
                    "localisation": "Tout",
                    "keywordSearchType": "Partout",
                    "isOffreActiris": False,
                    "isOffreVdabForem": False,
                    "isOfferPartner": False,
                    "isOffreHandicap": False,
                    "employerFilter": [],
                },
            }
            self._throttle()
            try:
                resp = requests.post(
                    _LIST_URL, json=payload, headers=_HEADERS, timeout=20
                )
                resp.raise_for_status()
                data = resp.json()
            except Exception as exc:
                warnings.warn(f"[ActirisSource] liste injoignable (page={page}): {exc}")
                break

            page_offers = data.get("offers") or []
            if not page_offers:
                break
            for item in page_offers:
                ref = str(item.get("reference") or "")
                if ref and ref not in seen_refs:
                    seen_refs.add(ref)
                    results.append(item)
            total = data.get("total")
            page += 1

        return [item for item in results if self._in_scope(item)]

    def _in_scope(self, item: dict) -> bool:
        return (
            str(item.get("codePostal") or "") in self.postal_codes
            and str(item.get("codeDomaineImt") or "") in self.domains
        )

    # ── Détail + mapping ─────────────────────────────────────────────────

    def _map(self, reference: str, item: dict) -> JobOffer | None:
        type_offer = str(item.get("typeOffer") or "")
        title_fr = str(item.get("titreFr") or "").strip()
        title_nl = str(item.get("titreNl") or "").strip()

        detail = self._fetch_detail(reference, type_offer)

        title = title_fr or title_nl or (detail or {}).get("title") or "Sans titre"
        title = _strip_gender_suffix(title) or "Sans titre"

        commune = str(item.get("communeFr") or item.get("communeNl") or "").strip()
        code_postal = str(item.get("codePostal") or "").strip()
        location_line = ""
        if commune or code_postal:
            location_line = f"Localisation : {commune} ({code_postal})".strip()
        body = (detail or {}).get("description") or ""
        description = "\n\n".join(p for p in (location_line, body) if p)

        url = f"{_DETAIL_URL}?reference={reference}&type={type_offer}"

        return JobOffer(
            source="actiris",
            source_id=reference,
            fingerprint=_fingerprint(
                title, (detail or {}).get("employer") or "", "Bruxelles"
            ),
            title=title,
            description=description,
            description_raw=(detail or {}).get("raw_html"),
            company=(detail or {}).get("employer"),
            location="Bruxelles",
            remote=False,
            contract_type=None,
            url=url,
            fetched_at=datetime.now(timezone.utc),
        )

    def _fetch_detail(self, reference: str, type_offer: str) -> dict | None:
        self._throttle()
        try:
            resp = requests.get(
                _DETAIL_URL,
                params={"reference": reference, "type": type_offer},
                timeout=20,
            )
            resp.raise_for_status()
            raw_html = resp.text
        except Exception as exc:
            warnings.warn(
                f"[ActirisSource] détail injoignable (reference={reference}): {exc}"
            )
            return None
        return self._parse_detail(raw_html)

    def _parse_detail(self, raw_html: str) -> dict:
        text = html.unescape(raw_html)
        result: dict = {"raw_html": raw_html}

        h1 = re.search(r"<h1[^>]*>(.*?)</h1>", text, re.S)
        if h1:
            title = _collapse_spaces(_strip_tags(h1.group(1)))
            if title:
                result["title"] = title

        employer = re.search(
            r"Nom de l'employeur\s*</div>\s*</td>\s*<td>\s*<div>(.*?)</div>",
            text,
            re.S,
        )
        if employer:
            emp = _collapse_spaces(_strip_tags(employer.group(1)))
            if emp:
                result["employer"] = emp

        start = text.find("bloc-emploi__text")
        if start != -1:
            div_start = text.rfind("<div", 0, start)
            if div_start == -1:
                div_start = start
            end_candidates = [
                p
                for p in (
                    text.find("bloc-emploi__text", start + 1),
                    text.find("bloc-emploi__disclaimer", start),
                    text.find("bloc-emploi__apply", start),
                    text.find("Mentions légales", start),
                    text.find("Restons en contact", start),
                )
                if p != -1
            ]
            end = min(end_candidates) if end_candidates else len(text)
            chunk = text[div_start:end]
            md = html_to_markdown(chunk)
            md = "\n".join(
                line
                for line in md.splitlines()
                if "panorama des métiers" not in line.lower()
            )
            result["description"] = md.strip()

        return result

    def _throttle(self) -> None:
        now = time.monotonic()
        if self._last_request_at is not None:
            elapsed = now - self._last_request_at
            if elapsed < _MIN_INTERVAL:
                time.sleep(_MIN_INTERVAL - elapsed)
        self._last_request_at = time.monotonic()
