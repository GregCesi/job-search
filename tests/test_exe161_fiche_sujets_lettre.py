"""Tests EXE-161 — la fiche entreprise cherche par mes sujets de lettre, et chaque
point dit le sujet qu'il sert.

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
import orchestrator.job_search.fiche.prompt as fiche_prompt
import orchestrator.job_search.fiche.service as fiche_service
import orchestrator.job_search.lettre.boucle as lettre_boucle
import orchestrator.job_search.lettre.jeu as lettre_jeu
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
        "version": 4,
        "sujets_interdits": [
            {
                "sujet": "Claude / Anthropic",
                "motif": "l'entreprise visée n'en parle pas",
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


def _fiche_result(points, session_id="fiche-session"):
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
    """Fiche produite avant EXE-161 (critère 7) : `points_json` sans `sujet`."""
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


# --- critère 1 -------------------------------------------------------------


class TestCritere1SujetsAvecIdentifiantLibelleConditions:
    def test_le_prompt_liste_identifiant_libelle_conditions_generique_exclu(
        self, db_path, tmp_path, monkeypatch
    ):
        chemin = _ecrire_repertoire(tmp_path, _repertoire_bien_forme())
        monkeypatch.setattr(fiche_prompt, "REPERTOIRE_LETTRE_PATH", chemin)
        _insert_offer(db_path, 1)
        offer = _offer_row(db_path, 1)

        prompt = fiche_prompt.build_prompt(offer, _cascade())

        for identifiant in IDS_TEXTES_TYPES_NON_GENERIQUES:
            # L'identifiant est donné à côté du libellé, pas seulement cité dans une
            # condition d'usage — marqueur qui force le format « - id : libellé ».
            assert f"{identifiant} : Sujet distinctif de {identifiant}" in prompt
            assert f"condition d'usage de {identifiant}" in prompt
            assert f"contre-indication de {identifiant}" in prompt
        assert "generique : Sujet distinctif de generique" not in prompt
        assert "Sujet distinctif de generique" not in prompt

    def test_les_sujets_interdits_suivent_mes_sujets(
        self, db_path, tmp_path, monkeypatch
    ):
        chemin = _ecrire_repertoire(tmp_path, _repertoire_bien_forme())
        monkeypatch.setattr(fiche_prompt, "REPERTOIRE_LETTRE_PATH", chemin)
        _insert_offer(db_path, 1)
        offer = _offer_row(db_path, 1)

        prompt = fiche_prompt.build_prompt(offer, _cascade())

        premier_id = IDS_TEXTES_TYPES_NON_GENERIQUES[0]
        idx_sujets = prompt.index(f"{premier_id} : Sujet distinctif de {premier_id}")
        idx_interdits = prompt.index("Claude / Anthropic")
        assert idx_sujets < idx_interdits


# --- critère 2 -------------------------------------------------------------


class TestCritere2PasDeDesignationPourLaLettre:
    def test_la_consigne_points_pour_lettre_n_est_plus_dans_le_prompt(self, db_path):
        _insert_offer(db_path, 1)
        offer = _offer_row(db_path, 1)

        prompt = fiche_prompt.build_prompt(offer, _cascade())

        assert "points_pour_lettre" not in prompt

    def test_aucun_point_produit_ne_porte_une_designation_vraie(
        self, db_path, monkeypatch
    ):
        offer_id = 2
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
                            }
                            for i in range(3)
                        ]
                    )
                ]
            ),
        )

        asyncio.run(fiche_service.run_fiche(offer_id))

        points = _points_json(db_path, offer_id)
        assert all(p.get("pour_lettre") is False for p in points)


# --- critère 3 -------------------------------------------------------------


class TestCritere3RepertoireAbsentOuMalFormeSansSujets:
    def test_repertoire_absent_fiche_tourne_avec_demande_generale_seule(
        self, db_path, monkeypatch
    ):
        offer_id = 3
        _insert_offer(db_path, offer_id)
        offer = _offer_row(db_path, offer_id)

        prompt = fiche_prompt.build_prompt(offer, _cascade())

        assert "mes textes prêts" not in prompt.lower()

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

    def test_repertoire_mal_forme_fiche_tourne_quand_meme(
        self, db_path, tmp_path, monkeypatch
    ):
        chemin = tmp_path / "repertoire_mal_forme.yaml"
        chemin.write_text(":\n  - ceci n'est pas un YAML valide: [", encoding="utf-8")
        monkeypatch.setattr(fiche_prompt, "REPERTOIRE_LETTRE_PATH", chemin)
        offer_id = 30
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


# --- critère 4 -------------------------------------------------------------


class TestCritere4ChaquePointPorteUnChampSujet:
    def test_point_avec_sujet_valide_le_garde(self, db_path, tmp_path, monkeypatch):
        chemin = _ecrire_repertoire(tmp_path, _repertoire_bien_forme())
        monkeypatch.setattr(fiche_prompt, "REPERTOIRE_LETTRE_PATH", chemin)
        offer_id = 4
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
                                "sujet": "prototyper",
                            }
                        ]
                    )
                ]
            ),
        )

        asyncio.run(fiche_service.run_fiche(offer_id))

        points = _points_json(db_path, offer_id)
        assert points[0]["sujet"] == "prototyper"

    def test_point_sans_sujet_rendu_a_null(self, db_path, tmp_path, monkeypatch):
        chemin = _ecrire_repertoire(tmp_path, _repertoire_bien_forme())
        monkeypatch.setattr(fiche_prompt, "REPERTOIRE_LETTRE_PATH", chemin)
        offer_id = 40
        _insert_offer(db_path, offer_id)
        monkeypatch.setattr(
            fiche_service,
            "query",
            _make_query(
                lambda p, o: [
                    _fiche_result(
                        [
                            {
                                "position": "Point passage annonce",
                                "citation": "citation",
                                "url": None,
                                "sujet": None,
                            }
                        ]
                    )
                ]
            ),
        )

        asyncio.run(fiche_service.run_fiche(offer_id))

        points = _points_json(db_path, offer_id)
        assert points[0]["sujet"] is None


# --- critère 5 -------------------------------------------------------------


class TestCritere5SujetHorsListeDevientNull:
    def test_sujet_rendu_hors_liste_devient_null_point_garde(
        self, db_path, tmp_path, monkeypatch
    ):
        chemin = _ecrire_repertoire(tmp_path, _repertoire_bien_forme())
        monkeypatch.setattr(fiche_prompt, "REPERTOIRE_LETTRE_PATH", chemin)
        offer_id = 5
        _insert_offer(db_path, offer_id)
        monkeypatch.setattr(
            fiche_service,
            "query",
            _make_query(
                lambda p, o: [
                    _fiche_result(
                        [
                            {
                                "position": "Point sujet inventé",
                                "citation": "citation",
                                "url": None,
                                "sujet": "pas_un_sujet_connu",
                            }
                        ]
                    )
                ]
            ),
        )

        asyncio.run(fiche_service.run_fiche(offer_id))

        points = _points_json(db_path, offer_id)
        assert len(points) == 1
        assert points[0]["position"] == "Point sujet inventé"
        assert points[0]["sujet"] is None

    def test_sujet_generique_rendu_par_le_modele_devient_null(
        self, db_path, tmp_path, monkeypatch
    ):
        chemin = _ecrire_repertoire(tmp_path, _repertoire_bien_forme())
        monkeypatch.setattr(fiche_prompt, "REPERTOIRE_LETTRE_PATH", chemin)
        offer_id = 50
        _insert_offer(db_path, offer_id)
        monkeypatch.setattr(
            fiche_service,
            "query",
            _make_query(
                lambda p, o: [
                    _fiche_result(
                        [
                            {
                                "position": "Point",
                                "citation": "citation",
                                "url": None,
                                "sujet": "generique",
                            }
                        ]
                    )
                ]
            ),
        )

        asyncio.run(fiche_service.run_fiche(offer_id))

        points = _points_json(db_path, offer_id)
        assert points[0]["sujet"] is None


# --- critère 6 -------------------------------------------------------------


class TestCritere6PointSansSujetNiCitationGarde:
    def test_point_sans_sujet_et_sans_citation_garde_tel_quel(
        self, db_path, monkeypatch
    ):
        offer_id = 6
        _insert_offer(db_path, offer_id)
        monkeypatch.setattr(
            fiche_service,
            "query",
            _make_query(
                lambda p, o: [
                    _fiche_result(
                        [{"position": "Point sans rien d'autre", "url": None}]
                    )
                ]
            ),
        )

        asyncio.run(fiche_service.run_fiche(offer_id))

        points = _points_json(db_path, offer_id)
        assert len(points) == 1
        assert points[0]["position"] == "Point sans rien d'autre"
        assert points[0]["citation"] is None
        assert points[0]["sujet"] is None


# --- critère 7 -------------------------------------------------------------


class TestCritere7FicheAncienneSansChampSujet:
    def test_point_d_une_fiche_anterieure_lu_avec_sujet_null(self, db_path):
        offer_id = 7
        _insert_offer(db_path, offer_id)
        points_anciens = [
            {
                "position": "Point ancien",
                "citation": "citation",
                "url": None,
                "tas": None,
                "explication": None,
                "pour_lettre": False,
                "famille": None,
                "date": None,
            }
        ]
        _insert_fiche_ancienne(db_path, offer_id, points_anciens)

        points = _points_json(db_path, offer_id)
        point = points[0]
        assert point["position"] == "Point ancien"
        # Rien n'a recalculé la fiche : la clé est simplement absente, lue comme
        # null par tout code qui la lit via `.get` (boucle, jeu).
        assert point.get("sujet") is None


# --- critère 8 -------------------------------------------------------------


class TestCritere8JeuGardeLeSujetDuFait:
    def test_fait_depuis_point_garde_sujet_famille_et_date(self):
        point = {
            "position": "Point",
            "citation": "citation",
            "url": "https://exemple.test",
            "sujet": "prototyper",
            "famille": "preuve_ia",
            "date": "12 mars 2026",
        }

        fait = lettre_jeu._fait_depuis_point(point)

        assert fait["sujet"] == "prototyper"
        assert fait["famille"] == "preuve_ia"
        assert fait["date"] == "12 mars 2026"

    def test_fait_depuis_point_sans_sujet_rend_sujet_null(self):
        point = {
            "position": "Point ancien",
            "citation": "citation",
            "url": None,
        }

        fait = lettre_jeu._fait_depuis_point(point)

        assert fait["sujet"] is None


# --- critère 9 -------------------------------------------------------------


class TestCritere9TamisRecoitLeSujetACoteDeFamilleEtDate:
    def test_texte_point_affiche_sujet_famille_et_date(self):
        point = {
            "position": "Point",
            "citation": "citation",
            "url": "https://exemple.test",
            "sujet": "prototyper",
            "famille": "preuve_ia",
            "date": "12 mars 2026",
        }

        texte = lettre_boucle._texte_point(point)

        assert "sujet : prototyper" in texte
        assert "famille : preuve_ia" in texte
        assert "date : 12 mars 2026" in texte

    def test_texte_point_sans_sujet_n_a_ni_rubrique_vide_ni_none(self):
        point = {
            "position": "Point",
            "citation": "citation",
            "url": None,
        }

        texte = lettre_boucle._texte_point(point)

        assert "sujet" not in texte
        assert "None" not in texte


# --- critère 10 ------------------------------------------------------------


class TestCritere10DemandeGeneraleContientMesSujets:
    def test_la_demande_generale_contient_mes_sujets(self):
        from orchestrator.job_search.paths import FICHE_COMMAND_PATH

        texte = FICHE_COMMAND_PATH.read_text(encoding="utf-8")
        assert "mes sujets" in texte
