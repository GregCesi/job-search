"""Tests EXE-149 — la fiche entreprise cherche les faits auxquels mes textes types
répondent, et chaque point dit sa famille et la date de sa page.

Aucun test n'appelle un modèle : `query` du SDK Claude Agent (fiche) est remplacé
par une doublure. Aucun test ne lit ni n'écrit sous data/ : DB et répertoire de la
lettre sont des fichiers tmp_path.
"""

import asyncio
import json
import sqlite3

import pytest
import yaml
from claude_agent_sdk import ResultMessage

import api.db as api_db
import api.fiche as fiche_api
import orchestrator.job_search.fiche.prompt as fiche_prompt
import orchestrator.job_search.fiche.service as fiche_service
import orchestrator.job_search.storage.db as storage_db
from orchestrator.job_search.fiche.cascade import CascadeResult
from orchestrator.job_search.storage.db import init_db

IDS_TEXTES_TYPES_NON_GENERIQUES = [
    "mesurer_avant_de_corriger",
    "tester_les_agents_automatiquement",
    "systeme_d_evaluation",
    "prototyper",
    "l_ia_ecrit_l_ingenieur_valide",
    "regle_ou_modele",
    "ecosysteme_claude",
]


def _texte_type(identifiant: str, **overrides) -> dict:
    base = {
        "id": identifiant,
        "sujet": f"Sujet distinctif de {identifiant}",
        "s_applique_si": f"condition d'usage de {identifiant}",
        "ne_s_applique_pas_si": f"contre-indication de {identifiant}",
    }
    base.update(overrides)
    return base


def _repertoire_bien_forme() -> dict:
    textes_types = [_texte_type(i) for i in IDS_TEXTES_TYPES_NON_GENERIQUES]
    textes_types.append({"id": "generique", "sujet": "Sujet distinctif de generique"})
    return {
        "version": 1,
        "sujets_interdits": [
            {
                "sujet": "Claude / Anthropic",
                "motif": "l'entreprise visée n'en parle pas",
                "exception": "sauf si l'offre nomme Claude elle-même",
            }
        ],
        "textes_types": textes_types,
    }


def _ecrire_repertoire(tmp_path, donnees: dict, nom: str = "repertoire.yaml"):
    chemin = tmp_path / nom
    chemin.write_text(yaml.safe_dump(donnees, allow_unicode=True), encoding="utf-8")
    return chemin


def _make_query(behavior):
    """behavior(prompt, options) -> liste de messages à produire."""

    async def _query(*, prompt, options):
        for m in behavior(prompt, options):
            yield m

    return _query


def _fiche_result(points, points_pour_lettre=None, session_id="fiche-session"):
    return ResultMessage(
        subtype="success",
        duration_ms=1,
        duration_api_ms=1,
        is_error=False,
        num_turns=1,
        session_id=session_id,
        total_cost_usd=0.1,
        result=None,
        structured_output={
            "mode": "entreprise",
            "presentation": "Présentation ACME.",
            "employeur": {
                "nom": "ACME",
                "entite_precise": None,
                "type_source": "direct",
                "methode": "test",
                "confiance": "sur",
                "urls": [],
            },
            "points": points,
            "points_pour_lettre": points_pour_lettre or [],
        },
    )


@pytest.fixture
def db_path(tmp_path, monkeypatch):
    path = tmp_path / "job_search.sqlite"
    monkeypatch.setattr(storage_db, "DB_PATH", path)
    monkeypatch.setattr(api_db, "DB_PATH", path)
    conn = sqlite3.connect(path)
    init_db(conn)
    conn.close()
    return path


@pytest.fixture(autouse=True)
def _stub_cascade_employeur(monkeypatch):
    """La cascade d'identification employeur appelle Ollama : hors périmètre de ce
    ticket, et interdit en test. Doublure déterministe, jamais de réseau."""

    def _fake(offer_id, conn, model=None, host=None):
        return CascadeResult(
            nom="ACME",
            entite=None,
            confiance="sur",
            type_source="direct",
            methode="test",
            etape=1,
        )

    monkeypatch.setattr(fiche_service, "identify_employer", _fake)


