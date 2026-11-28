"""Calcul des files « À postuler » et « À étudier » (EXE-210) — Python pur.

Rien ne s'écrit en base : rang, famille, file et motif se calculent à chaque
lecture, sur les faits déjà extraits (architecture.md §4, 0 LLM au recalcul).
L'état d'une offre vient du module d'états, passé en paramètre (architecture.md,
« Suivi des candidatures »). Du profil personnel, seules les compétences servent,
pour l'atteignabilité.
"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, timezone

from pydantic import ValidationError

from orchestrator.job_search.a_postuler.lieu import (
    LieuJuge,
    ParcoursFile,
    juger_lieu,
    marques_parcours,
)
from orchestrator.job_search.a_postuler.regles import (
    Regles,
    premier_mot,
    premiere_sous_chaine,
)
from orchestrator.job_search.matching.profile import Profile
from orchestrator.job_search.scoring.aliases import AliasTable
from orchestrator.job_search.scoring.attainability import compute_attainability
from orchestrator.job_search.sources.base import ExtractedFacts, RoleLevel
from orchestrator.job_search.suivi import etats

IA = "IA et automatisation"
DEVELOPPEUR = "Développeur"
DATA = "Data et analyse"

PRINCIPALE = "principale"
A_ETUDIER = "a_etudier"

FILE_DE_FAMILLE = {IA: PRINCIPALE, DEVELOPPEUR: PRINCIPALE, DATA: A_ETUDIER}
# Dans la file principale, « IA et automatisation » passe avant « Développeur ».
_ORDRE_FAMILLE = {IA: 0, DEVELOPPEUR: 1, DATA: 0}

# Groupes de la file « À étudier » (EXE-221) : la famille décide d'abord, puis le
# niveau extrait (niveaux de `niveaux_a_etudier`, profiles/a_postuler.yaml).
TROP_SENIOR = "trop senior ?"
INTERESSANT = "est-ce intéressant ?"
GROUPES = (TROP_SENIOR, INTERESSANT)

MARQUE_NEERLANDAIS = "néerlandais en atout"
# Une offre sortie par la vérification et remise à la main (EXE-223).
MARQUE_REMISE = "remise à la main"

# Motifs, dans l'ordre où ils sont cherchés (H5) : le premier rencontré est rendu.
DEJA_TRAITEE = "déjà traitée"
FILTREE = "filtrée à l'ingestion"
PAS_DE_FAITS = "pas de faits"
# LIEU, le motif de lieu, vit avec sa règle (a_postuler/lieu.py).
FREELANCE = "freelance"
STAGE = "stage ou alternance"
EXPIREE = "annonce expirée"
ANNONCE_NL = "annonce en néerlandais"
NL_EXIGE = "néerlandais exigé"
ROLE = "rôle lead ou manager"
SENIOR = "titre senior"
FORMATEUR = "formateur"
ROBOTIQUE = "robotique"
FAMILLE = "famille"
CLOUD = "cloud ou réseau"
DOUBLON = "doublon"

_IMPORTANCES_FORTES = {"core", "required"}
_FIN_DE_PHRASE = re.compile(r"[.!?\n]+")


@dataclass(frozen=True)
class OffreLue:
    """Ce que les files lisent d'une offre en base."""

    id: int
    titre: str
    entreprise: str
    lieu: str
    source: str
    url: str
    contrat: str
    recuperee: str | None
    description: str
    langue_annonce: str | None
    faits_json: str | None
    filtree: bool


@dataclass
class Ligne:
    id: int
    titre: str
    entreprise: str
    lieu: str
    source: str
    url: str
    contrat: str
    recuperee: str | None
    jours: int | None
    famille: str
    origine_famille: str
    niveau: str
    marques: list[str]
    atteignabilite: float = 0.0
    technos_connues: list[str] = field(default_factory=list)
    technos_absentes: list[str] = field(default_factory=list)
    rang: int = 0
    # Groupe de la file « À étudier » (EXE-221) ; None dans la file principale.
    groupe: str | None = None
    # Les offres de même clé regroupées sous cette ligne (EXE-219) : id et source.
    jumelles: list[dict] = field(default_factory=list)
    # Ce que dit le parcours de candidature (EXE-220).
    fin_forme: str | None = None
    fin_adresse: str | None = None
    en_ligne_depuis: str | None = None
    verifiee_le: str | None = None


