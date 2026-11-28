"""Les offres sorties des files par la vérification (EXE-223) — Python pur.

Une offre est sortie par la vérification quand elle serait dans une file si l'on
ignorait tout ce que la vérification a écrit (verdicts d'expiration, parcours,
clés de comparaison), et qu'elle n'y est pas (H3). Les files se calculent donc
deux fois, avec et sans ce que la vérification a écrit ; rien ne s'écrit en base.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from orchestrator.job_search.a_postuler import calcul
from orchestrator.job_search.a_postuler.lieu import ParcoursFile
from orchestrator.job_search.a_postuler.regles import Regles
from orchestrator.job_search.matching.profile import Profile
from orchestrator.job_search.parcours.lecture import ACCUEIL, FORMULAIRE, PAGE
from orchestrator.job_search.scoring.aliases import AliasTable

# Les fins de parcours dont l'adresse sert de preuve (H3) ; sinon, l'annonce.
_FINS_PREUVES = {PAGE, FORMULAIRE, ACCUEIL}


@dataclass(frozen=True)
class Entrees:
    """Ce que les files lisent en base."""

    offres: list[calcul.OffreLue]
    etats: dict[int, str]
    expirees: set[int]
    cles: dict[int, str]
    parcours: dict[int, ParcoursFile]
    remises: set[int] = field(default_factory=set)


@dataclass(frozen=True)
class Verification:
    """Ce que la vérification a gardé d'une offre, hors des files."""

    fermeture: dict | None = None
    lu_le: str | None = None
    verifiee_le: str | None = None
    expiration_le: str | None = None


def classer(
    e: Entrees,
    regles: Regles,
    profil: Profile,
    alias: AliasTable,
    maintenant: datetime | None = None,
) -> calcul.Classement:
    """Les files telles qu'elles s'affichent."""
    return calcul.classer(
        e.offres,
        e.etats,
        e.expirees,
        regles,
        profil,
        alias,
        e.cles,
        maintenant,
        parcours=e.parcours,
        remises=e.remises,
    )


def _sans_verification(
    e: Entrees, regles: Regles, profil: Profile, alias: AliasTable, maintenant
) -> calcul.Classement:
    return calcul.classer(
        e.offres, e.etats, set(), regles, profil, alias, {}, maintenant, parcours={}
    )


def _preuve(offre: calcul.OffreLue, p: ParcoursFile | None) -> str:
    if p is not None and p.fin_forme in _FINS_PREUVES and p.fin_adresse:
        return p.fin_adresse
    return offre.url


def _meme_offre_que(
    classement: calcul.Classement,
    offre_id: int,
    motif: str,
    par_id: dict[int, calcul.OffreLue],
) -> dict | None:
    autre = classement.meme_offre_que.get(offre_id)
    if autre is None:
        return None
    return {
        "id": autre["id"],
        "titre": par_id[autre["id"]].titre,
        "etat": None if motif == calcul.DOUBLON else autre["etat"],
    }


def _sortie(
    offre: calcul.OffreLue,
    file: str,
    reel: calcul.Classement,
    e: Entrees,
    v: Verification,
    par_id: dict[int, calcul.OffreLue],
) -> dict:
    motif = reel.motifs[offre.id]
    p = e.parcours.get(offre.id)
    fermeture = v.fermeture or {}
    return {
        "id": offre.id,
        "titre": offre.titre,
        "entreprise": offre.entreprise,
        "source": offre.source,
        "file": file,
        "motif": motif,
        "signe": fermeture.get("signe"),
        "site": fermeture.get("site"),
        "code": fermeture.get("code"),
        "phrase": fermeture.get("phrase"),
        "lieu_reel": p.lieu_reel if p else None,
        "code_postal": p.code_postal if p else None,
        "meme_offre_que": _meme_offre_que(reel, offre.id, motif, par_id),
        "preuve": _preuve(offre, p),
        "verifiee_le": v.verifiee_le or v.lu_le or v.expiration_le,
    }


def sorties(
    e: Entrees,
    verifications: dict[int, Verification],
    regles: Regles,
    profil: Profile,
    alias: AliasTable,
    maintenant: datetime | None = None,
) -> list[dict]:
    """Les sorties, de la vérification la plus récente à la plus ancienne."""
    reel = classer(e, regles, profil, alias, maintenant)
    base = _sans_verification(e, regles, profil, alias, maintenant)
    dans_les_files = {li.id for li in reel.principale + reel.a_etudier}
    par_id = {o.id: o for o in e.offres}
    rendues = [
        _sortie(
            par_id[li.id],
            nom,
            reel,
            e,
            verifications.get(li.id, Verification()),
            par_id,
        )
        for nom in (calcul.PRINCIPALE, calcul.A_ETUDIER)
        for li in base.file(nom)
        if li.id not in dans_les_files and li.id in reel.motifs
    ]
    rendues.sort(key=lambda s: s["id"])
    rendues.sort(key=lambda s: s["verifiee_le"] or "", reverse=True)
    return rendues
