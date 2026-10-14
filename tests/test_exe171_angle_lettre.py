"""Tests EXE-171 — j'écris mon angle pour la lettre : la régénération part de lui
au lieu du choix du tamis.

Deux paliers. D'abord la boucle (`generer_lettre_depuis_donnees`), appelée
directement, sans base — `boucle.appeler_modele` est remplacé par une doublure
programmable, comme dans test_exe147_boucle_lettre.py. Ensuite le service et
l'API, avec `generer_lettre_depuis_donnees` elle-même remplacée par une doublure,
la base posée dans un dossier temporaire — comme dans
test_exe166_choix_modele_lettre.py. Aucun test n'appelle un modèle réel, aucun
test ne lit ni n'écrit sous data/.
"""

import asyncio
import json
import sqlite3

import pytest
import yaml
from fastapi import HTTPException, Response

import api.db as api_db
import api.lettre as api_lettre
import orchestrator.job_search.lettre.boucle as boucle
import orchestrator.job_search.lettre.service as lettre_service
import orchestrator.job_search.storage.db as storage_db
from orchestrator.job_search.lettre.boucle import (
    GENERIQUE_ID,
    RAISON_RIEN_A_REDIRE,
    ConfigBoucle,
    Jugement,
    ReponseModele,
    ResultatBoucle,
    generer_lettre_depuis_donnees,
)
from orchestrator.job_search.storage.db import init_db

CV_HTML = "<html><body><p>Contenu CV de test</p></body></html>"
TOURNURES_INTERDITES = "je veux\nn'hésitez pas\n"

# ═══════════════════════════════════════════════════════════════════════════
# Palier 1 — la boucle (critères 1-4, 6, 7)
# ═══════════════════════════════════════════════════════════════════════════


class FakeModeles:
    """Même doublure que test_exe147_boucle_lettre.py : file programmable par
    nœud, trace des appels (noeud, modele, prompt_text)."""

    def __init__(self):
        self.files = {"tamis": [], "redaction": [], "juge": [], "verificateur": []}
        self.appels = []

    def programmer(self, noeud, *valeurs):
        self.files[noeud].extend(valeurs)

    def __call__(self, noeud, modele, prompt_text, schema=None):
        if noeud == "verificateur" and not self.files["verificateur"]:
            return ReponseModele(
                texte=json.dumps(
                    {"rien_a_signaler": True, "lieux": [], "affirmations": []}
                ),
                duree_s=0.01,
                cout_usd=0.01,
            )
        self.appels.append((noeud, modele, prompt_text))
        valeur = self.files[noeud].pop(0)
        if isinstance(valeur, BaseException):
            raise valeur
        return ReponseModele(texte=valeur, duree_s=0.01, cout_usd=0.01)


@pytest.fixture
def modeles(monkeypatch):
    fake = FakeModeles()
    monkeypatch.setattr(boucle, "appeler_modele", fake)
    return fake


def _config(modele="sonnet") -> ConfigBoucle:
    return ConfigBoucle(
        modele_tamis=modele, modele_redaction=modele, modele_juge=modele
    )


def _texte_type(identifiant: str, **overrides) -> dict:
    base = {
        "id": identifiant,
        "sujet": f"sujet de {identifiant}",
        "conviction": f"conviction de {identifiant}",
        "ce_que_j_ai_fait": f"ce que j'ai fait pour {identifiant}",
        "s_applique_si": f"condition d'usage de {identifiant}",
        "texte": f"texte rédigé de {identifiant}",
        "exemples": [],
    }
    base.update(overrides)
    return base


