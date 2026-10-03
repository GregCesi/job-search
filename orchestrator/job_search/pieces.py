"""Statut d'une pièce de candidature — CV ou lettre (EXE-101).

Trois valeurs : À faire (jamais générée), En cours (générée — en cours,
terminée ou en erreur — mais pas encore validée), Prête (marquée par moi
seul·e). Calcul 100% Python depuis l'état de génération déjà persisté et la
marque humaine : jamais déduit de la fin d'une génération (architecture.md).
"""

A_FAIRE = "a_faire"
EN_COURS = "en_cours"
PRETE = "prete"


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


def prete_a_l_envoi(cv: str, lettre: str) -> bool:
    return cv == PRETE and lettre == PRETE
