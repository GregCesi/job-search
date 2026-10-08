"""Tests EXE-151 — le banc de la lettre prépare un jeu d'évaluation figé et ne
lit plus la base de l'application.

Aucun test n'appelle un modèle réel ou le web : `fiche_service.query` (SDK)
est remplacé par une doublure, `jeu.identify_employer` aussi, et
`boucle.appeler_modele` est remplacé par la doublure programmable reprise de
test_exe147_boucle_lettre.py pour les tests du banc. Aucun test ne lit ni
n'écrit sous data/ : base, répertoire, CV de référence, tournures interdites,
rapports et jeux sont posés dans tmp_path.
"""

import asyncio
import json
import sqlite3

import pytest
import yaml
from claude_agent_sdk import ResultMessage
from mlflow.tracking import MlflowClient

import orchestrator.job_search.fiche.prompt as fiche_prompt
import orchestrator.job_search.fiche.service as fiche_service
import orchestrator.job_search.lettre.boucle as boucle
import orchestrator.job_search.lettre.jeu as jeu_module
from orchestrator.job_search.fiche.cascade import CascadeResult
from orchestrator.job_search.lettre import banc
from orchestrator.job_search.lettre.boucle import ReponseModele
from orchestrator.job_search.lettre.redaction import RAISON_TEXTE_MANQUANT
from orchestrator.job_search.storage.db import init_db

CV_HTML = "<html><body><p>Contenu CV de test</p></body></html>"
TOURNURES_INTERDITES = "je veux\n"


# --- doublures de modèle ----------------------------------------------------


def _make_query(behavior):
    """behavior(prompt, options) -> liste de messages à produire."""

    async def _query(*, prompt, options):
        for m in behavior(prompt, options):
            yield m

    return _query


def _fiche_result(points, points_pour_lettre, session_id="s", cost=0.1, nom="ACME"):
    return ResultMessage(
        subtype="success",
        duration_ms=1,
        duration_api_ms=1,
        is_error=False,
        num_turns=1,
        session_id=session_id,
        total_cost_usd=cost,
        result=None,
        structured_output={
            "mode": "entreprise",
            "presentation": "Présentation.",
            "employeur": {
                "nom": nom,
                "entite_precise": None,
                "type_source": "direct",
                "methode": "test",
                "confiance": "sur",
                "urls": [],
            },
            "points": points,
            "points_pour_lettre": points_pour_lettre,
        },
    )


def _cascade(nom="ACME") -> CascadeResult:
    return CascadeResult(
        nom=nom,
        entite=None,
        confiance="sur",
        type_source="direct",
        methode="t",
        etape=1,
    )


class FakeModeles:
    """Doublure programmable de `boucle.appeler_modele` (reprise de
    test_exe147_boucle_lettre.py)."""

    def __init__(self):
        self.files = {"tamis": [], "redaction": [], "juge": []}
        self.appels = []

    def programmer(self, noeud, *valeurs):
        self.files[noeud].extend(valeurs)

    def __call__(self, noeud, modele, prompt_text, schema=None):
        self.appels.append((noeud, modele, prompt_text))
        valeur = self.files[noeud].pop(0)
        if isinstance(valeur, BaseException):
            raise valeur
        cout = 0.01 if modele in boucle.MODELES_CLAUDE else None
        return ReponseModele(texte=valeur, duree_s=0.01, cout_usd=cout)


@pytest.fixture
def modeles(monkeypatch):
    fake = FakeModeles()
    monkeypatch.setattr(boucle, "appeler_modele", fake)
    return fake


_TAMIS_POINT_0 = json.dumps({"point_index": 0, "texte_type_id": "prototyper"})
_TAMIS_GENERIQUE = json.dumps({"point_index": None, "texte_type_id": "generique"})
_JUGE_RIEN_A_REDIRE = json.dumps(
    {
        "rien_a_redire": True,
        "ressenti": "Rien à redire.",
        "details": "Rien à redire.",
        "reussites": "Rien à redire.",
        "verdict": "Rien à redire.",
    }
)


