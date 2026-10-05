"""Avancement d'une pièce de candidature (EXE-127) — distinct du statut Prête
(`pieces.py`) : ceci dit si la génération tourne, a fini ou a échoué, pas si je
l'ai validée. Quatre états, les mêmes pour les quatre pièces (fiche, CV, lettre,
mail) : en attente, en cours, terminée, en erreur. Calcul 100% Python depuis
l'état déjà persisté et les registres en mémoire des tâches de fond — aucun
nouvel appel modèle.
"""

EN_ATTENTE = "en_attente"
EN_COURS = "en_cours"
TERMINEE = "terminee"
EN_ERREUR = "en_erreur"

RAISON_ORPHELINE = "Génération interrompue (API redémarrée)."


def _etat(etat: str, raison: str | None = None) -> dict:
    return {"etat": etat, "raison": raison}


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
    (fiche pas terminée, texte manquant, aucun point choisi) déjà calculée."""
    if row is None or row["statut"] == "aucune":
        return _etat(EN_ATTENTE, blocage)
    if row["statut"] == "done":
        return _etat(TERMINEE)
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
