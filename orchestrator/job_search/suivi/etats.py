"""Module d'états du suivi des candidatures (TCK-311, EXE-193) — Python pur,
sans FastAPI ni sqlite3 (architecture.md, « Suivi des candidatures »).

Un seul axe d'états stockés, qui mêle le tri (à trier / retenue / écartée) et,
une fois retenue, l'étape de la candidature. « Prête à l'envoi » n'est PAS un
état stocké : elle se déduit, à l'affichage, de l'état « retenue » et du statut
des pièces (critère 6) — c'est pourquoi `appliquer` prend `cv_pret`/`lettre_pret`
en paramètres plutôt que de les ignorer.

La revue hors périmètre (confirmé / faux positif) est un axe à part, qui ne vit
pas ici : elle ne change jamais cet état (architecture.md, section TCK-311).
"""

from dataclasses import dataclass, field
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

# Fuseau de référence pour toute date d'effet de `marquer_envoyee` (EXE-197,
# H3/H4) : le jour compté est celui de Bruxelles, jamais celui d'UTC.
FUSEAU_BRUXELLES = ZoneInfo("Europe/Brussels")

# ---------------------------------------------------------------------------
# États stockés
# ---------------------------------------------------------------------------

A_TRIER = "a_trier"
ECARTEE = "ecartee"
RETENUE = "retenue"
CANDIDATURE_ENVOYEE = "candidature_envoyee"
ENTRETIEN = "entretien"
OFFRE_RECUE = "offre_recue"
REFUSEE = "refusee"
SANS_SUITE = "sans_suite"
ABANDONNEE = "abandonnee"

ETATS = {
    A_TRIER,
    ECARTEE,
    RETENUE,
    CANDIDATURE_ENVOYEE,
    ENTRETIEN,
    OFFRE_RECUE,
    REFUSEE,
    SANS_SUITE,
    ABANDONNEE,
}

# États stockés qui font partie de la famille « retenue » (tri = retenue),
# y compris toutes les étapes qui suivent la rétention.
ETATS_RETENUS = {
    RETENUE,
    CANDIDATURE_ENVOYEE,
    ENTRETIEN,
    OFFRE_RECUE,
    REFUSEE,
    SANS_SUITE,
    ABANDONNEE,
}

# Étape affichée dérivée, jamais stockée (critère 6).
PRETE_A_L_ENVOI = "prete_a_l_envoi"

# ---------------------------------------------------------------------------
# Gestes
# ---------------------------------------------------------------------------

RETENIR = "retenir"
ECARTER = "ecarter"
REMETTRE_A_TRIER = "remettre_a_trier"
MARQUER_ENVOYEE = "marquer_envoyee"
RELANCER = "relancer"
ENTRETIEN_GESTE = "entretien"
OFFRE_RECUE_GESTE = "offre_recue"
REFUSER = "refuser"
SANS_SUITE_GESTE = "sans_suite"
ABANDONNER = "abandonner"
ANNULER = "annuler"

# Table des transitions (H4 du ticket) — une ligne par état stocké, les gestes
# qui en partent et l'état d'arrivée. `annuler` n'y figure jamais : il ne
# dépend pas de l'état courant mais de l'historique (cf. `storage.py`).
TRANSITIONS: dict[str, dict[str, str]] = {
    A_TRIER: {
        RETENIR: RETENUE,
        ECARTER: ECARTEE,
    },
    ECARTEE: {
        REMETTRE_A_TRIER: A_TRIER,
    },
    RETENUE: {
        MARQUER_ENVOYEE: CANDIDATURE_ENVOYEE,
        ABANDONNER: ABANDONNEE,
    },
    CANDIDATURE_ENVOYEE: {
        RELANCER: CANDIDATURE_ENVOYEE,
        ENTRETIEN_GESTE: ENTRETIEN,
        REFUSER: REFUSEE,
        SANS_SUITE_GESTE: SANS_SUITE,
        ABANDONNER: ABANDONNEE,
    },
    ENTRETIEN: {
        ENTRETIEN_GESTE: ENTRETIEN,
        RELANCER: ENTRETIEN,
        OFFRE_RECUE_GESTE: OFFRE_RECUE,
        REFUSER: REFUSEE,
        SANS_SUITE_GESTE: SANS_SUITE,
        ABANDONNER: ABANDONNEE,
    },
    OFFRE_RECUE: {},
    REFUSEE: {},
    SANS_SUITE: {},
    ABANDONNEE: {},
}

