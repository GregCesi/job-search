"""Source « manuel » — une offre trouvée à la main, par son URL ou son texte (EXE-79).

Deux entrées, un seul `JobOffer` en sortie :
- l'URL seule : la page est lue, et titre, entreprise, lieu et description sont pris
  dans son bloc de données structurées schema.org de type JobPosting (JSON-LD) ;
- un texte collé, avec ou sans URL (EXE-82) : la page n'est pas lue. Titre, entreprise
  et lieu viennent de la saisie ; sans titre saisi, l'appelant les fait identifier
  (`ajout/identification.py`) et les pose par `with_identification` avant `fetch`.

Rien ne se devine : un champ absent du bloc, de la saisie ou de l'identification reste
vide, et une offre sans URL envoyée n'a pas d'URL. Aucun appel LLM ici.
"""

import hashlib
import html
import json
import re
from datetime import datetime, timezone

import requests

from orchestrator.job_search.sources._clean import html_to_markdown
from orchestrator.job_search.sources.base import JobOffer, Source
from orchestrator.job_search.sources.fingerprint import fingerprint as _fingerprint

SOURCE = "manuel"
TIMEOUT_SECONDS = 15
_HEADERS = {"User-Agent": "Mozilla/5.0 (job-search; ajout manuel)"}

_LD_JSON_RE = re.compile(
    r"<script[^>]*type\s*=\s*[\"']application/ld\+json[\"'][^>]*>(.*?)</script>",
    re.IGNORECASE | re.DOTALL,
)

# employmentType schema.org → libellé de contrat lu par les filtres durs.
_EMPLOYMENT_NATURE = {"INTERN": "Stage"}


class PageInjoignable(Exception):
    """L'URL n'a pas répondu, ou a répondu un code HTTP d'erreur."""


class JobPostingAbsent(Exception):
    """La page ne porte aucun bloc JobPosting exploitable (absent ou sans titre)."""


def _source_id(key: str) -> str:
    return hashlib.sha256(key.encode()).hexdigest()[:16]


def fetch_html(url: str) -> str:
    try:
        resp = requests.get(
            url, headers=_HEADERS, allow_redirects=True, timeout=TIMEOUT_SECONDS
        )
    except requests.exceptions.RequestException as exc:
        raise PageInjoignable(
            f"La page {url} n'a pas pu être lue ({type(exc).__name__}). "
            "Coller le texte de l'offre."
        ) from exc
    if resp.status_code >= 400:
        raise PageInjoignable(
            f"La page {url} a répondu une erreur HTTP {resp.status_code}. "
            "Coller le texte de l'offre."
        )
    return resp.text


def _is_job_posting(node: dict) -> bool:
    t = node.get("@type")
    return t == "JobPosting" or (isinstance(t, list) and "JobPosting" in t)


def _walk(node: object):
    if isinstance(node, list):
        for item in node:
            yield from _walk(item)
    elif isinstance(node, dict):
        yield node
        if "@graph" in node:
            yield from _walk(node["@graph"])


def find_job_posting(page: str) -> dict | None:
    """Premier bloc JSON-LD de type JobPosting de la page, ou None."""
    for raw in _LD_JSON_RE.findall(page):
        try:
            data = json.loads(raw, strict=False)
        except json.JSONDecodeError:
            continue
        for node in _walk(data):
            if _is_job_posting(node):
                return node
    return None


def _text(value: object) -> str | None:
    if isinstance(value, str):
        return value.strip() or None
    return None


def _company(jp: dict) -> str | None:
    org = jp.get("hiringOrganization")
    if isinstance(org, list):
        org = org[0] if org else None
    if isinstance(org, dict):
        return _text(org.get("name"))
    return _text(org)


def _address_label(address: object) -> str | None:
    if isinstance(address, dict):
        country = address.get("addressCountry")
        if isinstance(country, dict):
            country = country.get("name")
        parts = [
            _text(address.get("addressLocality")),
            _text(address.get("addressRegion")),
            _text(country),
        ]
        return ", ".join(p for p in parts if p) or None
    return _text(address)


def _location(jp: dict) -> str | None:
    places = jp.get("jobLocation")
    if not isinstance(places, list):
        places = [places] if places else []
    labels: list[str] = []
    for place in places:
        address = place.get("address") if isinstance(place, dict) else place
        label = _address_label(address)
        if label and label not in labels:
            labels.append(label)
    return " / ".join(labels) or None


