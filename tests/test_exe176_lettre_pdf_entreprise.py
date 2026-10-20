"""Tests EXE-176 — le PDF de la lettre porte l'entreprise en haut à droite
(critères 12 à 16).

Mêmes conventions que test_exe129_lettre_mise_en_page.py : DB et coordonnées
sous tmp_path, aucun appel modèle, aucune lecture/écriture sous data/.
"""

import sqlite3
from datetime import date, datetime, timezone

import pytest
from fastapi import HTTPException

import api.db as api_db
import api.lettre as api_lettre
import orchestrator.job_search.fiche.intermediaires as intermediaires_module
import orchestrator.job_search.pdf.coordonnees as coordonnees_module
import orchestrator.job_search.storage.db as storage_db
from orchestrator.job_search.pdf.coordonnees import Coordonnees
from orchestrator.job_search.pdf.lettre_html import (
    build_lettre_html,
    ville_sans_departement,
)
from orchestrator.job_search.storage.db import init_db
from orchestrator.job_search.suivi import etats as suivi_etats
from orchestrator.job_search.suivi import storage as suivi_storage

COORDONNEES = Coordonnees(
    nom="Grégoire Marchand",
    mail="gregoire@example.com",
    telephone="+33 6 00 00 00 00",
    ville="Strasbourg",
)

LETTRE_TEXTE = "Je vous écris pour vous faire part de mon vif intérêt pour ce poste."


@pytest.fixture
def db_path(tmp_path, monkeypatch):
    path = tmp_path / "job_search.sqlite"
    monkeypatch.setattr(storage_db, "DB_PATH", path)
    monkeypatch.setattr(api_db, "DB_PATH", path)
    conn = sqlite3.connect(path)
    init_db(conn)
    conn.close()
    return path


