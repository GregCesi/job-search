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

from dataclasses import dataclass

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
    """Le geste n'est pas permis depuis cet état (critère 2) — nomme les deux."""

    def __init__(self, etat: str, geste: str):
        self.etat = etat
        self.geste = geste
        super().__init__(
            f"Le geste « {geste} » n'est pas permis depuis l'état « {etat} »"
        )


class PiecesNonPretes(Exception):
    """`marquer_envoyee` depuis `retenue` sans CV et lettre Prêts (critère 7) —
    même message qu'avant ce ticket (`api/pieces.py`)."""

    def __init__(self, cv_pret: bool, lettre_pret: bool):
        self.cv_pret = cv_pret
        self.lettre_pret = lettre_pret
        cv_manque = not cv_pret
        lettre_manque = not lettre_pret
        if cv_manque and lettre_manque:
            quoi = "Le CV et la lettre ne sont pas prêts"
        elif cv_manque:
            quoi = "Le CV n'est pas prêt"
        else:
            quoi = "La lettre n'est pas prête"
        super().__init__(f"{quoi} : impossible de marquer la candidature envoyée")


def gestes_permis(etat: str) -> list[str]:
    """Gestes de la table pour cet état, sans `annuler` (dépend de l'historique,
    cf. `storage.permis_annuler`)."""
    return sorted(TRANSITIONS.get(etat, {}))


def gestes_permis_effectifs(
    etat: str, *, cv_pret: bool, lettre_pret: bool, annulable: bool
) -> list[str]:
    """Gestes réellement applicables là, tout de suite (critère 12) : exclut
    `marquer_envoyee` si les pièces ne sont pas prêtes, ajoute `annuler` si
    l'historique le permet."""
    permis = [
        g
        for g in gestes_permis(etat)
        if not (
            g == MARQUER_ENVOYEE and etat == RETENUE and not (cv_pret and lettre_pret)
        )
    ]
    if annulable:
        permis.append(ANNULER)
    return permis


@dataclass(frozen=True)
class GesteEtat:
    """Un geste de la table avec son état permis/refusé et, si refusé, la
    raison en clair (EXE-200, critère 14)."""

    geste: str
    permis: bool
    raison: str | None


def gestes_avec_etat(
    etat: str, *, cv_pret: bool, lettre_pret: bool, annulable: bool
) -> list[GesteEtat]:
    """Chaque geste de la table (`annuler` compris), permis ou non, avec la
    raison du refus en clair quand il l'est (critère 14) — jamais par code
    interne (critère 17)."""
    resultat: list[GesteEtat] = []
    for geste in TOUS_GESTES:
        if geste == ANNULER:
            permis = annulable
            raison = None if permis else "Aucun geste à annuler."
        elif geste not in TRANSITIONS.get(etat, {}):
            permis = False
            raison = (
                f"« {LIBELLES_GESTES[geste]} » n'est pas possible depuis "
                f"l'étape « {LIBELLES_ETATS.get(etat, etat)} »."
            )
        elif (
            geste == MARQUER_ENVOYEE
            and etat == RETENUE
            and not (cv_pret and lettre_pret)
        ):
            permis = False
            raison = str(PiecesNonPretes(cv_pret, lettre_pret))
        else:
            permis = True
            raison = None
        resultat.append(GesteEtat(geste=geste, permis=permis, raison=raison))
    return resultat


def appliquer(etat: str, geste: str, *, cv_pret: bool, lettre_pret: bool) -> str:
    """Nouvel état stocké, ou lève `GesteRefuse` / `PiecesNonPretes`.

    `cv_pret`/`lettre_pret` ne sont consultés que pour `marquer_envoyee` depuis
    `retenue` — ignorés pour tout autre geste."""
    transitions = TRANSITIONS.get(etat, {})
    if geste not in transitions:
        raise GesteRefuse(etat, geste)
    if geste == MARQUER_ENVOYEE and etat == RETENUE and not (cv_pret and lettre_pret):
        raise PiecesNonPretes(cv_pret, lettre_pret)
    return transitions[geste]


def tri(etat: str) -> str:
    """Famille large (critère 12) : à trier / retenue / écartée."""
    if etat == A_TRIER:
        return A_TRIER
    if etat == ECARTEE:
        return ECARTEE
    return RETENUE


def etape_affichee(etat: str, *, cv_pret: bool, lettre_pret: bool) -> str | None:
    """`None` si pas retenue ; sinon l'étape à afficher, avec le survol
    « prête à l'envoi » dérivé (critère 6), jamais stocké."""
    if etat not in ETATS_RETENUS:
        return None
    if etat == RETENUE and cv_pret and lettre_pret:
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
