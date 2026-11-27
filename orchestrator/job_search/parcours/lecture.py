"""Lecture d'un parcours de candidature (EXE-217, H4) — de l'annonce au bout.

Départ : pour eures, le détail EURES ; pour actiris, la page de l'annonce ; pour
toute autre source, l'adresse de l'offre. Un lien vers une annonce EDITx se
poursuit par l'API d'EDITx. Toute autre adresse se demande par GET, redirections
suivies ; chaque adresse traversée fait un maillon, 8 au plus.

Aucun appel de modèle, aucun navigateur : seulement des lectures de pages, par le
seul point d'appel réseau (`reseau.lire`). Ce qui n'est pas lu reste vide.
"""

from __future__ import annotations

import html
import json
import re
import time
from dataclasses import dataclass, field
from datetime import datetime

import requests

from orchestrator.job_search.parcours import reseau
from orchestrator.job_search.parcours.adresses import (
    Suivi,
    est_accueil,
    nettoyer,
    site,
)

INJOIGNABLE = "injoignable"

PAGE = "page"
MAIL = "mail"
FORMULAIRE = "formulaire"
ACCUEIL = "accueil"
INCONNUE = "inconnue"

MAX_MAILLONS = 8
PAUSE_SECONDES = 0.5

EURES_DETAIL = "https://europa.eu/eures/api/jv-searchengine/public/jv/id/{id}?lang=fr"
EDITX_API = "https://api.editx.eu/en/api/editx/job/{num}"
_EDITX_ANNONCE = re.compile(
    r"^https?://(?:www\.)?editx\.eu/[a-z]{2}/job/(\d+)(?:[/?#]|$)", re.IGNORECASE
)
_HREF = re.compile(r"""href\s*=\s*["']([^"']+)["']""", re.IGNORECASE)
_BLOC_ACTIRIS = "bloc-emploi__apply"
# Le bouton « Postuler » d'Actiris mène à son espace citoyen, jamais à l'employeur (H2).
_BOUTON_ACTIRIS = "my.actiris.brussels"


@dataclass(frozen=True)
class Depart:
    source: str
    source_id: str
    url: str | None


def depart_possible(depart: Depart) -> bool:
    if depart.source == "eures":
        return bool(depart.source_id)
    return bool(depart.url)


@dataclass
class Parcours:
    maillons: list[dict]
    fin_forme: str
    fin_adresse: str | None = None
    cle: str | None = None
    lieu_reel: str | None = None
    code_postal: str | None = None
    provinces: list[str] = field(default_factory=list)
    en_ligne_depuis: str | None = None
    panne: bool = False


class Lecteur:
    """Une vérification : la politesse (une demi-seconde entre deux requêtes vers
    le même site) et la liste des paramètres de suivi."""

    def __init__(self, suivi: Suivi) -> None:
        self.suivi = suivi
        self._derniere: dict[str, float] = {}

    def demander(self, adresse: str) -> reseau.Reponse:
        cle = site(adresse)
        derniere = self._derniere.get(cle)
        if derniere is not None:
            reste = PAUSE_SECONDES - (time.monotonic() - derniere)
            if reste > 0:
                reseau.attendre(reste)
        try:
            return reseau.lire(adresse)
        finally:
            self._derniere[cle] = time.monotonic()


def _json(texte: str) -> object:
    try:
        return json.loads(texte)
    except (TypeError, ValueError):
        return None


def _texte(valeur: object) -> str | None:
    if isinstance(valeur, str) and valeur.strip():
        return valeur.strip()
    return None


def lien_eures(texte: str) -> str | None:
    """Premier href en http des consignes de candidature du détail EURES (H2a)."""
    data = _json(texte)
    profils = data.get("jvProfiles") if isinstance(data, dict) else None
    if not isinstance(profils, dict):
        return None
    for profil in profils.values():
        consignes = (
            profil.get("applicationInstructions") if isinstance(profil, dict) else None
        )
        for consigne in consignes or []:
            for href in _HREF.findall(str(consigne)):
                lien = html.unescape(href).strip()
                if lien.lower().startswith(("http://", "https://")):
                    return lien
    return None


def lien_actiris(page: str) -> str | None:
    """Lien du tableau « Comment postuler ? » d'Actiris (H2b), bouton exclu."""
    debut = page.find(_BLOC_ACTIRIS)
    if debut < 0:
        return None
    bloc = page[debut:]
    table = bloc.find("<table")
    fin = bloc.find("</table>")
    if table < 0 or fin < table:
        return None
    for href in _HREF.findall(bloc[table:fin]):
        lien = html.unescape(href).strip()
        if _BOUTON_ACTIRIS in lien.lower():
            continue
        if lien.lower().startswith(("http://", "https://", "mailto:")):
            return lien
    return None