@pytest.fixture
def coordonnees_path(tmp_path, monkeypatch):
    path = tmp_path / "coordonnees.txt"
    path.write_text(
        "nom: Grégoire Marchand\n"
        "mail: gregoire@example.com\n"
        "telephone: +33 6 00 00 00 00\n"
        "ville: Strasbourg\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(coordonnees_module, "COORDONNEES_PATH", path)
    return path


@pytest.fixture
def intermediaires_path(tmp_path, monkeypatch):
    path = tmp_path / "intermediaires.yaml"
    path.write_text("intermediaires:\n  - EDITX BV\n", encoding="utf-8")
    monkeypatch.setattr(intermediaires_module, "INTERMEDIAIRES_PATH", path)
    return path


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _insert_offer(
    db_path, offer_id, verdict="retenu", title="Titre", company=None, location=None
):
    conn = sqlite3.connect(db_path)
    try:
        conn.execute(
            "INSERT INTO offers (id, source, source_id, fingerprint, title, "
            "company, location, description_raw) VALUES (?, 'test', ?, 'fp', ?, ?, ?, "
            "'Texte de l offre')",
            (offer_id, str(offer_id), title, company, location),
        )
        if verdict == "retenu":
            suivi_storage.appliquer_geste(
                conn, offer_id, suivi_etats.RETENIR, effet_at=_now()
            )
        elif verdict is not None:
            suivi_storage.appliquer_geste(
                conn, offer_id, suivi_etats.ECARTER, effet_at=_now()
            )
        conn.commit()
    finally:
        conn.close()


def _insert_fiche(db_path, offer_id, employeur_nom=None, statut="done"):
    conn = sqlite3.connect(db_path)
    try:
        conn.execute(
            "INSERT INTO fiches_entreprise (offer_id, statut, employeur_nom, created_at) "
            "VALUES (?, ?, ?, ?)",
            (offer_id, statut, employeur_nom, _now()),
        )
        conn.commit()
    finally:
        conn.close()


def _insert_lettre_done(db_path, offer_id, texte):
    conn = sqlite3.connect(db_path)
    try:
        conn.execute(
            "INSERT INTO lettres (offer_id, statut, texte, created_at) "
            "VALUES (?, 'done', ?, ?)",
            (offer_id, texte, _now()),
        )
        conn.commit()
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Critère 14 — ville sans préfixe département
# ---------------------------------------------------------------------------


class TestCritere14VilleSansDepartement:
    @pytest.mark.parametrize(
        ("location", "attendu"),
        [
            ("67 - Obernai", "Obernai"),
            ("75 - Paris (Dept.)", "Paris"),
            ("Bruxelles", "Bruxelles"),
        ],
    )
    def test_formats(self, location, attendu):
        assert ville_sans_departement(location) == attendu

    def test_absente_sans_location(self):
        assert ville_sans_departement(None) is None
        assert ville_sans_departement("") is None


# ---------------------------------------------------------------------------
# Critères 12-13 — mes coordonnées à gauche, l'entreprise à droite
# ---------------------------------------------------------------------------


class TestCritere12Et13EntrepriseADroite:
    def test_entreprise_et_ville_a_droite_coordonnees_a_gauche(self):
        html = build_lettre_html(
            COORDONNEES,
            "Ingénieur IA",
            LETTRE_TEXTE,
            "SFEIR",
            "67 - Obernai",
            date(2026, 10, 15),
        )
        assert "Grégoire Marchand" in html
        assert "SFEIR" in html
        assert "Obernai" in html
        # coordonnées avant le bloc entreprise dans le HTML (gauche avant droite)
        assert html.index("Grégoire Marchand") < html.index("SFEIR")

    def test_meme_entreprise_que_le_nom_de_fichier_pour_un_intermediaire(
        self, db_path, coordonnees_path, intermediaires_path
    ):
        """Critère 13 : offre d'un intermédiaire connu → l'employeur de la fiche,
        exactement comme `resolve_piece_filename` (EXE-102)."""
        offer_id = 1
        _insert_offer(db_path, offer_id, title="Data Engineer", company="EDITX BV")
        _insert_fiche(db_path, offer_id, employeur_nom="Proximus Ada")
        _insert_lettre_done(db_path, offer_id, LETTRE_TEXTE)

        apercu = api_lettre.get_lettre_mise_en_page(offer_id)
        html = apercu.body.decode("utf-8")
        assert "Proximus Ada" in html
        assert "EDITX BV" not in html


# ---------------------------------------------------------------------------
# Critère 15 — sans entreprise résolue, le bloc de droite est absent
# ---------------------------------------------------------------------------


class TestCritere15SansEntrepriseResolue:
    def test_bloc_absent_sans_entreprise(self):
        html_sans = build_lettre_html(
            COORDONNEES, "Ingénieur IA", LETTRE_TEXTE, None, None
        )
        assert 'class="entreprise"' not in html_sans

    def test_bloc_present_sans_entreprise_mais_pas_le_contraire(self):
        html_avec = build_lettre_html(
            COORDONNEES, "Ingénieur IA", LETTRE_TEXTE, "SFEIR", None
        )
        assert 'class="entreprise"' in html_avec
        assert "SFEIR" in html_avec

    def test_aucune_adresse_ni_nom_de_personne_invente(self):
        html = build_lettre_html(
            COORDONNEES, "Ingénieur IA", LETTRE_TEXTE, "SFEIR", "67 - Obernai"
        )
        for mot_interdit in ("Service", "Monsieur", "Madame", "Rue", "Avenue"):
            assert mot_interdit not in html

    def test_integration_offre_sans_entreprise_ni_fiche(
        self, db_path, coordonnees_path
    ):
        offer_id = 2
        _insert_offer(db_path, offer_id, title="Ingénieur IA", company=None)
        _insert_lettre_done(db_path, offer_id, LETTRE_TEXTE)
        apercu = api_lettre.get_lettre_mise_en_page(offer_id)
        html = apercu.body.decode("utf-8")
        assert 'class="entreprise"' not in html


# ---------------------------------------------------------------------------
# Critère 16 — date, objet, texte, signature inchangés, sous les deux blocs
# ---------------------------------------------------------------------------


class TestCritere16RestantInchange:
    def test_date_objet_texte_signature_toujours_presents(self):
        html = build_lettre_html(
            COORDONNEES,
            "Ingénieur IA",
            LETTRE_TEXTE,
            "SFEIR",
            "67 - Obernai",
            date(2026, 10, 15),
        )
        assert "Strasbourg, le 15 octobre 2026" in html
        assert "Objet : candidature au poste de Ingénieur IA" in html
        assert LETTRE_TEXTE in html
        assert html.rindex("Grégoire Marchand") > html.index("Objet :")

    def test_texte_de_la_lettre_jamais_modifie(self, db_path, coordonnees_path):
        offer_id = 3
        _insert_offer(db_path, offer_id, title="Ingénieur IA", company="SFEIR")
        _insert_lettre_done(db_path, offer_id, LETTRE_TEXTE)
        apercu = api_lettre.get_lettre_mise_en_page(offer_id)
        html = apercu.body.decode("utf-8")
        assert LETTRE_TEXTE in html


# ---------------------------------------------------------------------------
# Non-régression — mêmes refus que le PDF, même phrase pour les deux routes
# ---------------------------------------------------------------------------


class TestNonRegressionMemesRefus:
    def test_pdf_et_apercu_identiques_avec_entreprise(
        self, db_path, coordonnees_path, monkeypatch
    ):
        offer_id = 4
        _insert_offer(
            db_path,
            offer_id,
            title="Ingénieur IA",
            company="SFEIR",
            location="67 - Obernai",
        )
        _insert_lettre_done(db_path, offer_id, LETTRE_TEXTE)

        captured: dict[str, str] = {}
        original = api_lettre.html_to_pdf

        def _capture(html: str) -> bytes:
            captured["html"] = html
            return original(html)

        monkeypatch.setattr(api_lettre, "html_to_pdf", _capture)

        pdf_response = api_lettre.get_lettre_pdf(offer_id)
        assert pdf_response.body[:5] == b"%PDF-"
        apercu_response = api_lettre.get_lettre_mise_en_page(offer_id)

        assert apercu_response.body.decode("utf-8") == captured["html"]
        assert "SFEIR" in captured["html"]
        assert "Obernai" in captured["html"]

    def test_offre_non_retenue_toujours_refusee(self, db_path, coordonnees_path):
        offer_id = 5
        _insert_offer(db_path, offer_id, verdict="rejete", company="SFEIR")
        with pytest.raises(HTTPException) as exc_info:
            api_lettre.get_lettre_pdf(offer_id)
        assert exc_info.value.status_code == 409