def _repertoire_donnees(generique_texte: str | None = "texte générique rédigé") -> dict:
    return {
        "version": 1,
        "posture": {
            "role": "ingénieur qui prototype vite",
            "quatre_temps": ["accroche", "preuve", "offre", "cta"],
            "regles": ["jamais de superlatif"],
            "formulations_rejetees": [],
        },
        "ce_qui_fait_une_bonne_accroche": ["un fait précis de l'entreprise"],
        "sujets_interdits": [
            {
                "sujet": "Claude / Anthropic",
                "motif": "l'entreprise visée n'en parle pas",
            }
        ],
        "conditions_generales": ["lettre en français"],
        "forme": {
            "blocs": ["accroche", "preuve", "offre", "cta"],
            "longueur_cible_mots": 160,
            "lettre_de_reference": None,
        },
        "textes_types": [
            _texte_type("prototyper"),
            _texte_type("generique", texte=generique_texte, exemples=[]),
        ],
        "juge": {"consigne": "Consigne du juge.", "contexte": "Contexte du juge."},
        "redaction": {
            "consigne_reprise": "Consigne de reprise.",
            "consigne_verification": "Consigne de correction.",
        },
        "verificateur": {"consigne": "Consigne du vérificateur."},
    }


@pytest.fixture
def repertoire_path(tmp_path):
    def _ecrire(generique_texte="texte générique rédigé"):
        chemin = tmp_path / "repertoire.yaml"
        donnees = _repertoire_donnees(generique_texte)
        chemin.write_text(yaml.safe_dump(donnees, allow_unicode=True), encoding="utf-8")
        return chemin

    return _ecrire


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


def _points_fiche() -> list[dict]:
    return [
        {
            "position": "Point 0",
            "citation": "Citation 0",
            "url": "https://exemple.test/0",
        }
    ]


_JUGE_RIEN_A_REDIRE = json.dumps(
    {
        "rien_a_redire": True,
        "ressenti": "Rien à redire.",
        "details": "Rien à redire.",
        "reussites": "Rien à redire.",
        "verdict": "Rien à redire.",
        "decision": "j'appelle",  # EXE-175, critère 1
    }
)

ANGLE = "J'ai lu votre dernier rapport RSE, ça m'a donné envie de vous écrire."


def _lancer(
    repertoire_path, cv_path, tournures_path, angle=None, points=None, config=None
):
    return generer_lettre_depuis_donnees(
        "Titre de l'offre",
        "Texte de l'offre",
        "Entreprise X",
        points if points is not None else _points_fiche(),
        config or _config(),
        repertoire_path=repertoire_path(),
        cv_reference_path=cv_path,
        tournures_path=tournures_path,
        angle=angle,
    )


def test_critere1_angle_rempli_le_tamis_n_est_pas_appele(
    repertoire_path, cv_path, tournures_path, modeles
):
    modeles.programmer("redaction", "Lettre depuis mon angle.")
    modeles.programmer("juge", _JUGE_RIEN_A_REDIRE)

    resultat = _lancer(repertoire_path, cv_path, tournures_path, angle=ANGLE)

    assert not any(noeud == "tamis" for noeud, _, _ in modeles.appels)
    assert modeles.files["tamis"] == []
    assert resultat.fait_retenu == GENERIQUE_ID
    assert resultat.raison_fin == RAISON_RIEN_A_REDIRE


def test_critere2_redaction_recoit_l_angle_mot_pour_mot_sans_fait_ni_texte_type(
    repertoire_path, cv_path, tournures_path, modeles
):
    modeles.programmer("redaction", "Lettre depuis mon angle.")
    modeles.programmer("juge", _JUGE_RIEN_A_REDIRE)

    _lancer(repertoire_path, cv_path, tournures_path, angle=ANGLE)

    demande_redaction = next(p for n, _, p in modeles.appels if n == "redaction")
    assert ANGLE in demande_redaction
    assert "L'angle d'accroche que j'ai choisi" in demande_redaction
    assert "Fait retenu de l'entreprise" not in demande_redaction
    assert "Aucun fait d'entreprise retenu" not in demande_redaction
    assert "Texte type" not in demande_redaction
    assert "conviction de prototyper" not in demande_redaction
    assert "conviction de generique" not in demande_redaction


