"""Seuil de niveau pour les ajouts de compétences (EXE-58, critère 16).

Configurable sans toucher au code : variable d'environnement `CV_SKILL_THRESHOLD`,
lue à chaque appel (jamais mise en cache au chargement du module).
"""

import os

DEFAULT_SKILL_THRESHOLD = 4


def skill_threshold() -> int:
    raw = os.environ.get("CV_SKILL_THRESHOLD")
    if raw is None or not raw.strip():
        return DEFAULT_SKILL_THRESHOLD
    return int(raw)
