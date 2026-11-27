"""Le seul point d'appel réseau du parcours de candidature (EXE-217, H9).

Une lecture de page : GET, redirections suivies, délai de 15 secondes (H4). Rien
d'autre ne part vers un site : ni formulaire, ni compte, ni clic. Une panne réseau
lève une `requests.exceptions.RequestException`, que le parcours note « injoignable ».

La suite de tests remplace `lire` par un refus (tests/conftest.py) : un test qui
ne simule pas ses réponses échoue au lieu d'appeler un site.
"""

from __future__ import annotations

import time
from dataclasses import dataclass

import requests

DELAI_SECONDES = 15


@dataclass(frozen=True)
class Reponse:
    """Les adresses traversées (redirections comprises) avec leur code, et le
    texte de la dernière."""

    chaine: list[tuple[str, int]]
    texte: str


def envoyer_get(adresse: str) -> Reponse:
    resp = requests.get(adresse, allow_redirects=True, timeout=DELAI_SECONDES)
    chaine = [(h.url, h.status_code) for h in resp.history]
    chaine.append((resp.url, resp.status_code))
    return Reponse(chaine=chaine, texte=resp.text)


lire = envoyer_get
attendre = time.sleep