def test_critere3_verificateur_recoit_l_angle_comme_source(
    repertoire_path, cv_path, tournures_path, modeles
):
    modeles.programmer("redaction", "Lettre depuis mon angle.")
    modeles.programmer(
        "verificateur",
        json.dumps({"rien_a_signaler": True, "lieux": [], "affirmations": []}),
    )
    modeles.programmer("juge", _JUGE_RIEN_A_REDIRE)

    _lancer(repertoire_path, cv_path, tournures_path, angle=ANGLE)

    demande_verif = next(p for n, _, p in modeles.appels if n == "verificateur")
    assert ANGLE in demande_verif
    assert "Fait retenu de l'entreprise" not in demande_verif
    assert "Aucun fait d'entreprise retenu" not in demande_verif


def test_critere4_juge_ne_recoit_pas_l_angle(
    repertoire_path, cv_path, tournures_path, modeles
):
    modeles.programmer("redaction", "Lettre depuis mon angle.")
    modeles.programmer("juge", _JUGE_RIEN_A_REDIRE)

    _lancer(repertoire_path, cv_path, tournures_path, angle=ANGLE)

    demande_juge = next(p for n, _, p in modeles.appels if n == "juge")
    assert ANGLE not in demande_juge


def test_critere6_angle_vide_le_tamis_choisit_comme_avant(
    repertoire_path, cv_path, tournures_path, modeles
):
    modeles.programmer(
        "tamis", json.dumps({"point_index": 0, "texte_type_id": "prototyper"})
    )
    modeles.programmer("redaction", "Lettre du tamis.")
    modeles.programmer("juge", _JUGE_RIEN_A_REDIRE)

    resultat = _lancer(repertoire_path, cv_path, tournures_path, angle=None)

    assert [n for n, _, _ in modeles.appels][0] == "tamis"
    assert resultat.fait_retenu["citation"] == "Citation 0"


def test_critere7_angle_seulement_des_espaces_vaut_vide(
    repertoire_path, cv_path, tournures_path, modeles
):
    modeles.programmer(
        "tamis", json.dumps({"point_index": 0, "texte_type_id": "prototyper"})
    )
    modeles.programmer("redaction", "Lettre du tamis.")
    modeles.programmer("juge", _JUGE_RIEN_A_REDIRE)

    resultat = _lancer(repertoire_path, cv_path, tournures_path, angle="   \n  ")

    assert [n for n, _, _ in modeles.appels][0] == "tamis"
    assert resultat.fait_retenu["citation"] == "Citation 0"


# ═══════════════════════════════════════════════════════════════════════════
# Palier 2 — service et API (critères 5, 8, 9, 10, 11, 12)
# ═══════════════════════════════════════════════════════════════════════════

FAIT_0 = {
    "position": "Point 0",
    "citation": "Citation 0",
    "url": "http://a",
    "tas": None,
}
POINTS = [FAIT_0]