# Tous les gestes de la table, `annuler` compris (EXE-200, critère 14) — ordre
# d'affichage, pas de signification métier.
TOUS_GESTES = [
    RETENIR,
    ECARTER,
    REMETTRE_A_TRIER,
    MARQUER_ENVOYEE,
    RELANCER,
    ENTRETIEN_GESTE,
    OFFRE_RECUE_GESTE,
    REFUSER,
    SANS_SUITE_GESTE,
    ABANDONNER,
    ANNULER,
]

# Libellés humains (EXE-200, critère 17) — pour les messages construits par
# `gestes_avec_etat` et les routes qui refusent un geste. N'affecte jamais le
# message de `GesteRefuse`/`PiecesNonPretes` elles-mêmes (compatibilité des
# tests EXE-193 qui en lisent le code interne).
LIBELLES_ETATS = {
    A_TRIER: "à trier",
    ECARTEE: "écartée",
    RETENUE: "retenue",
    CANDIDATURE_ENVOYEE: "candidature envoyée",
    ENTRETIEN: "entretien",
    OFFRE_RECUE: "offre reçue",
    REFUSEE: "refusée",
    SANS_SUITE: "sans suite",
    ABANDONNEE: "abandonnée",
}

LIBELLES_GESTES = {
    RETENIR: "Retenir",
    ECARTER: "Écarter",
    REMETTRE_A_TRIER: "Remettre à trier",
    MARQUER_ENVOYEE: "Marquer envoyée",
    RELANCER: "Relancer",
    ENTRETIEN_GESTE: "Entretien",
    OFFRE_RECUE_GESTE: "Offre reçue",
    REFUSER: "Refuser",
    SANS_SUITE_GESTE: "Sans suite",
    ABANDONNER: "Abandonner",
    ANNULER: "Annuler le dernier geste",
}


class GesteRefuse(Exception):
    """Le geste n'est pas permis depuis cet état (critère 2) — nomme les deux,
    par leur libellé, jamais par leur code interne (EXE-194, critère 20)."""

    def __init__(self, etat: str, geste: str):
        self.etat = etat
        self.geste = geste
        libelle_geste = LIBELLES_GESTES.get(geste, geste)
        libelle_etat = LIBELLES_ETATS.get(etat, etat)
        super().__init__(
            f"Le geste « {libelle_geste} » n'est pas permis depuis l'étape « {libelle_etat} »"
        )


class PiecesNonPretes(Exception):
    """Message humain de l'avertissement de `marquer_envoyee` quand une pièce
    n'est pas prête (EXE-197, critères 9-10). Depuis EXE-197, ce n'est plus
    une cause de refus : `appliquer` ne la lève plus (critère 1) ;
    `gestes_avec_etat` l'instancie seulement pour son message, jamais levée.
    Depuis EXE-196, `lettre_sans=True` (décision « Sans lettre ») compte comme
    la lettre satisfaite : elle ne manque jamais dans le message dans ce cas."""

    def __init__(self, cv_pret: bool, lettre_pret: bool, lettre_sans: bool = False):
        self.cv_pret = cv_pret
        self.lettre_pret = lettre_pret
        self.lettre_sans = lettre_sans
        manquantes = pieces_manquantes_pour_envoi(
            cv_pret=cv_pret, lettre_pret=lettre_pret, lettre_sans=lettre_sans
        )
        if manquantes == ["cv", "lettre"]:
            quoi = "Le CV et la lettre ne sont pas prêts"
        elif manquantes == ["cv"]:
            quoi = "Le CV n'est pas prêt"
        else:
            quoi = "La lettre n'est pas prête"
        super().__init__(f"{quoi} : impossible de marquer la candidature envoyée")


class DateEffetFuture(Exception):
    """`effet_at` de `marquer_envoyee` postérieur au jour de Bruxelles (EXE-197,
    critère 4) — seul `marquer_envoyee` porte cette règle (H3 du ticket)."""

    def __init__(self, effet_at: str, aujourd_hui: str):
        self.effet_at = effet_at
        self.aujourd_hui = aujourd_hui
        super().__init__(
            f"La date « {effet_at} » est postérieure à aujourd'hui "
            f"({aujourd_hui}, heure de Bruxelles) : impossible de marquer la "
            "candidature envoyée à l'avance."
        )


def gestes_permis(etat: str) -> list[str]:
    """Gestes de la table pour cet état, sans `annuler` (dépend de l'historique,
    cf. `storage.permis_annuler`)."""
    return sorted(TRANSITIONS.get(etat, {}))