def _programmer_passage_simple(modeles, lettre="Lettre finale.", tamis=_TAMIS_POINT_0):
    modeles.programmer("tamis", tamis)
    modeles.programmer("redaction", lettre)
    modeles.programmer("juge", _JUGE_RIEN_A_REDIRE)


# --- fixtures de terrain (boucle) -------------------------------------------


def _repertoire_donnees() -> dict:
    return {
        "version": 1,
        "posture": {"role": "ingénieur", "regles": ["jamais de superlatif"]},
        "forme": {"longueur_cible_mots": 160},
        "textes_types": [
            {
                "id": "prototyper",
                "sujet": "sujet de prototyper",
                "conviction": "conviction de prototyper",
                "ce_que_j_ai_fait": "ce que j'ai fait",
                "texte": "texte rédigé de prototyper",
                "exemples": [],
            },
            {
                "id": "generique",
                "sujet": "sujet générique",
                "conviction": "conviction générique",
                "ce_que_j_ai_fait": "ce que j'ai fait",
                "texte": "texte générique rédigé",
                "exemples": [],
            },
        ],
        "juge": {
            "consigne": "Consigne du juge.",
            "contexte": "Contexte du juge.",
        },
        "redaction": {"consigne_reprise": "Consigne de reprise."},
    }


@pytest.fixture
def repertoire_path(tmp_path):
    chemin = tmp_path / "repertoire.yaml"
    chemin.write_text(
        yaml.safe_dump(_repertoire_donnees(), allow_unicode=True), encoding="utf-8"
    )
    return chemin


@pytest.fixture
def cv_path(tmp_path):
    chemin = tmp_path / "cv_reference.html"
    chemin.write_text(CV_HTML, encoding="utf-8")
    return chemin


@pytest.fixture
def tournures_path(tmp_path):
    chemin = tmp_path / "tournures_interdites.txt"
    chemin.write_text(TOURNURES_INTERDITES, encoding="utf-8")
    return chemin


@pytest.fixture
def banc_dir(tmp_path):
    return tmp_path / "banc"


@pytest.fixture
def jeux_dir(tmp_path):
    return tmp_path / "jeux"


# --- fixtures de terrain (base, pour la préparation du jeu) -----------------


@pytest.fixture
def db_path(tmp_path):
    chemin = tmp_path / "job_search.sqlite"
    conn = sqlite3.connect(chemin)
    init_db(conn)
    conn.close()
    return chemin


def _conn(db_path):
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn


def _poser_offre(
    conn,
    offer_id,
    *,
    retenue=True,
    texte="Texte de l'offre.",
    titre="Titre de l'offre",
    entreprise="Entreprise X SAS",
):
    conn.execute(
        "INSERT INTO offers (id, source, source_id, fingerprint, title, company, "
        "description_raw) VALUES (?, 'test', ?, 'fp', ?, ?, ?)",
        (offer_id, str(offer_id), titre, entreprise, texte),
    )
    if retenue:
        conn.execute(
            "INSERT INTO verdicts (offer_id, status, created_at) VALUES (?, 'retenu', '2026-10-07')",
            (offer_id,),
        )
    conn.commit()


def _dump_toutes_tables(conn) -> dict:
    tables = ["offers", "verdicts", "fiches_entreprise"]
    return {
        t: [dict(r) for r in conn.execute(f"SELECT * FROM {t}").fetchall()]
        for t in tables
    }


@pytest.fixture(autouse=True)
def _identify_employer_par_defaut(monkeypatch):
    """Doublure déterministe de la cascade — jamais de réseau (H1 du ticket)."""
    monkeypatch.setattr(
        jeu_module, "identify_employer", lambda offer_id, conn: _cascade()
    )


# =============================================================================
# Préparation du jeu (critères 1-12)
# =============================================================================


