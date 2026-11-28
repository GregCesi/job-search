"""Lectures en base des files « À postuler » et « À étudier » (EXE-210).

Lecture seule : rang, famille, file et motif ne s'écrivent jamais en base. L'état
d'une offre ne se lit pas ici, mais par le module d'états (suivi/storage.py).
"""

import json
import sqlite3

from orchestrator.job_search.a_postuler.calcul import OffreLue
from orchestrator.job_search.a_postuler.lieu import ParcoursFile
from orchestrator.job_search.a_postuler.sorties import Entrees, Verification
from orchestrator.job_search.parcours.lecture import INCONNUE, Depart, depart_possible
from orchestrator.job_search.storage.remises import remises
from orchestrator.job_search.suivi import storage as suivi_storage


def lire_offres(conn: sqlite3.Connection) -> list[OffreLue]:
    rows = conn.execute(
        "SELECT id, title, company, location, source, url, contract_type, "
        "fetched_at, description, ad_language, extracted_facts_json, filtered_out "
        "FROM offers ORDER BY id ASC"
    ).fetchall()
    return [
        OffreLue(
            id=r[0],
            titre=r[1] or "",
            entreprise=r[2] or "",
            lieu=r[3] or "",
            source=r[4] or "",
            url=r[5] or "",
            contrat=r[6] or "",
            recuperee=r[7],
            description=r[8] or "",
            langue_annonce=r[9],
            faits_json=r[10],
            filtree=bool(r[11]),
        )
        for r in rows
    ]


def offres_expirees(conn: sqlite3.Connection) -> set[int]:
    """Offres dont la vérification d'expiration est positive."""
    rows = conn.execute("SELECT offer_id FROM expirations WHERE expired = 1").fetchall()
    return {r[0] for r in rows}


def cles_comparaison(conn: sqlite3.Connection) -> dict[int, str]:
    """La clé de comparaison du parcours lu de chaque offre qui en a une (EXE-219).
    Un parcours à la fin de forme « inconnue » compte comme sans clé."""
    rows = conn.execute(
        "SELECT offer_id, cle FROM parcours WHERE cle IS NOT NULL AND fin_forme != ?",
        (INCONNUE,),
    ).fetchall()
    return {r[0]: r[1] for r in rows}


def parcours_des_offres(conn: sqlite3.Connection) -> dict[int, ParcoursFile]:
    """Ce que les files lisent du parcours de chaque offre (EXE-220) : lu ou non,
    point de départ, lieu réel, fin, date de mise en ligne et de vérification."""
    rows = conn.execute(
        "SELECT o.id, o.source, o.source_id, o.url, p.offer_id, p.lieu_reel, "
        "p.code_postal, p.provinces_json, p.fin_forme, p.fin_adresse, "
        "p.en_ligne_depuis, p.verifiee_le "
        "FROM offers o LEFT JOIN parcours p ON p.offer_id = o.id"
    ).fetchall()
    return {
        r[0]: ParcoursFile(
            lu=r[4] is not None,
            adresse=depart_possible(
                Depart(source=r[1] or "", source_id=r[2] or "", url=r[3] or None)
            ),
            lieu_reel=r[5],
            code_postal=r[6],
            provinces=tuple(json.loads(r[7] or "[]")),
            fin_forme=r[8],
            fin_adresse=r[9],
            en_ligne_depuis=r[10],
            verifiee_le=r[11],
        )
        for r in rows
    }


def entrees(conn: sqlite3.Connection) -> Entrees:
    """Tout ce que les files lisent en base, remises à la main comprises (EXE-223).
    L'état de chaque offre vient du module d'états."""
    return Entrees(
        offres=lire_offres(conn),
        etats=suivi_storage.etat_map(conn),
        expirees=offres_expirees(conn),
        cles=cles_comparaison(conn),
        parcours=parcours_des_offres(conn),
        remises=remises(conn),
    )


def verifications(conn: sqlite3.Connection) -> dict[int, Verification]:
    """Ce que la vérification a gardé de chaque offre vérifiée : le signe de
    fermeture et les dates du parcours, la date du verdict d'expiration (EXE-223)."""
    rows = conn.execute(
        "SELECT o.id, p.fermeture_json, p.lu_le, p.verifiee_le, e.last_checked_at "
        "FROM offers o LEFT JOIN parcours p ON p.offer_id = o.id "
        "LEFT JOIN expirations e ON e.offer_id = o.id "
        "WHERE p.offer_id IS NOT NULL OR e.offer_id IS NOT NULL"
    ).fetchall()
    return {
        r[0]: Verification(
            fermeture=json.loads(r[1]) if r[1] else None,
            lu_le=r[2],
            verifiee_le=r[3],
            expiration_le=r[4],
        )
        for r in rows
    }