def pieces_pretes_pour_envoi(
    *, cv_pret: bool, lettre_pret: bool, lettre_sans: bool
) -> bool:
    """Condition unique « prête à l'envoi » (EXE-196, critères 1-5, H4) : CV
    Prêt, et lettre Prête ou décision « Sans lettre ». Seul endroit qui
    l'écrit — `gestes_avec_etat`, `etape_affichee` ci-dessous, et
    `api/offers.py::_tout_telecharger`,
    `orchestrator/job_search/pieces.py::prete_a_l_envoi` la lisent ici.
    Depuis EXE-197 (critère 1), elle ne gate plus `marquer_envoyee` — voir
    `pieces_manquantes_pour_envoi` pour l'avertissement qui la remplace."""
    return cv_pret and (lettre_pret or lettre_sans)


def pieces_manquantes_pour_envoi(
    *, cv_pret: bool, lettre_pret: bool, lettre_sans: bool
) -> list[str]:
    """Codes des pièces qui manquent pour l'envoi, dans cet ordre (EXE-197,
    critère 10) — même condition que `pieces_pretes_pour_envoi`, jamais
    recalculée ailleurs. Liste vide si tout est prêt."""
    manquantes = []
    if not cv_pret:
        manquantes.append("cv")
    if not (lettre_pret or lettre_sans):
        manquantes.append("lettre")
    return manquantes


def gestes_permis_effectifs(
    etat: str,
    *,
    cv_pret: bool,
    lettre_pret: bool,
    annulable: bool,
    lettre_sans: bool = False,
) -> list[str]:
    """Gestes réellement applicables là, tout de suite (critère 12, EXE-200) :
    ajoute `annuler` si l'historique le permet. Depuis EXE-197 (critère 1),
    `marquer_envoyee` n'est plus exclu pour des pièces non prêtes — ce n'est
    plus qu'un avertissement (`gestes_avec_etat`). `cv_pret`/`lettre_pret`/
    `lettre_sans` restent dans la signature pour ne pas changer l'appel
    depuis `storage.gestes_permis` et `api/offers.py`."""
    permis = gestes_permis(etat)
    if annulable:
        permis.append(ANNULER)
    return permis


def maintenant() -> datetime:
    """Horloge du module — remplacée directement dans les tests (EXE-197,
    H5 : ni freezegun ni time-machine ne sont installés)."""
    return datetime.now(timezone.utc)


def aujourd_hui_bruxelles(maintenant_utc: datetime | None = None) -> str:
    """Jour de Bruxelles au format ISO `YYYY-MM-DD` (EXE-197, critères 2, 4,
    5) — jamais le jour UTC (mutant E2 : refusé à 00:30 heure de Bruxelles si
    compté en UTC)."""
    now = maintenant_utc if maintenant_utc is not None else maintenant()
    return now.astimezone(FUSEAU_BRUXELLES).date().isoformat()


def normaliser_effet_marquer_envoyee(effet_at: str | None) -> str:
    """Date d'effet de `marquer_envoyee` (EXE-197, H3, critères 2, 4, 5, 7) :
    absente → maintenant ; une date seule (sans heure, saisie au champ date
    du navigateur) → midi, heure de Bruxelles, de CE jour calendaire, en ISO
    UTC (critère 7) ; toute date dont le jour de Bruxelles est postérieur à
    aujourd'hui, jour de Bruxelles → lève `DateEffetFuture` (critère 4). Ne
    s'applique qu'à `marquer_envoyee` — les autres gestes gardent leur date
    d'effet telle qu'elle est reçue (H3)."""
    now = maintenant()
    if effet_at is None:
        return now.isoformat()
    parsed = datetime.fromisoformat(effet_at)
    if parsed.tzinfo is None:
        jour = parsed.date()
        effectif = datetime(
            jour.year, jour.month, jour.day, 12, tzinfo=FUSEAU_BRUXELLES
        )
    else:
        effectif = parsed
    aujourdhui = aujourd_hui_bruxelles(now)
    if effectif.astimezone(FUSEAU_BRUXELLES).date().isoformat() > aujourdhui:
        raise DateEffetFuture(effet_at, aujourdhui)
    return effectif.astimezone(timezone.utc).isoformat()