@dataclass
class Classement:
    principale: list[Ligne]
    a_etudier: list[Ligne]
    motifs: dict[int, str]
    # Pour un motif « doublon » ou « déjà traitée » venu d'une autre offre
    # (EXE-219, H4) : l'id et l'état de cette offre.
    meme_offre_que: dict[int, dict] = field(default_factory=dict)

    def file(self, nom: str) -> list[Ligne]:
        return self.principale if nom == PRINCIPALE else self.a_etudier

    def hors_files(self) -> dict[str, int]:
        return dict(Counter(self.motifs.values()))


@dataclass
class _Candidate:
    offre: OffreLue
    faits: ExtractedFacts
    famille: str
    origine: str
    marques: list[str]
    lieu: str
    parcours: ParcoursFile | None = None
    remise: bool = False


# ---------------------------------------------------------------------------
# Lecture d'une offre
# ---------------------------------------------------------------------------


def lire_faits(faits_json: str | None) -> ExtractedFacts | None:
    """Faits extraits, ou None s'il n'y en a pas ou si aucune techno n'est extraite."""
    if not faits_json:
        return None
    try:
        faits = ExtractedFacts.model_validate_json(faits_json)
    except ValidationError:
        return None
    return faits if faits.techs_required else None


def jours_depuis(recuperee: str | None, maintenant: datetime) -> int | None:
    """Jours entiers entre la récupération et maintenant (H6)."""
    if not recuperee:
        return None
    try:
        date = datetime.fromisoformat(recuperee)
    except ValueError:
        return None
    if date.tzinfo is None:
        date = date.replace(tzinfo=timezone.utc)
    return (maintenant - date).days


def motif_neerlandais(
    faits: ExtractedFacts, description: str, regles: Regles
) -> tuple[str | None, list[str]]:
    langues = " ".join(faits.langues_requises)
    if not premiere_sous_chaine(regles.neerlandais, langues):
        return None, []
    for phrase in _FIN_DE_PHRASE.split(description.casefold()):
        if premiere_sous_chaine(regles.neerlandais, phrase) and premiere_sous_chaine(
            regles.tournures_atout, phrase
        ):
            return None, [MARQUE_NEERLANDAIS]
    return NL_EXIGE, []


def _technos_fortes(faits: ExtractedFacts) -> list[str]:
    return [
        t.name.casefold()
        for t in faits.techs_required
        if t.importance in _IMPORTANCES_FORTES
    ]


def _famille_ia(faits: ExtractedFacts, titre: str, regles: Regles) -> str | None:
    """Ce qui range l'offre en « IA et automatisation » (règle 1 de H4), ou None."""
    domaine = faits.domain
    technique = domaine in regles.domaines_techniques
    technos = _technos_fortes(faits)
    ia = [t for t in technos if regles.est_ia(t)]
    automatisation = [t for t in technos if regles.est_automatisation(t)]
    if domaine in regles.domaines_ia:
        return f"domaine {domaine}"
    if len(ia) >= 2:
        return "technos IA : " + ", ".join(ia)
    if ia and technique:
        return f"techno IA {ia[0]} et domaine {domaine}"
    if automatisation:
        return "techno d'automatisation : " + ", ".join(automatisation)
    mot = premiere_sous_chaine(regles.titre_automatisation, titre)
    if mot and technique:
        return f"titre « {mot} » et domaine {domaine}"
    return None


def famille(
    faits: ExtractedFacts, titre: str, regles: Regles
) -> tuple[str | None, str]:
    """(famille, ce qui l'a donnée), dans l'ordre de H4 ; (None, "") = dehors."""
    origine = _famille_ia(faits, titre, regles)
    if origine:
        return IA, origine
    mot = premier_mot(regles.titre_analyse, titre)
    if mot:
        return DATA, f"titre « {mot} »"
    if faits.domain in regles.domaines_developpeur:
        return DEVELOPPEUR, f"domaine {faits.domain}"
    if faits.domain in regles.domaines_data:
        return DATA, f"domaine {faits.domain}"
    return None, ""