@pytest.fixture(autouse=True)
def _repertoire_absent_par_defaut(tmp_path, monkeypatch):
    """Sauf si un test écrit son propre répertoire, le chemin par défaut pointe sur
    un fichier qui n'existe pas — déterministe, indépendant de l'état du poste."""
    monkeypatch.setattr(
        fiche_prompt, "REPERTOIRE_LETTRE_PATH", tmp_path / "absent" / "repertoire.yaml"
    )


def _insert_offer(db_path, offer_id, description_raw="Texte complet de l'offre."):
    conn = sqlite3.connect(db_path)
    try:
        conn.execute(
            "INSERT INTO offers (id, source, source_id, fingerprint, title, company, "
            "location, description_raw) VALUES (?, 'test', ?, 'fp', 'Ingénieur H/F', "
            "'ACME', 'Strasbourg', ?)",
            (offer_id, str(offer_id), description_raw),
        )
        conn.commit()
    finally:
        conn.close()


def _offer_row(db_path, offer_id):
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        return conn.execute(
            "SELECT title, company, location, url, description, description_raw "
            "FROM offers WHERE id = ?",
            (offer_id,),
        ).fetchone()
    finally:
        conn.close()


def _cascade() -> CascadeResult:
    return CascadeResult(
        nom="ACME",
        entite=None,
        confiance="sur",
        type_source="direct",
        methode="test",
        etape=1,
    )


def _fiche_row(db_path, offer_id):
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        return conn.execute(
            "SELECT * FROM fiches_entreprise WHERE offer_id = ?", (offer_id,)
        ).fetchone()
    finally:
        conn.close()


def _points_json(db_path, offer_id) -> list[dict]:
    return json.loads(_fiche_row(db_path, offer_id)["points_json"])


def _insert_fiche_ancienne(db_path, offer_id, points):
    """Fiche produite avant EXE-149 (critère 12) : `points_json` sans `famille` ni `date`."""
    conn = sqlite3.connect(db_path)
    try:
        conn.execute(
            "INSERT INTO fiches_entreprise (offer_id, statut, presentation, points_json, created_at) "
            "VALUES (?, 'done', 'Présentation ACME.', ?, '2026-10-01')",
            (offer_id, json.dumps(points, ensure_ascii=False)),
        )
        conn.commit()
    finally:
        conn.close()


# --- critère 1 -----------------------------------------------------------------


class TestCritere1SujetsDesTextesTypesNonGeneriques:
    def test_le_prompt_contient_les_sept_sujets_non_generiques(
        self, db_path, tmp_path, monkeypatch
    ):
        chemin = _ecrire_repertoire(tmp_path, _repertoire_bien_forme())
        monkeypatch.setattr(fiche_prompt, "REPERTOIRE_LETTRE_PATH", chemin)
        _insert_offer(db_path, 1)
        offer = _offer_row(db_path, 1)

        prompt = fiche_prompt.build_prompt(offer, _cascade())

        for identifiant in IDS_TEXTES_TYPES_NON_GENERIQUES:
            assert f"Sujet distinctif de {identifiant}" in prompt
        assert "Sujet distinctif de generique" not in prompt


# --- critère 2 -----------------------------------------------------------------


class TestCritere2ConditionsUsage:
    def test_le_prompt_contient_les_conditions_d_usage(
        self, db_path, tmp_path, monkeypatch
    ):
        chemin = _ecrire_repertoire(tmp_path, _repertoire_bien_forme())
        monkeypatch.setattr(fiche_prompt, "REPERTOIRE_LETTRE_PATH", chemin)
        _insert_offer(db_path, 1)
        offer = _offer_row(db_path, 1)

        prompt = fiche_prompt.build_prompt(offer, _cascade())

        assert "condition d'usage de prototyper" in prompt
        assert "contre-indication de prototyper" in prompt


# --- critère 3 -----------------------------------------------------------------


class TestCritere3SujetsInterdits:
    def test_le_prompt_contient_les_sujets_interdits(
        self, db_path, tmp_path, monkeypatch
    ):
        chemin = _ecrire_repertoire(tmp_path, _repertoire_bien_forme())
        monkeypatch.setattr(fiche_prompt, "REPERTOIRE_LETTRE_PATH", chemin)
        _insert_offer(db_path, 1)
        offer = _offer_row(db_path, 1)

        prompt = fiche_prompt.build_prompt(offer, _cascade())

        assert "Claude / Anthropic" in prompt
        assert "l'entreprise visée n'en parle pas" in prompt
        assert "sauf si l'offre nomme Claude elle-même" in prompt


