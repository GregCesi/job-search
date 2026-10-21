"""Statut d'une pièce de candidature — CV ou lettre (EXE-101).

Trois valeurs : À faire (jamais générée), En cours (générée — en cours,
terminée ou en erreur — mais pas encore validée), Prête (marquée par moi
seul·e). Calcul 100% Python depuis l'état de génération déjà persisté et la
marque humaine : jamais déduit de la fin d'une génération (architecture.md).

La décision de la lettre (EXE-195) est un axe séparé, propre à la carte
Lettre : à décider (jamais demandée), demandée (demandée au moins une fois —
qu'elle attende la fiche, tourne, ait fini ou soit en erreur), sans lettre
(choix explicite de ne pas en faire). Elle ne change rien à `lettre_statut`,
mais compte comme la lettre satisfaite pour `prete_a_l_envoi` depuis EXE-196 :
CV Prêt et (lettre Prête ou décision « Sans lettre ») — condition unique,
écrite dans `orchestrator.job_search.suivi.etats.pieces_pretes_pour_envoi`.
"""

from orchestrator.job_search.suivi.etats import pieces_pretes_pour_envoi

A_FAIRE = "a_faire"
EN_COURS = "en_cours"
PRETE = "prete"

DECISION_A_DECIDER = "a_decider"
DECISION_DEMANDEE = "demandee"
DECISION_SANS_LETTRE = "sans_lettre"

BOUTON_GENERER = "generer"
BOUTON_NE_PAS_FAIRE = "ne_pas_faire"
BOUTON_REVENIR = "revenir"

_LIBELLES_BOUTONS = {
    BOUTON_GENERER: "Générer la lettre",
    BOUTON_NE_PAS_FAIRE: "Ne pas faire de lettre pour cette annonce",
    BOUTON_REVENIR: "Revenir sur ce choix",
}

CARTE_A_DECIDER = "a_decider"
CARTE_DEMANDEE = "demandee"
CARTE_EN_GENERATION = "en_generation"
CARTE_GENEREE = "generee"
CARTE_PRETE = "prete"
CARTE_SANS_LETTRE = "sans_lettre"

RAISON_GENERATION_EN_COURS = (
    "La lettre est en cours de génération : impossible de choisir "
    "« Ne pas faire de lettre pour cette annonce »."
)


def cv_statut(row) -> str:
    """`row` : ligne `cvs` (ou None si aucune génération n'a jamais été lancée)."""
    if row is None:
        return A_FAIRE
    if row["marque_pret_at"] is not None:
        return PRETE
    return EN_COURS


def lettre_statut(row) -> str:
    """`row` : ligne `lettres` (ou None). `statut='aucune'` = jamais générée,
    y compris quand la ligne existe déjà pour porter un choix de points."""
    if row is None or row["statut"] == "aucune":
        return A_FAIRE
    if row["marque_pret_at"] is not None:
        return PRETE
    return EN_COURS


def prete_a_l_envoi(cv: str, lettre: str, lettre_sans: bool) -> bool:
    """Condition unique « prête à l'envoi » (EXE-196, H4) : lue depuis le
    module d'états, seul endroit qui l'écrit — jamais réécrite ici."""
    return pieces_pretes_pour_envoi(
        cv_pret=cv == PRETE, lettre_pret=lettre == PRETE, lettre_sans=lettre_sans
    )


def pieces_a_envoyer(lettre_sans: bool) -> list[str]:
    """Pièces qui partent avec la candidature (EXE-196, critère 7) : le CV
    seul si la lettre est « sans lettre », le CV et la lettre sinon."""
    return ["cv"] if lettre_sans else ["cv", "lettre"]


def libelle_tout_telecharger(lettre_sans: bool) -> str:
    """Libellé du bouton de téléchargement (EXE-196, critères 8, 10)."""
    return "Télécharger le CV" if lettre_sans else "Tout télécharger"


def decision_lettre(row) -> str:
    """Décision stockée sur la ligne `lettres` (EXE-195) — « à décider » par
    défaut si la ligne n'existe pas encore (offre retenue dont la fiche n'a
    pas encore tourné, critères 1, 2)."""
    if row is None:
        return DECISION_A_DECIDER
    return row["decision"] or DECISION_A_DECIDER


def _bouton(
    bouton: str, *, visible: bool, actif: bool, raison: str | None = None
) -> dict:
    return {
        "bouton": bouton,
        "visible": visible,
        "actif": actif,
        "libelle": _LIBELLES_BOUTONS[bouton],
        "raison": raison,
    }


def carte_lettre(
    decision: str,
    lettre_statut_brut: str,
    marque_pret_at,
    generation_en_cours: bool,
    fiche_statut: str | None,
    fiche_error_message: str | None,
) -> dict:
    """Statut affiché et boutons de la carte Lettre (EXE-195, critères 2-13) —
    calcul 100% Python depuis les colonnes déjà en base et le registre en
    mémoire des tâches de fond ; jamais déduit côté front (architecture.md,
    frontend.md)."""
    message = None
    if decision == DECISION_SANS_LETTRE:
        statut = CARTE_SANS_LETTRE
    elif decision == DECISION_A_DECIDER:
        statut = CARTE_A_DECIDER
    elif lettre_statut_brut == "done":
        statut = CARTE_PRETE if marque_pret_at is not None else CARTE_GENEREE
    elif generation_en_cours:
        statut = CARTE_EN_GENERATION
    else:
        statut = CARTE_DEMANDEE
        # Critère 5 : demandée pendant que la fiche tournait encore, qui a
        # fini en erreur — la lettre n'a jamais tourné (statut reste
        # `aucune`), c'est la fiche qu'il faut relire.
        if lettre_statut_brut != "error" and fiche_statut == "error":
            message = fiche_error_message

    ne_pas_faire_visible = decision != DECISION_SANS_LETTRE
    peut_ne_pas_faire = ne_pas_faire_visible and not generation_en_cours
    return {
        "statut": statut,
        "message": message,
        "boutons": [
            _bouton(
                BOUTON_GENERER,
                visible=decision == DECISION_A_DECIDER,
                actif=decision == DECISION_A_DECIDER,
            ),
            _bouton(
                BOUTON_NE_PAS_FAIRE,
                visible=ne_pas_faire_visible,
                actif=peut_ne_pas_faire,
                raison=RAISON_GENERATION_EN_COURS
                if ne_pas_faire_visible and not peut_ne_pas_faire
                else None,
            ),
            _bouton(
                BOUTON_REVENIR,
                visible=decision == DECISION_SANS_LETTRE,
                actif=decision == DECISION_SANS_LETTRE,
            ),
        ],
    }
