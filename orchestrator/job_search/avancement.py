"""Avancement d'une pièce de candidature (EXE-127) — distinct du statut Prête
(`pieces.py`) : ceci dit si la génération tourne, a fini ou a échoué, pas si je
l'ai validée. Quatre états, les mêmes pour les quatre pièces (fiche, CV, lettre,
mail) : en attente, en cours, terminée, en erreur. Calcul 100% Python depuis
l'état déjà persisté et les registres en mémoire des tâches de fond — aucun
nouvel appel modèle.
"""

from orchestrator.job_search.lettre.boucle import (
    ETAPE_CHOIX_FAIT,
    ETAPE_JUGE,
    ETAPE_REDACTION,
    ETAPE_VERIFICATION,
    MAX_TOURS,
)

EN_ATTENTE = "en_attente"
EN_COURS = "en_cours"
TERMINEE = "terminee"
EN_ERREUR = "en_erreur"

RAISON_ORPHELINE = "Génération interrompue (API redémarrée)."

# EXE-167, critère 3 : le choix du fait, puis rédaction/vérification/lecture du
# juge pour chaque tour d'une boucle qui irait au plafond — la correction n'est
# jamais comptée.
_ETAPES_COMPTEES_LETTRE = {
    ETAPE_CHOIX_FAIT,
    ETAPE_REDACTION,
    ETAPE_VERIFICATION,
    ETAPE_JUGE,
}
TOTAL_ETAPES_LETTRE = 1 + MAX_TOURS * 3


def _etat(etat: str, raison: str | None = None) -> dict:
    return {"etat": etat, "raison": raison}


class ProgressionLettre:
    """Suivi en mémoire de la progression de la boucle de la lettre (EXE-167,
    critères 2, 3) — une instance par génération ou régénération en cours, vit
    dans la mémoire du processus de l'API, jamais en base : l'étape n'a de sens
    que pendant que la boucle tourne."""

    def __init__(self) -> None:
        self._complets: set[tuple[str, int]] = set()
        self.etape: str | None = None
        self.tour = 0
        self.max_tours = MAX_TOURS
        self.pourcentage = 0

    def signaler(self, signal: dict) -> None:
        self.etape = signal["etape"]
        self.tour = signal["tour"]
        self.max_tours = signal["max_tours"]
        if signal["etape"] in _ETAPES_COMPTEES_LETTRE:
            self._complets.add((signal["etape"], signal["tour"]))
        if signal.get("fin"):
            # Critère 3 : la boucle peut s'arrêter avant le plafond — le
            # pourcentage passe quand même à 100, jamais avant.
            self.pourcentage = 100
        else:
            self.pourcentage = min(99, len(self._complets) * 100 // TOTAL_ETAPES_LETTRE)

    def as_dict(self) -> dict:
        return {
            "etape": self.etape,
            "tour": self.tour,
            "max_tours": self.max_tours,
            "pourcentage": self.pourcentage,
        }


def generation_avancement(row, running: bool) -> dict:
    """Fiche ou CV : statut `pending|done|error` porté par leur propre table."""
    if row is None:
        return _etat(EN_ATTENTE)
    if row["statut"] == "done":
        return _etat(TERMINEE)
    if row["statut"] == "error":
        return _etat(EN_ERREUR, row["error_message"])
    # pending
    if running:
        return _etat(EN_COURS)
    return _etat(EN_ERREUR, RAISON_ORPHELINE)


def lettre_avancement(row, running: bool, blocage: str | None) -> dict:
    """Lettre : statut `aucune|pending|done|error`, plus la raison d'attente
    (fiche pas terminée, texte manquant, aucun point choisi) déjà calculée.

    Une régénération en cours (EXE-167, critère 1) se lit « en cours » comme
    une première génération — la pièce reste `done` en base, seul l'indicateur
    `regeneration_en_cours` le dit. Terminée ou en échec (y compris orpheline,
    API redémarrée en cours de régénération), elle revient à « terminée » :
    la lettre d'avant reste utilisable, seule la raison porte l'écart."""
    if row is None or row["statut"] == "aucune":
        return _etat(EN_ATTENTE, blocage)
    if row["statut"] == "done":
        if row["regeneration_en_cours"]:
            if running:
                return _etat(EN_COURS)
            return _etat(TERMINEE, RAISON_ORPHELINE)
        return _etat(TERMINEE, row["regeneration_error"])
    if row["statut"] == "error":
        return _etat(EN_ERREUR, row["error_message"])
    if running:
        return _etat(EN_COURS)
    return _etat(EN_ERREUR, RAISON_ORPHELINE)


def mail_avancement(ok: bool, error_message: str | None) -> dict:
    """Mail : jamais stocké, recalculé à la demande (critère 16) — terminé dès
    que le gabarit se lit, en erreur avec le message existant sinon."""
    if ok:
        return _etat(TERMINEE)
    return _etat(EN_ERREUR, error_message)
