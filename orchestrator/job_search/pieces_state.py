"""Registre en mémoire des offres dont une pièce vient de changer d'état (EXE-127).

Vit dans le process API, jamais persisté : un redémarrage le vide. Sans
conséquence, puisqu'il ne sert qu'au polling d'affichage (critère 17) — pas à
l'avancement d'une offre précise, qui se recalcule toujours depuis la base.

`drain_changed` vide le registre à la lecture : une offre signalée « vient de
changer d'état » ne l'est plus au prochain appel, jusqu'au prochain changement.
"""

_changed: set[int] = set()


def mark_changed(offer_id: int) -> None:
    _changed.add(offer_id)


def drain_changed() -> set[int]:
    changed = set(_changed)
    _changed.clear()
    return changed