# --- critère 4 -----------------------------------------------------------------


class TestCritere4FamilleDemandeePourChaquePoint:
    def test_le_prompt_demande_la_famille_meme_sans_repertoire(self, db_path):
        _insert_offer(db_path, 1)
        offer = _offer_row(db_path, 1)

        prompt = fiche_prompt.build_prompt(offer, _cascade())

        assert "famille" in prompt
        assert "facon_de_travailler" in prompt
        assert "ce_que_le_poste_fait_faire" in prompt
        assert "preuve_ia" in prompt


# --- critère 5 -----------------------------------------------------------------


class TestCritere5DateDemandeePourChaquePoint:
    def test_le_prompt_demande_la_date_de_la_page_meme_sans_repertoire(self, db_path):
        _insert_offer(db_path, 1)
        offer = _offer_row(db_path, 1)

        prompt = fiche_prompt.build_prompt(offer, _cascade())

        assert "`date`" in prompt
        assert "aucune date" in prompt


# --- critère 6 -----------------------------------------------------------------


class TestCritere6FamilleEtDateRetrouveesParAPI:
    def test_point_avec_famille_et_date_relu_par_l_api(self, db_path, monkeypatch):
        offer_id = 6
        _insert_offer(db_path, offer_id)
        monkeypatch.setattr(
            fiche_service,
            "query",
            _make_query(
                lambda p, o: [
                    _fiche_result(
                        [
                            {
                                "position": "Point A",
                                "citation": "citation",
                                "url": "https://exemple.test",
                                "famille": "preuve_ia",
                                "date": "12 mars 2026",
                            }
                        ]
                    )
                ]
            ),
        )

        asyncio.run(fiche_service.run_fiche(offer_id))

        fiche = fiche_api.get_fiche(offer_id)
        point = fiche["points"][0]
        assert point["famille"] == "preuve_ia"
        assert point["date"] == "12 mars 2026"


# --- critère 7 -----------------------------------------------------------------


class TestCritere7PointSansDateGarde:
    def test_point_sans_date_est_garde_sans_date(self, db_path, monkeypatch):
        offer_id = 7
        _insert_offer(db_path, offer_id)
        monkeypatch.setattr(
            fiche_service,
            "query",
            _make_query(
                lambda p, o: [
                    _fiche_result(
                        [
                            {
                                "position": "Point sans date",
                                "citation": "citation",
                                "url": None,
                                "famille": "facon_de_travailler",
                            }
                        ]
                    )
                ]
            ),
        )

        asyncio.run(fiche_service.run_fiche(offer_id))

        points = _points_json(db_path, offer_id)
        assert len(points) == 1
        assert points[0]["position"] == "Point sans date"
        assert points[0]["date"] is None


# --- critère 8 -----------------------------------------------------------------


class TestCritere8FamilleHorsVocabulaireEcartee:
    def test_point_avec_famille_inconnue_garde_sans_famille(self, db_path, monkeypatch):
        offer_id = 8
        _insert_offer(db_path, offer_id)
        monkeypatch.setattr(
            fiche_service,
            "query",
            _make_query(
                lambda p, o: [
                    _fiche_result(
                        [
                            {
                                "position": "Point famille inconnue",
                                "citation": "citation",
                                "url": None,
                                "famille": "pas_une_vraie_famille",
                                "date": "2026",
                            }
                        ]
                    )
                ]
            ),
        )

        asyncio.run(fiche_service.run_fiche(offer_id))

        points = _points_json(db_path, offer_id)
        assert len(points) == 1
        assert points[0]["position"] == "Point famille inconnue"
        assert points[0]["famille"] is None
        assert points[0]["date"] == "2026"


# --- critère 9 -----------------------------------------------------------------