def _motif_titre(titre: str, regles: Regles) -> str | None:
    """Senior, formateur, robotique — dans l'ordre de H5."""
    for motif, mots in (
        (SENIOR, regles.titre_senior),
        (FORMATEUR, regles.titre_formateur),
        (ROBOTIQUE, regles.titre_robotique),
    ):
        if premier_mot(mots, titre):
            return motif
    return None


def _motif_avant_faits(
    offre: OffreLue, etat: str, faits: ExtractedFacts | None
) -> str | None:
    if etat != etats.A_TRIER:
        return DEJA_TRAITEE
    if offre.filtree:
        return FILTREE
    if faits is None:
        return PAS_DE_FAITS
    return None


def _juger_lieu(
    offre: OffreLue, parcours: ParcoursFile | None, regles: Regles, remise: bool
) -> LieuJuge:
    """Le lieu jugé ; pour une offre remise à la main, le motif « lieu » tiré du
    lieu réel ne s'applique plus, celui du lieu d'annonce reste (EXE-223, H3)."""
    lieu = juger_lieu(offre.lieu, parcours, regles)
    if remise and lieu.motif and not juger_lieu(offre.lieu, None, regles).motif:
        return LieuJuge(lieu.affiche, None, lieu.marques)
    return lieu


def evaluer(
    offre: OffreLue,
    etat: str,
    expiree: bool,
    regles: Regles,
    parcours: ParcoursFile | None = None,
    remise: bool = False,
) -> _Candidate | str:
    """La candidate d'une offre qui passe les refus, ou son motif (H5). Le lieu
    se juge sur le lieu réel du parcours quand il en donne un (EXE-220). Une offre
    remise à la main n'est plus tenue pour expirée (EXE-223)."""
    faits = lire_faits(offre.faits_json)
    motif = _motif_avant_faits(offre, etat, faits)
    if motif or faits is None:
        return motif or PAS_DE_FAITS
    lieu = _juger_lieu(offre, parcours, regles, remise)
    if lieu.motif:
        return lieu.motif
    if offre.contrat.casefold().strip() in regles.contrats_refuses:
        return FREELANCE
    if premier_mot(regles.titre_stage, offre.titre):
        return STAGE
    if expiree and not remise:
        return EXPIREE
    if (offre.langue_annonce or "").casefold() == "nl":
        return ANNONCE_NL
    motif, marques_nl = motif_neerlandais(faits, offre.description, regles)
    if motif:
        return motif
    if faits.role_level in (RoleLevel.lead, RoleLevel.manager):
        return ROLE
    motif = _motif_titre(offre.titre, regles)
    if motif:
        return motif
    nom, origine = famille(faits, offre.titre, regles)
    if nom is None:
        return FAMILLE
    if nom != IA and premier_mot(regles.titre_cloud_reseau, offre.titre):
        return CLOUD
    marques = lieu.marques + marques_nl + ([MARQUE_REMISE] if remise else [])
    return _Candidate(
        offre, faits, nom, origine, marques, lieu.affiche, parcours, remise
    )


# ---------------------------------------------------------------------------
# Doublons, lignes et ordre
# ---------------------------------------------------------------------------


def cle_doublon(offre: OffreLue, regles: Regles) -> tuple[str, str]:
    """Entreprise et titre, sans casse, sans espaces en trop ni marqueurs H/F (H6)."""
    titre = offre.titre.casefold()
    if regles.marqueurs_titre is not None:
        titre = regles.marqueurs_titre.sub(" ", titre)
    return (
        " ".join(offre.entreprise.casefold().split()),
        " ".join(titre.split()),
    )