def _date_editx(valeur: object) -> str | None:
    """onlineDate.value, « AAAA-MM-JJ HH:MM:SS » en UTC (H2c) → « AAAA-MM-JJ »."""
    if not isinstance(valeur, str):
        return None
    try:
        return datetime.strptime(valeur.strip(), "%Y-%m-%d %H:%M:%S").date().isoformat()
    except ValueError:
        return None


class Course:
    """Le parcours d'une offre, maillon par maillon."""

    def __init__(self, depart: Depart, lecteur: Lecteur) -> None:
        self.depart = depart
        self.lecteur = lecteur
        self.maillons: list[dict] = []
        self.editx: str | None = None
        self.panne = False
        self.lieux: dict = {}

    def lire(self) -> Parcours:
        if self.depart.source == "eures":
            rep = self._get(EURES_DETAIL.format(id=self.depart.source_id))
            lien = lien_eures(rep.texte) if rep is not None else None
        elif self.depart.source == "actiris":
            rep = self._get(self.depart.url or "")
            lien = lien_actiris(rep.texte) if rep is not None else None
        else:
            return self._suivre(self.depart.url or "")
        if lien is None:
            return self._fin(INCONNUE)
        return self._suivre(lien)

    def _get(self, adresse: str, nom_site: str | None = None) -> reseau.Reponse | None:
        """Une requête ; ses maillons, ou un maillon « injoignable ». Une API (EURES,
        EDITx) fait un seul maillon, à l'adresse demandée, sous le nom du site."""
        try:
            rep = self.lecteur.demander(adresse)
        except requests.exceptions.RequestException:
            self.panne = True
            self.maillons.append(
                {
                    "site": nom_site or site(adresse),
                    "adresse": adresse,
                    "reponse": INJOIGNABLE,
                }
            )
            return None
        if nom_site is not None:
            code = rep.chaine[-1][1]
            self.maillons.append(
                {"site": nom_site, "adresse": adresse, "reponse": code}
            )
        else:
            for url, code in rep.chaine:
                self.maillons.append(
                    {"site": site(url), "adresse": url, "reponse": code}
                )
        return rep

    def _suivre(self, lien: str) -> Parcours:
        if len(self.maillons) >= MAX_MAILLONS:
            return self._fin(INCONNUE)
        if lien.lower().startswith("mailto:"):
            return self._fin(MAIL, lien[len("mailto:") :].split("?")[0].strip())
        annonce = _EDITX_ANNONCE.match(lien)
        if annonce:
            return self._editx(lien, annonce.group(1))
        if not lien.lower().startswith(("http://", "https://")):
            return self._fin(INCONNUE)
        rep = self._get(lien)
        if rep is None or len(self.maillons) > MAX_MAILLONS:
            return self._fin(INCONNUE)
        arrivee = rep.chaine[-1][0]
        return self._fin(
            ACCUEIL if est_accueil(arrivee) else PAGE, self._propre(arrivee)
        )

    def _editx(self, lien: str, numero: str) -> Parcours:
        self.editx = numero
        rep = self._get(EDITX_API.format(num=numero), nom_site=site(lien))
        data = _json(rep.texte) if rep is not None else None
        if not isinstance(data, dict):
            return self._fin(INCONNUE)
        areas = data.get("areas") if isinstance(data.get("areas"), list) else []
        self.lieux = {
            "lieu_reel": _texte(data.get("locality")),
            "code_postal": _texte(data.get("postalCode")),
            "provinces": [
                a["label"]
                for a in areas
                if isinstance(a, dict) and _texte(a.get("label"))
            ],
            "en_ligne_depuis": _date_editx((data.get("onlineDate") or {}).get("value")),
        }
        genre = data.get("applicationType")
        action = _texte(data.get("applicationAction"))
        if genre == "email" and action:
            return self._fin(MAIL, action.removeprefix("mailto:").strip())
        if genre == "editx":
            return self._fin(FORMULAIRE, self._propre(lien))
        if genre == "url" and action:
            return self._suivre(action)
        return self._fin(INCONNUE)

    def _propre(self, adresse: str) -> str:
        return nettoyer(adresse, self.lecteur.suivi)

    def _fin(self, forme: str, adresse: str | None = None) -> Parcours:
        if forme == PAGE:
            cle = adresse
        elif forme == INCONNUE:
            cle = None
        elif self.editx is not None:
            cle = f"editx:{self.editx}"
        else:
            cle = f"{self.depart.source}:{self.depart.source_id}"
        return Parcours(
            maillons=self.maillons,
            fin_forme=forme,
            fin_adresse=adresse,
            cle=cle,
            panne=self.panne,
            **self.lieux,
        )