def _employment_types(jp: dict) -> list[str]:
    value = jp.get("employmentType")
    values = value if isinstance(value, list) else [value]
    return [v.strip().upper() for v in values if isinstance(v, str) and v.strip()]


def _is_remote(jp: dict) -> bool:
    value = jp.get("jobLocationType")
    values = value if isinstance(value, list) else [value]
    return any(isinstance(v, str) and v.upper() == "TELECOMMUTE" for v in values)


def _full_time(types: list[str]) -> bool | None:
    if "FULL_TIME" in types:
        return True
    if "PART_TIME" in types:
        return False
    return None


class ManualSource(Source):
    """Une offre, depuis son URL ou depuis un texte collé (URL et titre facultatifs)."""

    def __init__(
        self,
        url: str | None,
        *,
        texte: str | None = None,
        titre: str | None = None,
        entreprise: str | None = None,
        lieu: str | None = None,
    ) -> None:
        self.url = url
        self.texte = texte
        self.titre = titre
        self.entreprise = entreprise
        self.lieu = lieu

    @property
    def source_id(self) -> str:
        """Identifiant stable : l'URL si elle est envoyée, le texte collé sinon."""
        return _source_id(self.url if self.url else self.texte or "")

    @property
    def needs_identification(self) -> bool:
        """Texte collé sans titre saisi : titre, entreprise et lieu restent à identifier."""
        return self.texte is not None and _text(self.titre) is None

    def with_identification(
        self, titre: str, entreprise: str | None, lieu: str | None
    ) -> "ManualSource":
        """La même entrée, titre posé ; entreprise et lieu saisis priment sur ceux
        identifiés."""
        return ManualSource(
            self.url,
            texte=self.texte,
            titre=titre,
            entreprise=_text(self.entreprise) or entreprise,
            lieu=_text(self.lieu) or lieu,
        )

    def fetch(self) -> list[JobOffer]:
        """Rend l'offre. Lève `PageInjoignable` ou `JobPostingAbsent` si l'URL ne
        la donne pas : aucune offre n'est alors produite."""
        if self.texte is not None:
            return [self._from_text()]
        jp = find_job_posting(fetch_html(self.url))
        if jp is None or _text(jp.get("title")) is None:
            raise JobPostingAbsent(
                f"La page {self.url} ne porte pas d'offre lisible (bloc JobPosting "
                "absent ou sans titre). Coller le texte de l'offre."
            )
        return [self._map(jp)]

    def _offer(
        self,
        *,
        title: str,
        company: str | None,
        location: str | None,
        description: str,
        description_raw: str,
        remote: bool = False,
        nature_contract: str | None = None,
        full_time: bool | None = None,
    ) -> JobOffer:
        return JobOffer(
            source=SOURCE,
            source_id=self.source_id,
            fingerprint=_fingerprint(title, company or "", location or ""),
            title=title,
            description=description,
            description_raw=description_raw,
            company=company,
            location=location,
            remote=remote,
            contract_type=None,
            nature_contract=nature_contract,
            full_time=full_time,
            url=self.url,
            fetched_at=datetime.now(timezone.utc),
        )

    def _from_text(self) -> JobOffer:
        texte = self.texte or ""
        return self._offer(
            title=(self.titre or "").strip(),
            company=_text(self.entreprise),
            location=_text(self.lieu),
            description=html_to_markdown(texte),
            description_raw=texte,
        )

    def _map(self, jp: dict) -> JobOffer:
        raw = jp.get("description") if isinstance(jp.get("description"), str) else ""
        # Certains sites échappent le HTML de la description dans le JSON-LD.
        lisible = html.unescape(raw) if "&lt;" in raw else raw
        types = _employment_types(jp)
        nature = next(
            (_EMPLOYMENT_NATURE[t] for t in types if t in _EMPLOYMENT_NATURE), None
        )
        return self._offer(
            title=_text(jp.get("title")) or "",
            company=_company(jp),
            location=_location(jp),
            description=html_to_markdown(lisible),
            description_raw=raw,
            remote=_is_remote(jp),
            nature_contract=nature,
            full_time=_full_time(types),
        )