class _Groupes:
    """Regroupement des candidates en postes (EXE-219, H4). Deux clés différentes
    ne se rejoignent jamais ; une candidate sans clé rejoint par entreprise et titre."""

    def __init__(self, cles: list[str | None]) -> None:
        self.parent = list(range(len(cles)))
        self.cle = dict(enumerate(cles))

    def racine(self, i: int) -> int:
        while self.parent[i] != i:
            self.parent[i] = self.parent[self.parent[i]]
            i = self.parent[i]
        return i

    def unir(self, i: int, j: int) -> bool:
        ri, rj = self.racine(i), self.racine(j)
        if ri == rj:
            return True
        ki, kj = self.cle[ri], self.cle[rj]
        if ki and kj and ki != kj:
            return False
        self.parent[rj] = ri
        self.cle[ri] = ki or kj
        return True


def _groupes(
    candidates: list[_Candidate], cles: dict[int, str], regles: Regles
) -> list[list[_Candidate]]:
    """Les postes, dans l'ordre de leur première candidate : même clé d'abord, puis
    même entreprise et même titre quand l'une des deux n'a pas de clé."""
    cles_c = [cles.get(c.offre.id) for c in candidates]
    g = _Groupes(cles_c)
    par_cle: dict[str, int] = {}
    for i, cle in enumerate(cles_c):
        if cle is not None:
            g.unir(par_cle.setdefault(cle, i), i)
    par_poste: dict[tuple[str, str], list[int]] = {}
    for i, c in enumerate(candidates):
        reps = par_poste.setdefault(cle_doublon(c.offre, regles), [])
        if not any(g.unir(r, i) for r in reps):
            reps.append(i)
    postes: dict[int, list[_Candidate]] = {}
    for i, c in enumerate(candidates):
        postes.setdefault(g.racine(i), []).append(c)
    return list(postes.values())


def _sans_doublons(
    candidates: list[_Candidate],
    cles: dict[int, str],
    regles: Regles,
    classement: Classement,
) -> list[tuple[_Candidate, list[_Candidate]]]:
    """Garde, par poste, l'offre récupérée le plus récemment, avec ses jumelles ;
    les autres sont dehors, au motif « doublon ». Une offre remise à la main garde
    sa ligne, seule (EXE-223)."""
    gardees = [(c, []) for c in candidates if c.remise]
    autres_candidates = [c for c in candidates if not c.remise]
    for poste in _groupes(autres_candidates, cles, regles):
        gardee = max(poste, key=lambda c: c.offre.recuperee or "")
        autres = [c for c in poste if c is not gardee]
        for c in autres:
            classement.motifs[c.offre.id] = DOUBLON
            classement.meme_offre_que[c.offre.id] = {
                "id": gardee.offre.id,
                "etat": etats.A_TRIER,
            }
        gardees.append((gardee, autres))
    return gardees


def _traitees_par_cle(
    offres: list[OffreLue], etats_de: dict[int, str], cles: dict[int, str]
) -> dict[str, dict]:
    """Par clé, la première offre déjà traitée qui la porte : son id et son état."""
    traitees: dict[str, dict] = {}
    for o in offres:
        cle, etat = cles.get(o.id), etats_de[o.id]
        if cle is not None and etat != etats.A_TRIER:
            traitees.setdefault(cle, {"id": o.id, "etat": etat})
    return traitees


def _ligne(
    c: _Candidate,
    jumelles: list[_Candidate],
    profil: Profile,
    alias: AliasTable,
    regles: Regles,
    maintenant: datetime,
) -> Ligne:
    attein = compute_attainability(c.faits, profil, alias)
    o = c.offre
    p = c.parcours
    return Ligne(
        id=o.id,
        titre=o.titre,
        entreprise=o.entreprise,
        lieu=c.lieu,
        source=o.source,
        url=o.url,
        contrat=o.contrat,
        recuperee=o.recuperee,
        jours=jours_depuis(o.recuperee, maintenant),
        famille=c.famille,
        origine_famille=c.origine,
        niveau=c.faits.seniority_required.value,
        marques=c.marques + marques_parcours(p, regles, maintenant),
        atteignabilite=attein.score,
        technos_connues=attein.techs_matched,
        technos_absentes=attein.techs_missing,
        jumelles=[{"id": j.offre.id, "source": j.offre.source} for j in jumelles],
        fin_forme=p.fin_forme if p else None,
        fin_adresse=p.fin_adresse if p else None,
        en_ligne_depuis=p.en_ligne_depuis if p else None,
        verifiee_le=p.verifiee_le if p else None,
    )