class TestCritere9RepertoireAbsent:
    def test_fiche_produite_quand_meme_repertoire_absent(self, db_path, monkeypatch):
        offer_id = 9
        _insert_offer(db_path, offer_id)
        monkeypatch.setattr(
            fiche_service,
            "query",
            _make_query(
                lambda p, o: [
                    _fiche_result([{"position": "Point", "citation": "c", "url": None}])
                ]
            ),
        )

        asyncio.run(fiche_service.run_fiche(offer_id))

        row = _fiche_row(db_path, offer_id)
        assert row["statut"] == "done"
        assert "Sujet distinctif de" not in row["prompt_text"]


# --- critère 10 ----------------------------------------------------------------


class TestCritere10RepertoireMalForme:
    def test_fiche_produite_quand_meme_repertoire_mal_forme(
        self, db_path, tmp_path, monkeypatch
    ):
        chemin = tmp_path / "repertoire_mal_forme.yaml"
        chemin.write_text(":\n  - ceci n'est pas un YAML valide: [", encoding="utf-8")
        monkeypatch.setattr(fiche_prompt, "REPERTOIRE_LETTRE_PATH", chemin)
        offer_id = 10
        _insert_offer(db_path, offer_id)
        monkeypatch.setattr(
            fiche_service,
            "query",
            _make_query(
                lambda p, o: [
                    _fiche_result([{"position": "Point", "citation": "c", "url": None}])
                ]
            ),
        )

        asyncio.run(fiche_service.run_fiche(offer_id))

        row = _fiche_row(db_path, offer_id)
        assert row["statut"] == "done"


# --- critère 11 ----------------------------------------------------------------


class TestCritere11ChampATrouAbsentDeLaDemande:
    def test_champ_a_trou_n_apparait_pas_dans_le_prompt(
        self, db_path, tmp_path, monkeypatch
    ):
        donnees = _repertoire_bien_forme()
        donnees["textes_types"][0]["s_applique_si"] = (
            "[À COMPLÉTER : condition d'usage pas encore écrite]"
        )
        chemin = _ecrire_repertoire(tmp_path, donnees)
        monkeypatch.setattr(fiche_prompt, "REPERTOIRE_LETTRE_PATH", chemin)
        _insert_offer(db_path, 1)
        offer = _offer_row(db_path, 1)

        prompt = fiche_prompt.build_prompt(offer, _cascade())

        assert "[À COMPLÉTER" not in prompt
        # Le sujet du texte type reste présent : seul le champ à trou a disparu.
        assert f"Sujet distinctif de {IDS_TEXTES_TYPES_NON_GENERIQUES[0]}" in prompt


# --- critère 12 ----------------------------------------------------------------


class TestCritere12FicheAncienneSansFamilleNiDate:
    def test_points_d_une_fiche_anterieure_affiches_sans_famille_ni_date(self, db_path):
        offer_id = 12
        _insert_offer(db_path, offer_id)
        points_anciens = [
            {
                "position": "Point ancien",
                "citation": "citation",
                "url": None,
                "tas": None,
                "explication": None,
                "pour_lettre": False,
            }
        ]
        _insert_fiche_ancienne(db_path, offer_id, points_anciens)

        fiche = fiche_api.get_fiche(offer_id)

        point = fiche["points"][0]
        assert point["position"] == "Point ancien"
        assert "famille" not in point
        assert "date" not in point


# --- critère 13 ----------------------------------------------------------------


class TestCritere13PlafondQuatrePointsPourLettreTenu:
    def test_points_pour_lettre_rendu_par_le_modele_est_ignore(
        self, db_path, monkeypatch
    ):
        # EXE-161, critère 2 : la fiche ne désigne plus elle-même de points pour
        # la lettre — `points_pour_lettre`, même rendu par le modèle, est ignoré.
        offer_id = 13
        _insert_offer(db_path, offer_id)
        monkeypatch.setattr(
            fiche_service,
            "query",
            _make_query(
                lambda p, o: [
                    _fiche_result(
                        [
                            {
                                "position": f"Point {i}",
                                "citation": f"c{i}",
                                "url": None,
                                "famille": "preuve_ia",
                                "date": "2026",
                            }
                            for i in range(6)
                        ],
                        points_pour_lettre=[0, 1, 2, 3, 4, 5],
                    )
                ]
            ),
        )

        asyncio.run(fiche_service.run_fiche(offer_id))

        points = _points_json(db_path, offer_id)
        designes = [i for i, p in enumerate(points) if p.get("pour_lettre")]
        assert designes == []