@dataclass(frozen=True)
class GesteEtat:
    """Un geste de la table avec son état permis/refusé, son libellé humain et,
    si refusé, la raison en clair (EXE-200, critère 14 ; libellé EXE-194,
    critères 14-15). `pieces_non_pretes` (EXE-197, critère 10) : codes des
    pièces qui manquent pour `marquer_envoyee`, même quand il est permis
    (critère 1) — vide pour tout autre geste ou quand tout est prêt."""

    geste: str
    permis: bool
    libelle: str
    raison: str | None
    pieces_non_pretes: list[str] = field(default_factory=list)


_MOIS_FR = [
    "janvier",
    "février",
    "mars",
    "avril",
    "mai",
    "juin",
    "juillet",
    "août",
    "septembre",
    "octobre",
    "novembre",
    "décembre",
]


def _jour_mois_fr(iso: str) -> str:
    d = datetime.fromisoformat(iso)
    return f"{d.day} {_MOIS_FR[d.month - 1]}"


def libelle_annuler(dernier: "EvenementHistorique | None") -> str:
    """Dit quel geste l'annulation défera et sa date d'effet (EXE-194, critère
    15) — par exemple « Annuler Marquer envoyée du 19 octobre » ; libellé
    générique si rien à annuler."""
    if dernier is None:
        return LIBELLES_GESTES[ANNULER]
    libelle_geste = LIBELLES_GESTES.get(dernier.geste, dernier.geste)
    return f"Annuler {libelle_geste} du {_jour_mois_fr(dernier.effet_at)}"


def gestes_avec_etat(
    etat: str,
    *,
    cv_pret: bool,
    lettre_pret: bool,
    dernier_annulable: "EvenementHistorique | None",
    lettre_sans: bool = False,
) -> list[GesteEtat]:
    """Chaque geste de la table (`annuler` compris), permis ou non, avec son
    libellé et la raison du refus en clair quand il l'est (critère 14) —
    jamais par code interne (critère 17). `dernier_annulable` est le dernier
    geste non annulé de l'historique, ou `None` s'il n'y a rien à annuler
    (EXE-194, critère 15 : donne sa date d'effet au libellé)."""
    annulable = dernier_annulable is not None
    resultat: list[GesteEtat] = []
    for geste in TOUS_GESTES:
        pieces_manquantes: list[str] = []
        if geste == ANNULER:
            permis = annulable
            libelle = libelle_annuler(dernier_annulable)
            raison = None if permis else "Aucun geste à annuler."
        elif geste not in TRANSITIONS.get(etat, {}):
            permis = False
            libelle = LIBELLES_GESTES[geste]
            raison = (
                f"« {LIBELLES_GESTES[geste]} » n'est pas possible depuis "
                f"l'étape « {LIBELLES_ETATS.get(etat, etat)} »."
            )
        else:
            permis = True
            libelle = LIBELLES_GESTES[geste]
            raison = None
            # EXE-197, critères 1, 9, 10 : `marquer_envoyee` reste permis
            # quel que soit l'état des pièces — seul un avertissement, plus
            # un refus (`PiecesNonPretes` n'est plus levée, cf. `appliquer`).
            if geste == MARQUER_ENVOYEE and not pieces_pretes_pour_envoi(
                cv_pret=cv_pret, lettre_pret=lettre_pret, lettre_sans=lettre_sans
            ):
                pieces_manquantes = pieces_manquantes_pour_envoi(
                    cv_pret=cv_pret, lettre_pret=lettre_pret, lettre_sans=lettre_sans
                )
                raison = str(PiecesNonPretes(cv_pret, lettre_pret, lettre_sans))
        resultat.append(
            GesteEtat(
                geste=geste,
                permis=permis,
                libelle=libelle,
                raison=raison,
                pieces_non_pretes=pieces_manquantes,
            )
        )
    return resultat


def appliquer(
    etat: str,
    geste: str,
    *,
    cv_pret: bool,
    lettre_pret: bool,
    lettre_sans: bool = False,
) -> str:
    """Nouvel état stocké, ou lève `GesteRefuse` si le geste n'est pas dans la
    table depuis cet état.

    Depuis EXE-197 (critère 1), `marquer_envoyee` n'est plus jamais refusé
    pour des pièces non prêtes — `cv_pret`/`lettre_pret`/`lettre_sans`
    restent dans la signature pour ne pas changer les appels existants
    (`storage.appliquer_geste`, les tests de transition génériques), mais ne
    sont plus consultés ici."""
    transitions = TRANSITIONS.get(etat, {})
    if geste not in transitions:
        raise GesteRefuse(etat, geste)
    return transitions[geste]


