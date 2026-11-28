"""Vérification à la fin d'un run (EXE-217, H3, H7), sur le périmètre de
« vérifier tout » (EXE-223, H3).

La fin du run lance la même vérification que POST /offers/check-expirations avec
le corps {"tout": true} (`run_expiration_check`), sur les lignes des files
« À postuler » et « À étudier », leurs jumelles et les candidatures en cours.
Elle ne fait jamais échouer le run : une erreur s'écrit sur sa sortie et le run
se termine.
"""

from __future__ import annotations

import sqlite3

import orchestrator.job_search.paths as paths
from orchestrator.job_search.a_postuler import calcul, sorties
from orchestrator.job_search.a_postuler.regles import charger_regles
from orchestrator.job_search.expiration.service import run_expiration_check
from orchestrator.job_search.matching.profile import Profile
from orchestrator.job_search.scoring.aliases import AliasTable
from orchestrator.job_search.storage import a_postuler as stockage
from orchestrator.job_search.suivi import storage as suivi_storage


def ids_a_verifier(
    conn: sqlite3.Connection, classement: calcul.Classement
) -> list[int]:
    """Le périmètre de « vérifier tout » (H3) : les lignes des deux files, toutes
    familles et tous groupes, leurs jumelles, puis les candidatures en cours."""
    ids: list[int] = []
    for li in classement.principale + classement.a_etudier:
        ids.append(li.id)
        ids.extend(j["id"] for j in li.jumelles)
    ids.extend(suivi_storage.offer_ids_en_cours(conn))
    return list(dict.fromkeys(ids))


def verifier_en_fin_de_run(
    conn: sqlite3.Connection, profil: Profile, alias: AliasTable
) -> None:
    try:
        classement = sorties.classer(
            stockage.entrees(conn), charger_regles(paths.A_POSTULER_PATH), profil, alias
        )
        ids = ids_a_verifier(conn, classement)
        run_expiration_check(conn, offer_ids=ids)
    except Exception as exc:  # la vérification ne fait jamais échouer le run
        print(f"[run] vérification : échec ({exc})")
        return
    print(f"[run] vérification : {len(ids)} offres vérifiées")
