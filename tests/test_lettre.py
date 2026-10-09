"""Tests EXE-65 — lettre de motivation : choix des points (routes GET/PUT
/lettre/points, héritées) et calculs Python purs de `redaction.py`.

EXE-162 a retiré toute la couverture de l'ancienne génération en un seul appel
SDK (`_generate_texte`, `build_prompt`) : la génération délègue désormais à la
boucle (`lettre/boucle.py`), couverte par ses propres tests
(test_exe147_boucle_lettre.py et suivants) et par test_exe162_boucle_app.py
pour le branchement API/service. Les critères 1-4, 8-23 d'origine (préférences
de ton obligatoires, point choisi obligatoire, contenu du prompt unique,
longueur à 400 mots) ne décrivent plus le comportement du système — ils sont
remplacés par les critères du ticket EXE-162.

Aucun test n'appelle le modèle. Aucun test ne lit ni n'écrit sous data/ : la DB
est un fichier tmp_path.
"""

import json
import sqlite3

import pytest

import api.db as api_db
import api.lettre as api_lettre
import orchestrator.job_search.storage.db as storage_db
from orchestrator.job_search.lettre.redaction import (
    count_words,
    detect_tournures,
    exceeds_length,
    point_text,
    resolve_chosen_indices,
    strip_html,
)
from orchestrator.job_search.storage.db import init_db


@pytest.fixture
def db_path(tmp_path, monkeypatch):
    path = tmp_path / "job_search.sqlite"
    monkeypatch.setattr(storage_db, "DB_PATH", path)
    monkeypatch.setattr(api_db, "DB_PATH", path)
    conn = sqlite3.connect(path)
    init_db(conn)
    conn.close()
    return path


def _insert_offer(db_path, offer_id, verdict="retenu"):
    conn = sqlite3.connect(db_path)
    try:
        conn.execute(
            "INSERT INTO offers (id, source, source_id, fingerprint, title, description_raw) "
            "VALUES (?, 'test', ?, 'fp', 'Titre', 'Texte de l offre X')",
            (offer_id, str(offer_id)),
        )
        if verdict is not None:
            conn.execute(
                "INSERT INTO verdicts (offer_id, status, created_at) VALUES (?, ?, '2026-09-28')",
                (offer_id, verdict),
            )
        conn.commit()
    finally:
        conn.close()


def _points_8() -> list[dict]:
    tas_par_index = ["lettre", "lettre", "entretien", "rien", None, None, None, None]
    return [
        {
            "position": f"Point {i}",
            "citation": f"Citation {i}",
            "url": None,
            "tas": tas,
            "explication": None,
        }
        for i, tas in enumerate(tas_par_index)
    ]


def _insert_fiche(
    db_path, offer_id, points, statut="done", presentation="Présentation entreprise X"
):
    conn = sqlite3.connect(db_path)
    try:
        conn.execute(
            "INSERT INTO fiches_entreprise (offer_id, statut, presentation, points_json, created_at) "
            "VALUES (?, ?, ?, ?, '2026-09-28')",
            (offer_id, statut, presentation, json.dumps(points, ensure_ascii=False)),
        )
        conn.commit()
    finally:
        conn.close()


def _fiche_points(db_path, offer_id):
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        row = conn.execute(
            "SELECT points_json FROM fiches_entreprise WHERE offer_id = ?", (offer_id,)
        ).fetchone()
        return json.loads(row["points_json"])
    finally:
        conn.close()


class TestCritere5PointsAvecTasParDefaut:
    def test_huit_points_deux_choisis_par_defaut(self, db_path):
        offer_id = 5
        _insert_offer(db_path, offer_id)
        _insert_fiche(db_path, offer_id, _points_8())

        result = api_lettre.get_lettre_points(offer_id)

        assert len(result) == 8
        for i, p in enumerate(result):
            assert p["tas"] == _points_8()[i]["tas"]
            assert p["texte"] == point_text(_points_8()[i])
        choisis = [i for i, p in enumerate(result) if p["choisi"]]
        assert choisis == [0, 1]


class TestCritere6ChoixExplicite:
    def test_retrait_et_ajout_persistent_exactement(self, db_path):
        offer_id = 6
        _insert_offer(db_path, offer_id)
        _insert_fiche(db_path, offer_id, _points_8())

        body = api_lettre.PointsChoisisIn(indices=[1, 2])
        api_lettre.set_lettre_points(offer_id, body)

        result = api_lettre.get_lettre_points(offer_id)
        choisis = [i for i, p in enumerate(result) if p["choisi"]]
        assert choisis == [1, 2]


class TestCritere7TasFicheInchangeApresChoix:
    def test_tas_fiche_identiques_apres_changement_de_choix(self, db_path):
        offer_id = 7
        _insert_offer(db_path, offer_id)
        points_avant = _points_8()
        _insert_fiche(db_path, offer_id, points_avant)

        api_lettre.set_lettre_points(
            offer_id, api_lettre.PointsChoisisIn(indices=[1, 2])
        )

        points_apres = _fiche_points(db_path, offer_id)
        assert [p["tas"] for p in points_apres] == [p["tas"] for p in points_avant]
        assert points_apres == points_avant


class TestReglesTransversales:
    """Comportements interdits par le ticket, vérifiés indépendamment des critères
    numérotés : le choix des points ne touche jamais la fiche, et le module de calcul
    reste pur (utile en isolation par les tests unitaires ci-dessous)."""

    def test_resolve_chosen_indices_defaut_tas_lettre(self):
        points = _points_8()
        assert resolve_chosen_indices(points, None) == [0, 1]

    def test_resolve_chosen_indices_choix_explicite_vide(self):
        points = _points_8()
        assert resolve_chosen_indices(points, json.dumps([])) == []

    def test_detect_tournures_insensible_a_la_casse(self):
        assert detect_tournures("JE VEUX partir", ["je veux"]) == ["JE VEUX"]

    def test_detect_tournures_absente(self):
        assert detect_tournures("Texte neutre", ["je veux"]) == []

    def test_count_words_et_exceeds_length(self):
        # EXE-162, H2 : la borne de longueur passe de 400 à 250 mots.
        assert count_words("un deux trois") == 3
        assert exceeds_length(251) is True
        assert exceeds_length(250) is False

    def test_strip_html_retire_les_balises(self):
        assert strip_html("<p>Bonjour <b>Monde</b></p>") == "Bonjour Monde"
