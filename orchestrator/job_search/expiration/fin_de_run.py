"""Vérification à la fin d'un run (EXE-217, H3, H7).

La fin du run lance la même vérification que POST /offers/check-expirations
(`run_expiration_check`), sur les seules offres des files « À postuler » et
« À étudier ». Elle ne fait jamais échouer le run : une erreur s'écrit sur sa
sortie et le run se termine.
"""

from __future__ import annotations

import sqlite3

import orchestrator.job_search.paths as paths
from orchestrator.job_search.a_postuler import calcul
from orchestrator.job_search.a_postuler.regles import charger_regles
from orchestrator.job_search.expiration.service import run_expiration_check
from orchestrator.job_search.matching.profile import Profile
from orchestrator.job_search.scoring.aliases import AliasTable
from orchestrator.job_search.storage import a_postuler as stockage
from orchestrator.job_search.suivi import storage as suivi_storage


def ids_des_files(
    conn: sqlite3.Connection, profil: Profile, alias: AliasTable
) -> list[int]:
    """Les offres des deux files, dans leur ordre, calculées comme l'API les calcule."""
    classement = calcul.classer(
        stockage.lire_offres(conn),
        suivi_storage.etat_map(conn),
        stockage.offres_expirees(conn),
        charger_regles(paths.A_POSTULER_PATH),
        profil,
        alias,
        stockage.cles_comparaison(conn),
    )
    return [li.id for li in classement.principale + classement.a_etudier]


def verifier_en_fin_de_run(
    conn: sqlite3.Connection, profil: Profile, alias: AliasTable
) -> None:
    try:
        ids = ids_des_files(conn, profil, alias)
        run_expiration_check(conn, offer_ids=ids)
    except Exception as exc:  # la vérification ne fait jamais échouer le run
        print(f"[run] vérification : échec ({exc})")
        return
    print(f"[run] vérification : {len(ids)} offres vérifiées")