def _resultat_ok(
    texte="Voici ma lettre.", fait_retenu=None, jugement=None
) -> ResultatBoucle:
    return ResultatBoucle(
        fait_retenu=fait_retenu if fait_retenu is not None else GENERIQUE_ID,
        texte_type_id="tt1",
        lettres=[
            {
                "texte": texte,
                "nb_mots": len(texte.split()),
                "tournures_signalees": [],
                "jugement": jugement,
                "releve_redaction": None,
                "releve_correction": None,
            }
        ],
        nb_tours=1,
        raison_fin=RAISON_RIEN_A_REDIRE,
        appels=[],
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


def _insert_offer(db_path, offer_id, verdict="retenu"):
    conn = sqlite3.connect(db_path)
    try:
        conn.execute(
            "INSERT INTO offers (id, source, source_id, fingerprint, title, company, "
            "description_raw) VALUES (?, 'test', ?, 'fp', 'Titre', 'ACME', 'Texte de l''offre.')",
            (offer_id, str(offer_id)),
        )
        if verdict is not None:
            conn.execute(
                "INSERT INTO verdicts (offer_id, status, created_at) VALUES (?, ?, '2026-10-12')",
                (offer_id, verdict),
            )
        conn.commit()
    finally:
        conn.close()


def _insert_fiche(db_path, offer_id, points=POINTS, statut="done"):
    conn = sqlite3.connect(db_path)
    try:
        conn.execute(
            "INSERT INTO fiches_entreprise (offer_id, statut, presentation, points_json, "
            "employeur_nom, created_at) VALUES (?, ?, 'Présentation', ?, 'ACME', '2026-10-12')",
            (offer_id, statut, json.dumps(points, ensure_ascii=False)),
        )
        conn.commit()
    finally:
        conn.close()


def _lettre_row(db_path, offer_id):
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        return conn.execute(
            "SELECT * FROM lettres WHERE offer_id = ?", (offer_id,)
        ).fetchone()
    finally:
        conn.close()


async def _drain() -> None:
    while True:
        pending = [t for t in asyncio.all_tasks() if t is not asyncio.current_task()]
        if not pending:
            return
        await asyncio.gather(*pending, return_exceptions=True)


class TestCritere5AngleReste:
    def test_angle_enregistre_relu_par_get_lettre(self, db_path):
        offer_id = 50
        _insert_offer(db_path, offer_id)
        _insert_fiche(db_path, offer_id)

        api_lettre.put_lettre_angle(offer_id, api_lettre.LettreAngleIn(angle=ANGLE))
        lettre = api_lettre.get_lettre(offer_id)

        assert lettre["angle"] == ANGLE


class TestCritere7AngleVideEstNormalise:
    def test_angle_seulement_espaces_enregistre_vide(self, db_path):
        offer_id = 70
        _insert_offer(db_path, offer_id)
        _insert_fiche(db_path, offer_id)

        resultat = api_lettre.put_lettre_angle(
            offer_id, api_lettre.LettreAngleIn(angle="   ")
        )

        assert resultat["angle"] is None


class TestCritere8ToutesLesGenerationsPartentDeLAngle:
    def test_premiere_generation_part_de_l_angle(self, db_path, monkeypatch):
        offer_id = 80
        _insert_offer(db_path, offer_id)
        _insert_fiche(db_path, offer_id)
        lettre_service.save_angle(sqlite3.connect(db_path), offer_id, ANGLE)
        captured = {}

        def _double(titre, texte_offre, entreprise, points_fiche, config, **kw):
            captured["angle"] = kw.get("angle")
            return _resultat_ok()

        monkeypatch.setattr(lettre_service, "generer_lettre_depuis_donnees", _double)
        asyncio.run(lettre_service.run_lettre(offer_id))

        assert captured["angle"] == ANGLE

    def test_regeneration_avec_un_autre_modele_part_de_l_angle(
        self, db_path, monkeypatch
    ):
        offer_id = 81
        _insert_offer(db_path, offer_id)
        _insert_fiche(db_path, offer_id)
        conn = sqlite3.connect(db_path)
        lettre_service.save_angle(conn, offer_id, ANGLE)
        monkeypatch.setattr(
            lettre_service,
            "generer_lettre_depuis_donnees",
            lambda *a, **k: _resultat_ok(),
        )
        asyncio.run(lettre_service.run_lettre(offer_id, "sonnet"))

        captured = {}

        def _double(titre, texte_offre, entreprise, points_fiche, config, **kw):
            captured["angle"] = kw.get("angle")
            return _resultat_ok("Régénérée.")

        monkeypatch.setattr(lettre_service, "generer_lettre_depuis_donnees", _double)
        asyncio.run(lettre_service.run_lettre_regenerate(offer_id, "opus"))

        assert captured["angle"] == ANGLE


class TestCritere9AngleTropLongRefuse:
    def test_angle_trop_long_est_refuse_avant_tout_enregistrement(self, db_path):
        offer_id = 90
        _insert_offer(db_path, offer_id)
        _insert_fiche(db_path, offer_id)
        angle_trop_long = "a" * (lettre_service.MAX_ANGLE_CHARS + 1)

        with pytest.raises(lettre_service.AngleTropLongError) as exc_info:
            lettre_service.save_angle(
                sqlite3.connect(db_path), offer_id, angle_trop_long
            )
        assert str(lettre_service.MAX_ANGLE_CHARS) in str(exc_info.value)

        row = _lettre_row(db_path, offer_id)
        assert row is None

    def test_route_put_angle_refuse_avec_422(self, db_path):
        offer_id = 91
        _insert_offer(db_path, offer_id)
        _insert_fiche(db_path, offer_id)
        angle_trop_long = "a" * (lettre_service.MAX_ANGLE_CHARS + 1)

        with pytest.raises(HTTPException) as exc_info:
            api_lettre.put_lettre_angle(
                offer_id, api_lettre.LettreAngleIn(angle=angle_trop_long)
            )
        assert exc_info.value.status_code == 422
        assert str(lettre_service.MAX_ANGLE_CHARS) in exc_info.value.detail


class TestCritere10VersionDepuisAngleNaPasDeFaitRetenu:
    def test_version_generee_depuis_l_angle_porte_l_angle_et_aucun_fait(
        self, db_path, monkeypatch
    ):
        offer_id = 100
        _insert_offer(db_path, offer_id)
        _insert_fiche(db_path, offer_id)
        conn = sqlite3.connect(db_path)
        lettre_service.save_angle(conn, offer_id, ANGLE)

        monkeypatch.setattr(
            lettre_service,
            "generer_lettre_depuis_donnees",
            lambda *a, **k: _resultat_ok(),
        )
        asyncio.run(lettre_service.run_lettre(offer_id))

        row = _lettre_row(db_path, offer_id)
        assert row["fait_retenu_json"] is None
        versions = api_lettre.get_lettre_versions(offer_id)
        assert versions[-1]["angle_utilise"] == ANGLE
        assert versions[-1]["fait_retenu"] is None


class TestCritere11EcarterRefuseSurLettreDepuisAngle:
    def test_ecarter_est_refuse_sur_une_lettre_depuis_mon_angle(
        self, db_path, monkeypatch
    ):
        offer_id = 110
        _insert_offer(db_path, offer_id)
        _insert_fiche(db_path, offer_id)
        conn = sqlite3.connect(db_path)
        lettre_service.save_angle(conn, offer_id, ANGLE)
        monkeypatch.setattr(
            lettre_service,
            "generer_lettre_depuis_donnees",
            lambda *a, **k: _resultat_ok(),
        )
        asyncio.run(lettre_service.run_lettre(offer_id))

        with pytest.raises(HTTPException) as exc_info:
            asyncio.run(api_lettre.ecarter_fait(offer_id, Response()))
        assert exc_info.value.status_code == 409


class TestCritere12ModeleJugeEtJugementMarchentAvecUnAngle:
    def test_juge_opus_et_jugement_gardes_avec_un_angle(self, db_path, monkeypatch):
        offer_id = 120
        _insert_offer(db_path, offer_id)
        _insert_fiche(db_path, offer_id)
        conn = sqlite3.connect(db_path)
        lettre_service.save_angle(conn, offer_id, ANGLE)
        jugement = Jugement(
            rien_a_redire=True,
            ressenti="Ressenti.",
            details="Détails.",
            reussites="Réussites.",
            verdict="Verdict.",
        )
        captured = {}

        def _double(titre, texte_offre, entreprise, points_fiche, config, **kw):
            captured["config"] = config
            return _resultat_ok(jugement=jugement)

        monkeypatch.setattr(lettre_service, "generer_lettre_depuis_donnees", _double)
        asyncio.run(lettre_service.run_lettre(offer_id, "opus"))

        assert captured["config"].modele_juge == "opus"
        row = _lettre_row(db_path, offer_id)
        assert json.loads(row["jugement_json"]) == {
            "rien_a_redire": True,
            "ressenti": "Ressenti.",
            "details": "Détails.",
            "reussites": "Réussites.",
            "verdict": "Verdict.",
            "decision": "j'appelle",  # EXE-175, critère 1
        }