def test_critere1_jeu_porte_numero_intitule_entreprise_texte_et_faits(
    db_path, jeux_dir, monkeypatch
):
    conn = _conn(db_path)
    _poser_offre(conn, 179, titre="Dev IA", entreprise="ACME SAS", texte="Texte 179.")
    _poser_offre(
        conn, 1677, titre="Dev Backend", entreprise="Beta", texte="Texte 1677."
    )
    conn.close()

    monkeypatch.setattr(
        fiche_service,
        "query",
        _make_query(lambda p, o: [_fiche_result([{"position": "Point 1"}], [])]),
    )

    conn = _conn(db_path)
    resultat = asyncio.run(
        jeu_module.preparer_jeu(conn, "essai1", [179, 1677], jeux_dir=jeux_dir)
    )
    conn.close()

    assert {o["offer_id"] for o in resultat.jeu["offres"]} == {179, 1677}
    entree = next(o for o in resultat.jeu["offres"] if o["offer_id"] == 179)
    assert entree["intitule"] == "Dev IA"
    assert entree["entreprise"] == "ACME"  # résolu par la cascade
    assert entree["texte_offre"] == "Texte 179."
    assert len(entree["faits"]) == 1


def test_critere2_fait_porte_les_quatre_champs_a_cote_de_la_position(
    db_path, jeux_dir, monkeypatch
):
    conn = _conn(db_path)
    _poser_offre(conn, 1)
    conn.close()
    monkeypatch.setattr(
        fiche_service,
        "query",
        _make_query(
            lambda p, o: [
                _fiche_result(
                    [
                        {
                            "position": "Pos",
                            "citation": "Cit",
                            "url": "https://ex.test",
                            "famille": "facon_de_travailler",
                            "date": "2026-01-01",
                        }
                    ],
                    [],
                )
            ]
        ),
    )

    conn = _conn(db_path)
    resultat = asyncio.run(
        jeu_module.preparer_jeu(conn, "essai", [1], jeux_dir=jeux_dir)
    )
    conn.close()

    fait = resultat.jeu["offres"][0]["faits"][0]
    assert fait == {
        "position": "Pos",
        "citation": "Cit",
        "url": "https://ex.test",
        "famille": "facon_de_travailler",
        "date": "2026-01-01",
    }


def test_critere3_famille_inconnue_gardee_sans_famille(db_path, jeux_dir, monkeypatch):
    conn = _conn(db_path)
    _poser_offre(conn, 1)
    conn.close()
    monkeypatch.setattr(
        fiche_service,
        "query",
        _make_query(
            lambda p, o: [
                _fiche_result([{"position": "Pos", "famille": "famille_inventee"}], [])
            ]
        ),
    )

    conn = _conn(db_path)
    resultat = asyncio.run(
        jeu_module.preparer_jeu(conn, "essai", [1], jeux_dir=jeux_dir)
    )
    conn.close()

    fait = resultat.jeu["offres"][0]["faits"][0]
    assert fait["position"] == "Pos"
    assert fait["famille"] is None