def groupe(ligne: Ligne, regles: Regles) -> str | None:
    """Le groupe de « À étudier » où va la ligne, ou None pour la file principale :
    un poste data reste « est-ce intéressant ? » quel que soit son niveau (H3)."""
    if FILE_DE_FAMILLE[ligne.famille] == A_ETUDIER:
        return INTERESSANT
    if ligne.niveau in regles.niveaux_a_etudier:
        return TROP_SENIOR
    return None


def est_recente(ligne: Ligne, regles: Regles) -> bool:
    return ligne.jours is not None and ligne.jours <= regles.jours_recents


def _cle_ordre(ligne: Ligne, regles: Regles) -> tuple:
    """Tranche d'âge, famille, groupe de niveau, atteignabilité (critères 38-42)."""
    return (
        0 if est_recente(ligne, regles) else 1,
        _ORDRE_FAMILLE[ligne.famille],
        0 if ligne.niveau in regles.niveaux_premier_groupe else 1,
        -ligne.atteignabilite,
        ligne.id,
    )


def _cle_ordre_a_etudier(ligne: Ligne, regles: Regles) -> tuple:
    """Tranche d'âge, puis atteignabilité (EXE-221, H3)."""
    return (0 if est_recente(ligne, regles) else 1, -ligne.atteignabilite, ligne.id)


def _ordonner(lignes: list[Ligne], regles: Regles, cle=_cle_ordre) -> list[Ligne]:
    lignes = sorted(lignes, key=lambda ligne: cle(ligne, regles))
    for rang, ligne in enumerate(lignes, start=1):
        ligne.rang = rang
    return lignes


def classer(
    offres: list[OffreLue],
    etats_stockes: dict[int, str],
    expirees: set[int],
    regles: Regles,
    profil: Profile,
    alias: AliasTable,
    cles: dict[int, str],
    maintenant: datetime | None = None,
    parcours: dict[int, ParcoursFile] | None = None,
    remises: set[int] | None = None,
) -> Classement:
    """Les deux files, rangées, et le motif de chaque offre laissée dehors.

    `cles` : la clé de comparaison du parcours lu de chaque offre qui en a une
    (EXE-219). Une offre à trier dont la clé est celle d'une offre déjà traitée
    sort au motif « déjà traitée », avant toute autre règle. `parcours` : ce que
    dit le parcours de chaque offre, pour son lieu réel et ses marques (EXE-220).
    `remises` : les offres remises à la main, que l'expiration, le lieu réel, le
    doublon et la clé d'une offre déjà traitée ne sortent plus (EXE-223, H3)."""
    maintenant = maintenant or datetime.now(timezone.utc)
    parcours = parcours or {}
    remises = remises or set()
    classement = Classement(principale=[], a_etudier=[], motifs={})
    etats_de = {o.id: etats_stockes.get(o.id, etats.A_TRIER) for o in offres}
    traitees = _traitees_par_cle(offres, etats_de, cles)
    candidates: list[_Candidate] = []
    for offre in offres:
        etat = etats_de[offre.id]
        remise = offre.id in remises
        soeur = (
            traitees.get(cles.get(offre.id, ""))
            if etat == etats.A_TRIER and not remise
            else None
        )
        resultat = (
            DEJA_TRAITEE
            if soeur
            else evaluer(
                offre,
                etat,
                offre.id in expirees,
                regles,
                parcours.get(offre.id),
                remise,
            )
        )
        if soeur:
            classement.meme_offre_que[offre.id] = soeur
        if isinstance(resultat, str):
            classement.motifs[offre.id] = resultat
        else:
            candidates.append(resultat)
    lignes = [
        _ligne(c, jumelles, profil, alias, regles, maintenant)
        for c, jumelles in _sans_doublons(candidates, cles, regles, classement)
    ]
    for li in lignes:
        li.groupe = groupe(li, regles)
    classement.principale = _ordonner(
        [li for li in lignes if li.groupe is None], regles
    )
    classement.a_etudier = _ordonner(
        [li for li in lignes if li.groupe is not None], regles, _cle_ordre_a_etudier
    )
    return classement
