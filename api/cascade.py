"""Cascade de lancement des pièces au geste de retenir (TCK-281, EXE-127).

Retenir une offre lance sa fiche entreprise et son CV sans autre appel de ma
part : les deux sont indépendants (architecture.md §4 — le CV ne lit jamais la
fiche), donc lancés l'un après l'autre sans que l'un attende l'autre. La lettre,
elle, dépend de la fiche et ne part qu'une fois celle-ci terminée — ce n'est pas
cette cascade qui la lance, mais `api/fiche.py::_generate` lui-même (cf.
`api/lettre.py::launch_lettre_if_ready`).

Appelée uniquement par `PUT /offers/{id}/verdict` quand le nouveau statut est
`retenu` — jamais par un changement de profil, un rescore, ou le démarrage de
l'API.
"""

import asyncio

from . import cv as cv_api
from . import fiche as fiche_api


async def launch_pieces(offer_id: int) -> list[asyncio.Task]:
    """Lance la fiche et le CV s'ils ne sont pas déjà en cours ou terminés
    (critères 1, 11, 12 du ticket). Rend les tâches effectivement créées —
    utile pour les tests, ignoré par la route."""
    tasks: list[asyncio.Task] = []
    fiche_task = await fiche_api.launch_fiche(offer_id)
    if fiche_task is not None:
        tasks.append(fiche_task)
    cv_task = await cv_api.launch_cv(offer_id)
    if cv_task is not None:
        tasks.append(cv_task)
    return tasks
