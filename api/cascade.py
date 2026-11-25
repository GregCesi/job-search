"""Lancement des pièces au geste de retenir (TCK-281, EXE-127, EXE-212).

Retenir une offre lance son CV seul, sans autre appel de ma part. La fiche
entreprise ne part plus de ce geste depuis EXE-212 : elle part de « Préparer la
fiche » (`POST /offers/{id}/fiche`) ou de « Générer la lettre » quand elle
manque (`api/lettre.py::create_lettre`), et sa fin lance la lettre demandée
(`api/lettre.py::launch_lettre_if_ready`).

Appelée uniquement par les deux routes de retenir (`POST /offers/{id}/geste`,
`PUT /offers/{id}/verdict`) — jamais par un changement de profil, un rescore,
ou le démarrage de l'API.
"""

import asyncio

from . import cv as cv_api


async def launch_pieces(offer_id: int) -> list[asyncio.Task]:
    """Lance le CV s'il n'est pas déjà en cours ou terminé. Rend les tâches
    effectivement créées — utile pour les tests, ignoré par la route."""
    cv_task = await cv_api.launch_cv(offer_id)
    return [cv_task] if cv_task is not None else []
