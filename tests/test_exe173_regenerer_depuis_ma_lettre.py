"""Tests EXE-173 — je réécris la lettre moi-même, et la régénération repart de
ma lettre : le juge la lit d'abord, la rédaction la reprend depuis son ressenti.

Deux paliers, comme test_exe171_angle_lettre.py. D'abord la boucle
(`generer_lettre_depuis_donnees`), appelée directement — `boucle.appeler_modele`
remplacé par une doublure programmable, comme dans test_exe147_boucle_lettre.py
(critères 3-7). Ensuite le service et l'API, avec `generer_lettre_depuis_donnees`
elle-même remplacée par une doublure qui rend un `ResultatBoucle` explicite — la
base est un fichier tmp_path (critère 18). Aucun test n'appelle un modèle réel,
aucun test ne lit ni n'écrit sous data/.
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
    RAISON_PLAFOND,
    RAISON_RIEN_A_REDIRE,
    ConfigBoucle,
    Jugement,
    ReponseModele,
    ResultatBoucle,
    generer_lettre_depuis_donnees,
)
from orchestrator.job_search.storage.db import init_db

# ═══════════════════════════════════════════════════════════════════════════
# Palier 1 — la boucle (critères 3, 4, 5, 6, 7)
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


def _repertoire_donnees() -> dict:
    return {
        "version": 1,
        "posture": {
            "role": "ingénieur qui prototype vite",
            "quatre_temps": ["accroche", "preuve", "offre", "cta"],
            "regles": ["jamais de superlatif"],
            "formulations_rejetees": [],
        },
        "ce_qui_fait_une_bonne_accroche": ["un fait précis de l'entreprise"],
        "sujets_interdits": [],
        "conditions_generales": ["lettre en français"],
        "forme": {
            "blocs": ["accroche", "preuve", "offre", "cta"],
            "longueur_cible_mots": 160,
            "lettre_de_reference": None,
        },
        "textes_types": [
            {
                "id": "generique",
                "sujet": "sujet générique",
                "conviction": "conviction générique",
                "ce_que_j_ai_fait": "ce que j'ai fait",
                "texte": "texte générique rédigé",
                "exemples": [],
            },
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
    chemin = tmp_path / "repertoire.yaml"
    chemin.write_text(
        yaml.safe_dump(_repertoire_donnees(), allow_unicode=True), encoding="utf-8"
    )
    return chemin


@pytest.fixture
def cv_path(tmp_path):
    chemin = tmp_path / "cv_reference.html"
    chemin.write_text(
        "<html><body><p>Contenu CV de test</p></body></html>", encoding="utf-8"
    )
    return chemin


@pytest.fixture
def tournures_path(tmp_path):
    chemin = tmp_path / "tournures_interdites.txt"
    chemin.write_text("je veux\nn'hésitez pas\n", encoding="utf-8")
    return chemin


MA_LETTRE = "Ma lettre écrite à la main, mot pour mot."

_JUGE_A_REDIRE = json.dumps(
    {
        "rien_a_redire": False,
        "ressenti": "Ça sonne creux.",
        "details": "Détail du juge.",
        "reussites": "Réussite du juge.",
        "verdict": "Verdict du juge.",
        "decision": "j'appelle",  # EXE-175, critère 1
    }
)
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


def _lancer(repertoire_path, cv_path, tournures_path, angle=None, config=None):
    return generer_lettre_depuis_donnees(
        "Titre de l'offre",
        "Texte de l'offre",
        "Entreprise X",
        [],
        config or _config(),
        repertoire_path=repertoire_path,
        cv_reference_path=cv_path,
        tournures_path=tournures_path,
        angle=angle,
        ma_lettre=MA_LETTRE,
    )


def test_critere3_le_juge_est_le_premier_appel_jamais_le_tamis(
    repertoire_path, cv_path, tournures_path, modeles
):
    modeles.programmer("juge", _JUGE_RIEN_A_REDIRE)

    _lancer(repertoire_path, cv_path, tournures_path)

    assert [n for n, _, _ in modeles.appels][0] == "juge"
    assert not any(n == "tamis" for n, _, _ in modeles.appels)
    assert modeles.files["tamis"] == []


def test_critere3_le_juge_juge_ma_lettre_mot_pour_mot(
    repertoire_path, cv_path, tournures_path, modeles
):
    modeles.programmer("juge", _JUGE_RIEN_A_REDIRE)

    _lancer(repertoire_path, cv_path, tournures_path)

    demande_juge = next(p for n, _, p in modeles.appels if n == "juge")
    assert MA_LETTRE in demande_juge


def test_critere4_rien_a_redire_aucune_lettre_n_est_reecrite(
    repertoire_path, cv_path, tournures_path, modeles
):
    modeles.programmer("juge", _JUGE_RIEN_A_REDIRE)

    resultat = _lancer(repertoire_path, cv_path, tournures_path)

    assert resultat.nb_tours == 0
    assert resultat.raison_fin == RAISON_RIEN_A_REDIRE
    assert len(resultat.lettres) == 1
    assert resultat.lettres[0]["texte"] == MA_LETTRE
    assert not any(n == "redaction" for n, _, _ in modeles.appels)
    assert resultat.jugement_ma_lettre.rien_a_redire is True


def test_critere5_redaction_recoit_ma_lettre_jugement_et_consigne_sans_fait_ni_texte_type(
    repertoire_path, cv_path, tournures_path, modeles
):
    modeles.programmer("juge", _JUGE_A_REDIRE, _JUGE_RIEN_A_REDIRE)
    modeles.programmer("redaction", "Lettre réécrite par le modèle.")

    resultat = _lancer(repertoire_path, cv_path, tournures_path)

    demande_redaction = next(p for n, _, p in modeles.appels if n == "redaction")
    assert MA_LETTRE in demande_redaction
    assert "Ça sonne creux." in demande_redaction
    assert "Détail du juge." in demande_redaction
    assert "Réussite du juge." in demande_redaction
    assert "Verdict du juge." in demande_redaction
    assert "Consigne de reprise." in demande_redaction
    assert "Fait retenu de l'entreprise" not in demande_redaction
    assert "Aucun fait d'entreprise retenu" not in demande_redaction
    assert "Texte type" not in demande_redaction
    # Ma lettre reste intacte dans le résultat, distincte de la réécriture.
    assert resultat.lettres[0]["texte"] == MA_LETTRE
    assert resultat.lettres[-1]["texte"] == "Lettre réécrite par le modèle."
    assert resultat.nb_tours == 1


def test_critere6_angle_rempli_la_redaction_le_recoit_aussi(
    repertoire_path, cv_path, tournures_path, modeles
):
    angle = "Mon angle d'accroche écrit à la main."
    modeles.programmer("juge", _JUGE_A_REDIRE, _JUGE_RIEN_A_REDIRE)
    modeles.programmer("redaction", "Lettre réécrite depuis mon angle.")

    _lancer(repertoire_path, cv_path, tournures_path, angle=angle)

    demande_redaction = next(p for n, _, p in modeles.appels if n == "redaction")
    assert angle in demande_redaction
    assert "L'angle d'accroche que j'ai choisi" in demande_redaction


def test_critere7_la_boucle_s_arrete_au_plus_tard_apres_3_lettres_reecrites(
    repertoire_path, cv_path, tournures_path, modeles
):
    # Jugé une première fois sur ma lettre, puis une fois après chacune des
    # trois réécritures — jamais rien à redire, pour atteindre le plafond.
    modeles.programmer(
        "juge", _JUGE_A_REDIRE, _JUGE_A_REDIRE, _JUGE_A_REDIRE, _JUGE_A_REDIRE
    )
    modeles.programmer("redaction", "Réécriture 1.", "Réécriture 2.", "Réécriture 3.")

    resultat = _lancer(repertoire_path, cv_path, tournures_path)

    assert resultat.nb_tours == 3
    assert resultat.raison_fin == RAISON_PLAFOND
    assert resultat.lettres[-1]["texte"] == "Réécriture 3."


# ═══════════════════════════════════════════════════════════════════════════
# Palier 2 — service et API (critères 1, 2, 8, 9, 10, 11, 12, 13)
# ═══════════════════════════════════════════════════════════════════════════

FAIT_0 = {
    "position": "Point 0",
    "citation": "Citation 0",
    "url": "http://a",
    "tas": None,
}
POINTS = [FAIT_0]

JUGEMENT_MA_LETTRE = Jugement(
    rien_a_redire=False,
    ressenti="Ça sonne creux.",
    details="Détail du juge.",
    reussites="Réussite du juge.",
    verdict="Verdict du juge.",
)

JUGEMENT_RIEN_A_REDIRE = Jugement(
    rien_a_redire=True,
    ressenti="Rien à redire.",
    details="Rien à redire.",
    reussites="Rien à redire.",
    verdict="Rien à redire.",
)

JUGEMENT_FINAL = Jugement(
    rien_a_redire=True,
    ressenti="Ça sonne vrai, maintenant.",
    details="Détail final.",
    reussites="Réussite finale.",
    verdict="À envoyer.",
)


def _resultat_sans_reecriture(ma_lettre_texte: str) -> ResultatBoucle:
    """Simule le juge n'ayant rien à redire sur ma lettre (critère 4) : une
    seule entrée dans `lettres`, `nb_tours=0`."""
    return ResultatBoucle(
        fait_retenu=GENERIQUE_ID,
        texte_type_id=GENERIQUE_ID,
        lettres=[
            {
                "texte": ma_lettre_texte,
                "nb_mots": len(ma_lettre_texte.split()),
                "tournures_signalees": [],
                "jugement": JUGEMENT_RIEN_A_REDIRE,
                "releve_redaction": None,
                "releve_correction": None,
                "tour": 0,  # EXE-175 : ma lettre, jamais réécrite
            }
        ],
        nb_tours=0,
        raison_fin=RAISON_RIEN_A_REDIRE,
        appels=[],
        jugement_ma_lettre=JUGEMENT_RIEN_A_REDIRE,
    )


def _resultat_avec_reecriture(
    ma_lettre_texte: str, texte_final="Lettre réécrite par le modèle.", nb_tours=1
) -> ResultatBoucle:
    """Simule une reprise qui réécrit la lettre (critères 5-10)."""
    return ResultatBoucle(
        fait_retenu=GENERIQUE_ID,
        texte_type_id=GENERIQUE_ID,
        lettres=[
            {
                "texte": ma_lettre_texte,
                "nb_mots": len(ma_lettre_texte.split()),
                "tournures_signalees": [],
                "jugement": JUGEMENT_MA_LETTRE,
                "releve_redaction": None,
                "releve_correction": None,
                "tour": 0,  # EXE-175 : ma lettre, jamais réécrite
            },
            {
                "texte": texte_final,
                "nb_mots": len(texte_final.split()),
                "tournures_signalees": [],
                "jugement": JUGEMENT_FINAL,
                "releve_redaction": None,
                "releve_correction": None,
                "tour": nb_tours,  # EXE-175 : la réécriture retenue, ce tour-ci
            },
        ],
        nb_tours=nb_tours,
        raison_fin=RAISON_RIEN_A_REDIRE,
        appels=[],
        jugement_ma_lettre=JUGEMENT_MA_LETTRE,
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
                "INSERT INTO verdicts (offer_id, status, created_at) VALUES (?, ?, '2026-10-14')",
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
            "employeur_nom, created_at) VALUES (?, ?, 'Présentation', ?, 'ACME', '2026-10-14')",
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


def _poser_lettre_puis_reprise_a_la_main(db_path, offer_id, texte_moi: str):
    """Fait passer une offre par une génération modèle (statut done), puis par
    une reprise à la main (`save_texte`) — état réaliste d'une lettre dont la
    dernière version est « moi », sans jamais appeler un modèle réel."""
    _insert_offer(db_path, offer_id)
    _insert_fiche(db_path, offer_id)
    import unittest.mock as mock

    with mock.patch.object(
        lettre_service,
        "generer_lettre_depuis_donnees",
        lambda *a, **k: _ResultatInitial(),
    ):
        asyncio.run(lettre_service.run_lettre(offer_id, "sonnet"))
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        lettre_service.save_texte(conn, offer_id, texte_moi)
    finally:
        conn.close()


def _ResultatInitial() -> ResultatBoucle:
    return ResultatBoucle(
        fait_retenu=GENERIQUE_ID,
        texte_type_id=GENERIQUE_ID,
        lettres=[
            {
                "texte": "Lettre générée par le modèle, au départ.",
                "nb_mots": 7,
                "tournures_signalees": [],
                "jugement": JUGEMENT_RIEN_A_REDIRE,
                "releve_redaction": None,
                "releve_correction": None,
            }
        ],
        nb_tours=1,
        raison_fin=RAISON_RIEN_A_REDIRE,
        appels=[],
    )


class TestCritere1Et2RefusAvantToutAppelDeModeleSiPasMaMain:
    def test_valider_repart_de_ma_lettre_accepte_la_derniere_version_moi(self, db_path):
        offer_id = 1
        _poser_lettre_puis_reprise_a_la_main(db_path, offer_id, MA_LETTRE)

        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        try:
            texte = lettre_service.valider_repart_de_ma_lettre(conn, offer_id)
        finally:
            conn.close()
        assert texte == MA_LETTRE

    def test_route_refuse_quand_la_derniere_version_n_est_pas_moi(
        self, db_path, monkeypatch
    ):
        offer_id = 2
        _insert_offer(db_path, offer_id)
        _insert_fiche(db_path, offer_id)
        monkeypatch.setattr(
            lettre_service,
            "generer_lettre_depuis_donnees",
            lambda *a, **k: (_ for _ in ()).throw(
                AssertionError("aucun appel de modèle ne doit partir")
            ),
        )
        asyncio.run(lettre_service.run_lettre(offer_id, "sonnet"))
        # Aucune reprise à la main : la dernière version est 'modele'.

        async def _scenario():
            with pytest.raises(HTTPException) as exc_info:
                await api_lettre.regenerer_depuis_ma_lettre(offer_id, Response())
            assert exc_info.value.status_code == 409
            await _drain()

        asyncio.run(_scenario())

    def test_route_refuse_quand_aucune_lettre_n_existe(self, db_path):
        offer_id = 20
        _insert_offer(db_path, offer_id)

        async def _scenario():
            with pytest.raises(HTTPException) as exc_info:
                await api_lettre.regenerer_depuis_ma_lettre(offer_id, Response())
            assert exc_info.value.status_code == 409

        asyncio.run(_scenario())


class TestCritere4RienARedireAucuneNouvelleVersion:
    def test_rien_a_redire_ma_lettre_reste_courante_sans_nouvelle_version(
        self, db_path, monkeypatch
    ):
        offer_id = 4
        _poser_lettre_puis_reprise_a_la_main(db_path, offer_id, MA_LETTRE)
        versions_avant = api_lettre.get_lettre_versions(offer_id)

        monkeypatch.setattr(
            lettre_service,
            "generer_lettre_depuis_donnees",
            lambda *a, **k: _resultat_sans_reecriture(MA_LETTRE),
        )
        asyncio.run(
            lettre_service.run_lettre_regenerate_depuis_ma_lettre(offer_id, MA_LETTRE)
        )

        versions_apres = api_lettre.get_lettre_versions(offer_id)
        assert len(versions_apres) == len(versions_avant)
        row = _lettre_row(db_path, offer_id)
        assert row["texte"] == MA_LETTRE
        assert row["nb_tours"] == 0


class TestCritere9JugementSurMaLettreEnregistreSurMaVersion:
    def test_jugement_pose_sur_ma_version_meme_sans_reecriture(
        self, db_path, monkeypatch
    ):
        offer_id = 9
        _poser_lettre_puis_reprise_a_la_main(db_path, offer_id, MA_LETTRE)

        monkeypatch.setattr(
            lettre_service,
            "generer_lettre_depuis_donnees",
            lambda *a, **k: _resultat_sans_reecriture(MA_LETTRE),
        )
        asyncio.run(
            lettre_service.run_lettre_regenerate_depuis_ma_lettre(offer_id, MA_LETTRE)
        )

        versions = api_lettre.get_lettre_versions(offer_id)
        ma_version = next(v for v in versions if v["origine"] == "moi")
        assert ma_version["jugement"] == {
            "rien_a_redire": True,
            "ressenti": "Rien à redire.",
            "details": "Rien à redire.",
            "reussites": "Rien à redire.",
            "verdict": "Rien à redire.",
            "decision": "j'appelle",  # EXE-175, critère 1
        }
        assert ma_version["modele_juge"] == lettre_service.MODELE_JUGE

    def test_jugement_pose_sur_ma_version_quand_une_reecriture_a_eu_lieu(
        self, db_path, monkeypatch
    ):
        offer_id = 90
        _poser_lettre_puis_reprise_a_la_main(db_path, offer_id, MA_LETTRE)

        monkeypatch.setattr(
            lettre_service,
            "generer_lettre_depuis_donnees",
            lambda *a, **k: _resultat_avec_reecriture(MA_LETTRE),
        )
        asyncio.run(
            lettre_service.run_lettre_regenerate_depuis_ma_lettre(offer_id, MA_LETTRE)
        )

        versions = api_lettre.get_lettre_versions(offer_id)
        ma_version = next(v for v in versions if v["origine"] == "moi")
        assert ma_version["jugement"]["ressenti"] == "Ça sonne creux."
        assert ma_version["texte"] == MA_LETTRE  # jamais réécrite ni effacée


class TestCritere10VersionFinaleNouvelleEtMarqueeRepartieDeMaLettre:
    def test_version_finale_est_nouvelle_porte_son_jugement_et_la_marque(
        self, db_path, monkeypatch
    ):
        offer_id = 10
        _poser_lettre_puis_reprise_a_la_main(db_path, offer_id, MA_LETTRE)
        nb_versions_avant = len(api_lettre.get_lettre_versions(offer_id))

        monkeypatch.setattr(
            lettre_service,
            "generer_lettre_depuis_donnees",
            lambda *a, **k: _resultat_avec_reecriture(MA_LETTRE, nb_tours=2),
        )
        asyncio.run(
            lettre_service.run_lettre_regenerate_depuis_ma_lettre(
                offer_id, MA_LETTRE, "sonnet"
            )
        )

        versions = api_lettre.get_lettre_versions(offer_id)
        assert len(versions) == nb_versions_avant + 1
        derniere = versions[-1]
        assert derniere["origine"] == "modele"
        assert derniere["texte"] == "Lettre réécrite par le modèle."
        assert derniere["jugement"]["ressenti"] == "Ça sonne vrai, maintenant."
        assert derniere["nb_tours"] == 2
        assert derniere["modele"] == "sonnet"
        assert derniere["modele_juge"] == lettre_service.MODELE_JUGE
        assert derniere["repartie_de_ma_lettre"] is True

        # Ma version reste intacte dans l'historique.
        ma_version = next(v for v in versions if v["origine"] == "moi")
        assert ma_version["texte"] == MA_LETTRE
        assert ma_version["repartie_de_ma_lettre"] is False


class TestCritere11VersionsAncienesSeLisentSansErreur:
    def test_version_sans_colonne_repartie_de_ma_lettre_se_lit_sans_erreur(
        self, db_path
    ):
        offer_id = 110
        _insert_offer(db_path, offer_id)
        conn = sqlite3.connect(db_path)
        conn.execute(
            "INSERT INTO lettre_versions (offer_id, texte, origine, created_at) "
            "VALUES (?, 'Ancienne version.', 'modele', '2026-09-01')",
            (offer_id,),
        )
        conn.commit()
        conn.close()

        versions = api_lettre.get_lettre_versions(offer_id)
        assert versions[0]["repartie_de_ma_lettre"] is False


class TestCritere12RegenerationOrdinairePartDuTamisMemeSiMaLettreEstCourante:
    def test_regeneration_ordinaire_n_envoie_pas_ma_lettre(self, db_path, monkeypatch):
        offer_id = 12
        _poser_lettre_puis_reprise_a_la_main(db_path, offer_id, MA_LETTRE)
        captured = {}

        def _double(titre, texte_offre, entreprise, points_fiche, config, **kw):
            captured["ma_lettre"] = kw.get("ma_lettre")
            return _ResultatInitial()

        monkeypatch.setattr(lettre_service, "generer_lettre_depuis_donnees", _double)
        asyncio.run(lettre_service.run_lettre_regenerate(offer_id, "sonnet"))

        assert captured["ma_lettre"] is None


class TestCritere13GenerationSansCeModeEnvoieLesMemesDemandesQuAvant:
    def test_run_lettre_n_envoie_pas_ma_lettre(self, db_path, monkeypatch):
        offer_id = 13
        _insert_offer(db_path, offer_id)
        _insert_fiche(db_path, offer_id)
        captured = {}

        def _double(titre, texte_offre, entreprise, points_fiche, config, **kw):
            captured["ma_lettre"] = kw.get("ma_lettre")
            return _ResultatInitial()

        monkeypatch.setattr(lettre_service, "generer_lettre_depuis_donnees", _double)
        asyncio.run(lettre_service.run_lettre(offer_id, "sonnet"))

        assert captured["ma_lettre"] is None


class TestCritere8ModeleJugeRestePartAChaqueFoisQueLaRedactionTourne:
    def test_rédaction_sur_le_modele_choisi_juge_toujours_opus(
        self, db_path, monkeypatch
    ):
        offer_id = 8
        _poser_lettre_puis_reprise_a_la_main(db_path, offer_id, MA_LETTRE)
        captured = {}

        def _double(titre, texte_offre, entreprise, points_fiche, config, **kw):
            captured["config"] = config
            return _resultat_avec_reecriture(MA_LETTRE)

        monkeypatch.setattr(lettre_service, "generer_lettre_depuis_donnees", _double)
        asyncio.run(
            lettre_service.run_lettre_regenerate_depuis_ma_lettre(
                offer_id, MA_LETTRE, "opus"
            )
        )

        assert captured["config"].modele_redaction == "opus"
        assert captured["config"].modele_juge == lettre_service.MODELE_JUGE
        row = _lettre_row(db_path, offer_id)
        assert row["modele"] == "opus"
        assert row["modele_juge"] == lettre_service.MODELE_JUGE