def test_critere4_recherche_recoit_la_meme_demande_que_la_fiche_de_lapplication(
    db_path, jeux_dir, monkeypatch
):
    conn = _conn(db_path)
    _poser_offre(conn, 1, titre="Dev", entreprise="ACME", texte="Texte offre.")
    conn.close()

    repertoire_fiche_path = jeux_dir.parent / "repertoire_fiche.yaml"
    repertoire_fiche_path.write_text(
        yaml.safe_dump(
            {
                "version": 1,
                "textes_types": [
                    {"id": "prototyper", "sujet": "sujet unique A", "texte": "texte A"},
                    {"id": "generique", "sujet": "sujet générique", "texte": "texte G"},
                ],
                "sujets_interdits": [
                    {"sujet": "argent facile", "motif": "pas convaincant"}
                ],
            },
            allow_unicode=True,
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(fiche_prompt, "REPERTOIRE_LETTRE_PATH", repertoire_fiche_path)
    monkeypatch.setattr(
        jeu_module, "identify_employer", lambda offer_id, conn: _cascade()
    )

    captured = {}

    async def _query(*, prompt, options):
        captured["prompt"] = prompt
        yield _fiche_result([], [])

    monkeypatch.setattr(fiche_service, "query", _query)

    conn = _conn(db_path)
    offer_row = conn.execute(
        "SELECT title, company, location, url, description, description_raw "
        "FROM offers WHERE id = 1"
    ).fetchone()
    asyncio.run(jeu_module.preparer_jeu(conn, "essai", [1], jeux_dir=jeux_dir))
    conn.close()

    demande_attendue = fiche_prompt.build_prompt(offer_row, _cascade())
    assert captured["prompt"] == demande_attendue
    assert "sujet unique A" in captured["prompt"]
    assert "argent facile" in captured["prompt"]


def test_critere5_base_inchangee_apres_preparation(db_path, jeux_dir, monkeypatch):
    conn = _conn(db_path)
    _poser_offre(conn, 1)
    conn.close()
    monkeypatch.setattr(
        fiche_service,
        "query",
        _make_query(lambda p, o: [_fiche_result([{"position": "P"}], [])]),
    )

    conn = _conn(db_path)
    avant = _dump_toutes_tables(conn)
    asyncio.run(jeu_module.preparer_jeu(conn, "essai", [1], jeux_dir=jeux_dir))
    apres = _dump_toutes_tables(conn)
    conn.close()

    assert avant == apres


def test_criteres6_7_8_offres_sautees_avec_raison_les_autres_preparees(
    db_path, jeux_dir, monkeypatch
):
    conn = _conn(db_path)
    _poser_offre(conn, 1)  # ok
    _poser_offre(conn, 2, retenue=False)  # non retenue
    _poser_offre(conn, 3, texte="")  # texte manquant
    # offre 4 absente de la base
    conn.close()
    monkeypatch.setattr(
        fiche_service,
        "query",
        _make_query(lambda p, o: [_fiche_result([{"position": "P"}], [])]),
    )

    conn = _conn(db_path)
    resultat = asyncio.run(
        jeu_module.preparer_jeu(conn, "essai", [1, 2, 3, 4], jeux_dir=jeux_dir)
    )
    conn.close()

    assert {o["offer_id"] for o in resultat.jeu["offres"]} == {1}
    lignes = resultat.lignes_resume
    assert any(
        "offre 2" in ligne and jeu_module.RAISON_NON_RETENUE in ligne
        for ligne in lignes
    )
    assert any(
        "offre 3" in ligne and RAISON_TEXTE_MANQUANT in ligne for ligne in lignes
    )
    assert any(
        "offre 4" in ligne and jeu_module.RAISON_OFFRE_INTROUVABLE in ligne
        for ligne in lignes
    )


def test_critere9_echec_recherche_offre_figure_sans_fait_avec_raison(
    db_path, jeux_dir, monkeypatch
):
    conn = _conn(db_path)
    _poser_offre(conn, 1)
    _poser_offre(conn, 2)
    conn.close()

    appels = {"n": 0}

    async def _query(*, prompt, options):
        appels["n"] += 1
        if appels["n"] == 1:
            raise RuntimeError("panne réseau")
        yield _fiche_result([{"position": "P"}], [])

    monkeypatch.setattr(fiche_service, "query", _query)

    conn = _conn(db_path)
    resultat = asyncio.run(
        jeu_module.preparer_jeu(conn, "essai", [1, 2], jeux_dir=jeux_dir)
    )
    conn.close()

    entree1 = next(o for o in resultat.jeu["offres"] if o["offer_id"] == 1)
    assert entree1["faits"] == []
    assert entree1["raison_echec_recherche"]
    assert "échoué" in entree1["raison_echec_recherche"]

    entree2 = next(o for o in resultat.jeu["offres"] if o["offer_id"] == 2)
    assert entree2["raison_echec_recherche"] is None
    assert len(entree2["faits"]) == 1


def test_critere9_reponse_illisible_offre_figure_sans_fait_avec_raison(
    db_path, jeux_dir, monkeypatch
):
    conn = _conn(db_path)
    _poser_offre(conn, 1)
    conn.close()

    async def _query(*, prompt, options):
        yield ResultMessage(
            subtype="success",
            duration_ms=1,
            duration_api_ms=1,
            is_error=False,
            num_turns=1,
            session_id="s",
            total_cost_usd=0.1,
            result="n'est pas du JSON",
            structured_output=None,
        )

    monkeypatch.setattr(fiche_service, "query", _query)

    conn = _conn(db_path)
    resultat = asyncio.run(
        jeu_module.preparer_jeu(conn, "essai", [1], jeux_dir=jeux_dir)
    )
    conn.close()

    entree = resultat.jeu["offres"][0]
    assert entree["faits"] == []
    assert entree["raison_echec_recherche"]


def test_critere10_nom_deja_pris_refuse_sans_appeler_de_modele(db_path, jeux_dir):
    jeux_dir.mkdir(parents=True)
    chemin = jeux_dir / "essai.json"
    contenu_existant = '{"nom": "essai", "prepare_le": "x", "offres": []}'
    chemin.write_text(contenu_existant, encoding="utf-8")

    conn = _conn(db_path)
    _poser_offre(conn, 1)

    def _jamais_identifie(*a, **k):
        raise AssertionError("identify_employer appelé malgré le nom déjà pris")

    def _jamais_query(*, prompt, options):
        raise AssertionError("query appelé malgré le nom déjà pris")

    import orchestrator.job_search.lettre.jeu as _jm

    original_identify = _jm.identify_employer
    original_query = fiche_service.query
    _jm.identify_employer = _jamais_identifie
    fiche_service.query = _jamais_query
    try:
        with pytest.raises(jeu_module.JeuExistantError):
            asyncio.run(jeu_module.preparer_jeu(conn, "essai", [1], jeux_dir=jeux_dir))
    finally:
        _jm.identify_employer = original_identify
        fiche_service.query = original_query
        conn.close()

    assert chemin.read_text(encoding="utf-8") == contenu_existant


def test_critere11_jeu_porte_la_date_de_preparation(db_path, jeux_dir, monkeypatch):
    conn = _conn(db_path)
    _poser_offre(conn, 1)
    conn.close()
    monkeypatch.setattr(
        fiche_service,
        "query",
        _make_query(lambda p, o: [_fiche_result([{"position": "P"}], [])]),
    )

    conn = _conn(db_path)
    resultat = asyncio.run(
        jeu_module.preparer_jeu(conn, "essai", [1], jeux_dir=jeux_dir)
    )
    conn.close()

    assert resultat.jeu["prepare_le"]


def test_critere12_une_ligne_par_offre_avec_duree_et_cout(
    db_path, jeux_dir, monkeypatch
):
    conn = _conn(db_path)
    _poser_offre(conn, 1)
    _poser_offre(conn, 2, retenue=False)
    conn.close()
    monkeypatch.setattr(
        fiche_service,
        "query",
        _make_query(lambda p, o: [_fiche_result([{"position": "P"}], [], cost=0.25)]),
    )

    conn = _conn(db_path)
    resultat = asyncio.run(
        jeu_module.preparer_jeu(conn, "essai", [1, 2], jeux_dir=jeux_dir)
    )
    conn.close()

    assert len(resultat.lignes_resume) == 2
    ligne1 = next(ligne for ligne in resultat.lignes_resume if "offre 1 " in ligne)
    assert "1 fait(s)" in ligne1
    assert "0.25" in ligne1 or "0.2500" in ligne1
    ligne2 = next(ligne for ligne in resultat.lignes_resume if "offre 2 " in ligne)
    assert jeu_module.RAISON_NON_RETENUE in ligne2


# =============================================================================
# Le banc lit un jeu, n'ouvre jamais la base (critères 13-22)
# =============================================================================


def _jeu(nom="essai", offres=None) -> dict:
    return {"nom": nom, "prepare_le": "2026-10-07T00:00:00Z", "offres": offres or []}


def _entree_jeu(
    offer_id,
    *,
    titre="Titre",
    entreprise="ACME",
    texte="Texte offre.",
    faits=None,
    raison_echec_recherche=None,
):
    return {
        "offer_id": offer_id,
        "intitule": titre,
        "entreprise": entreprise,
        "texte_offre": texte,
        "faits": faits or [],
        "raison_echec_recherche": raison_echec_recherche,
    }


def _lancer(
    jeu,
    offer_ids,
    config_specs,
    repertoire_path,
    cv_path,
    tournures_path,
    banc_dir,
    jeu_path=None,
    tracker_factory=None,
):
    kwargs = dict(
        repertoire_path=repertoire_path,
        cv_reference_path=cv_path,
        tournures_path=tournures_path,
        banc_dir=banc_dir,
    )
    if jeu_path is not None:
        kwargs["jeu_path"] = jeu_path
    if tracker_factory is not None:
        kwargs["tracker_factory"] = tracker_factory
    return banc.lancer_banc(jeu, offer_ids, config_specs, **kwargs)


def test_critere13_tamis_recoit_les_faits_du_jeu_dans_l_ordre_du_jeu(
    repertoire_path, cv_path, tournures_path, banc_dir, modeles
):
    faits = [
        {
            "position": "P0",
            "citation": "C0",
            "url": None,
            "famille": None,
            "date": None,
        },
        {
            "position": "P1",
            "citation": "C1",
            "url": None,
            "famille": None,
            "date": None,
        },
    ]
    jeu = _jeu(offres=[_entree_jeu(1, faits=faits)])
    _programmer_passage_simple(modeles)

    _lancer(jeu, None, ["sonnet"], repertoire_path, cv_path, tournures_path, banc_dir)

    prompt_tamis = next(p for n, m, p in modeles.appels if n == "tamis")
    assert prompt_tamis.index("C0") < prompt_tamis.index("C1")


def test_critere14_banc_sur_jeu_sans_base_les_lettres_s_ecrivent(
    repertoire_path, cv_path, tournures_path, banc_dir, modeles
):
    jeu = _jeu(offres=[_entree_jeu(1)])
    _programmer_passage_simple(modeles, lettre="Une lettre.")

    resultat = _lancer(
        jeu, None, ["sonnet"], repertoire_path, cv_path, tournures_path, banc_dir
    )

    assert resultat.passages[0].resultat.lettres[-1]["texte"] == "Une lettre."


def test_critere15_sans_jeu_refuse_sans_appeler_de_modele(modeles):
    with pytest.raises(SystemExit):
        banc.main(["--config", "sonnet"])
    assert modeles.appels == []


def test_critere16_jeu_introuvable_refuse_sans_appeler_de_modele(
    repertoire_path, cv_path, tournures_path, banc_dir, jeux_dir, modeles
):
    code = banc.main(
        ["--jeu", "inexistant", "--config", "sonnet"],
        repertoire_path=repertoire_path,
        cv_reference_path=cv_path,
        tournures_path=tournures_path,
        banc_dir=banc_dir,
        jeux_dir=jeux_dir,
    )
    assert code == 1
    assert modeles.appels == []


def test_critere16_jeu_illisible_refuse_sans_appeler_de_modele(
    repertoire_path, cv_path, tournures_path, banc_dir, jeux_dir, modeles
):
    jeux_dir.mkdir(parents=True)
    (jeux_dir / "casse.json").write_text("{pas du json", encoding="utf-8")

    code = banc.main(
        ["--jeu", "casse", "--config", "sonnet"],
        repertoire_path=repertoire_path,
        cv_reference_path=cv_path,
        tournures_path=tournures_path,
        banc_dir=banc_dir,
        jeux_dir=jeux_dir,
    )
    assert code == 1
    assert modeles.appels == []


def test_critere17_offre_avec_raison_d_echec_sautee_pour_toutes_les_configs(
    repertoire_path, cv_path, tournures_path, banc_dir, modeles
):
    jeu = _jeu(
        offres=[_entree_jeu(1, raison_echec_recherche="la recherche a échoué : x")]
    )

    resultat = _lancer(
        jeu,
        None,
        ["sonnet", "opus"],
        repertoire_path,
        cv_path,
        tournures_path,
        banc_dir,
    )

    assert modeles.appels == []
    assert all(p.skip_reason == "la recherche a échoué : x" for p in resultat.passages)


def test_critere18_zero_fait_passe_dans_la_boucle_comme_sans_accroche(
    repertoire_path, cv_path, tournures_path, banc_dir, modeles
):
    jeu = _jeu(offres=[_entree_jeu(1, faits=[])])
    _programmer_passage_simple(modeles, tamis=_TAMIS_GENERIQUE)

    resultat = _lancer(
        jeu, None, ["sonnet"], repertoire_path, cv_path, tournures_path, banc_dir
    )

    passage = resultat.passages[0]
    assert passage.skip_reason is None
    assert passage.resultat is not None
    assert passage.resultat.texte_type_id == "generique"


def test_critere19_offres_limitees_et_dans_l_ordre_demande(
    repertoire_path, cv_path, tournures_path, banc_dir, modeles
):
    jeu = _jeu(offres=[_entree_jeu(1), _entree_jeu(2), _entree_jeu(3)])
    _programmer_passage_simple(modeles)
    _programmer_passage_simple(modeles)

    resultat = _lancer(
        jeu, [3, 1], ["sonnet"], repertoire_path, cv_path, tournures_path, banc_dir
    )

    assert [p.offer_id for p in resultat.passages] == [3, 1]


def test_critere20_offre_absente_du_jeu_sautee_pour_toutes_les_configs(
    repertoire_path, cv_path, tournures_path, banc_dir, modeles
):
    jeu = _jeu(offres=[_entree_jeu(1)])

    resultat = _lancer(
        jeu,
        [99],
        ["sonnet", "opus"],
        repertoire_path,
        cv_path,
        tournures_path,
        banc_dir,
    )

    assert modeles.appels == []
    assert all(p.skip_reason == banc.RAISON_ABSENTE_DU_JEU for p in resultat.passages)


def test_critere21_rapport_nomme_le_jeu_dans_l_en_tete(
    repertoire_path, cv_path, tournures_path, banc_dir, modeles
):
    jeu = _jeu(nom="jeu-reference", offres=[_entree_jeu(1)])
    _programmer_passage_simple(modeles)

    resultat = _lancer(
        jeu, None, ["sonnet"], repertoire_path, cv_path, tournures_path, banc_dir
    )

    texte = resultat.rapport_path.read_text(encoding="utf-8")
    assert "Jeu : jeu-reference" in texte


def test_critere22_run_mlflow_porte_le_jeu_en_parametre_et_en_piece(
    repertoire_path, cv_path, tournures_path, banc_dir, jeux_dir, modeles
):
    jeux_dir.mkdir(parents=True)
    jeu_path = jeux_dir / "essai.json"
    jeu = _jeu(nom="essai", offres=[_entree_jeu(1)])
    jeu_path.write_text(json.dumps(jeu), encoding="utf-8")
    _programmer_passage_simple(modeles)

    _lancer(
        jeu,
        None,
        ["sonnet"],
        repertoire_path,
        cv_path,
        tournures_path,
        banc_dir,
        jeu_path=jeu_path,
    )

    client = MlflowClient()
    experiment = client.get_experiment_by_name(banc.EXPERIMENT_NAME)
    run = client.search_runs([experiment.experiment_id])[0]
    assert run.data.params["jeu"] == "essai"
    artefacts = {a.path for a in client.list_artifacts(run.info.run_id)}
    assert "essai.json" in artefacts


# --- invariants « ce qui ne doit pas arriver » ------------------------------


def test_banc_n_ouvre_jamais_la_base(
    repertoire_path, cv_path, tournures_path, banc_dir, modeles, monkeypatch
):
    def _interdit(*a, **k):
        raise AssertionError("le banc a ouvert une connexion sqlite3")

    monkeypatch.setattr(sqlite3, "connect", _interdit)

    jeu = _jeu(offres=[_entree_jeu(1)])
    _programmer_passage_simple(modeles)

    _lancer(jeu, None, ["sonnet"], repertoire_path, cv_path, tournures_path, banc_dir)