def tri(etat: str) -> str:
    """Famille large (critère 12) : à trier / retenue / écartée."""
    if etat == A_TRIER:
        return A_TRIER
    if etat == ECARTEE:
        return ECARTEE
    return RETENUE


def etape_affichee(
    etat: str, *, cv_pret: bool, lettre_pret: bool, lettre_sans: bool = False
) -> str | None:
    """`None` si pas retenue ; sinon l'étape à afficher, avec le survol
    « prête à l'envoi » dérivé (critère 6), jamais stocké."""
    if etat not in ETATS_RETENUS:
        return None
    if etat == RETENUE and pieces_pretes_pour_envoi(
        cv_pret=cv_pret, lettre_pret=lettre_pret, lettre_sans=lettre_sans
    ):
        return PRETE_A_L_ENVOI
    return etat


@dataclass(frozen=True)
class EvenementHistorique:
    """Reflet d'une ligne de `historique_gestes` — pas de sqlite3 ici, le
    mapping ligne→dataclass vit dans `storage.py`."""

    id: int
    geste: str
    etat_depart: str
    etat_arrivee: str
    effet_at: str
    enregistre_at: str
    motif: str | None
    annule_at: str | None


def permis_annuler(historique: list[EvenementHistorique]) -> bool:
    """Vrai si au moins un geste de l'historique n'est pas annulé (critère 5)."""
    return any(e.annule_at is None for e in historique)


def dernier_geste_non_annule(
    historique: list[EvenementHistorique],
) -> EvenementHistorique | None:
    """Le plus récent geste non annulé, ou `None` — `historique` est fourni
    trié du plus ancien au plus récent."""
    for e in reversed(historique):
        if e.annule_at is None:
            return e
    return None


def dernier_ecart(
    historique: list[EvenementHistorique],
) -> EvenementHistorique | None:
    """Le plus récent geste `ecarter` non annulé, ou `None` (EXE-194, critères
    9 et 11) — date d'effet et motif de l'écart affichés dans Écartées."""
    for e in reversed(historique):
        if e.annule_at is None and e.geste == ECARTER:
            return e
    return None


# ---------------------------------------------------------------------------
# Rang de progression sur le chemin heureux, pour la frise (EXE-194, critère
# 22) — résout une bifurcation (refusée/sans suite/abandonnée) via l'état de
# départ du geste qui y a mené, jamais via la position de l'état courant dans
# la séquence affichée (qui rendait TOUT acquis dès qu'un état hors séquence
# était atteint — le défaut nommé par le ticket).
# ---------------------------------------------------------------------------

_RANG_ON_PATH = {
    RETENUE: 1,
    CANDIDATURE_ENVOYEE: 2,
    ENTRETIEN: 3,
    OFFRE_RECUE: 4,
}

ETATS_BRANCHE = {REFUSEE, SANS_SUITE, ABANDONNEE}


def rang_progression(etat: str, historique: list[EvenementHistorique]) -> int:
    """Rang atteint sur le chemin heureux (0 à 4). Pour un état hors chemin
    (branche), remonte à l'état de départ du geste qui y a mené."""
    if etat in _RANG_ON_PATH:
        return _RANG_ON_PATH[etat]
    if etat in ETATS_BRANCHE:
        for e in reversed(historique):
            if e.annule_at is None and e.etat_arrivee == etat:
                return _RANG_ON_PATH.get(e.etat_depart, 0)
    return 0


def etapes_acquises(
    etat: str,
    historique: list[EvenementHistorique],
    *,
    cv_pret: bool,
    lettre_pret: bool,
    lettre_sans: bool = False,
) -> list[str]:
    """Sous-ensemble de `ETAPES_AFFICHEES` (api/offers.py) réellement acquis
    (critère 22) — jamais « tout acquis par défaut » pour un état hors
    séquence, qui montrait « candidature envoyée » pour une offre abandonnée
    depuis « retenue » sans jamais avoir été envoyée."""
    rang = rang_progression(etat, historique)
    etape_actuelle = etape_affichee(
        etat, cv_pret=cv_pret, lettre_pret=lettre_pret, lettre_sans=lettre_sans
    )
    acquises: list[str] = []
    if rang >= 1:
        acquises.append(RETENUE)
    if rang >= 2 or (rang == 1 and etape_actuelle == PRETE_A_L_ENVOI):
        acquises.append(PRETE_A_L_ENVOI)
    if rang >= 2:
        acquises.append(CANDIDATURE_ENVOYEE)
    if rang >= 3:
        acquises.append(ENTRETIEN)
    return acquises
