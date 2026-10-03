"""Tests EXE-107 (TCK-221) — le jeu de référence : ajout d'offres par
identifiant, préremplissage, marque de relecture, empreinte.

Aucun test n'appelle Ollama ni n'écrit dans le mlflow.db du dépôt (pas
concerné ici). Aucun test ne lit ni n'écrit sous data/ : chaque test pointe
son propre fichier de jeu (tmp_path) et une base SQLite en mémoire.
"""

import sqlite3

import pytest

from orchestrator.job_search.reference.dataset import (
    add_offers,
    jeu_fingerprint,
    load_jeu,
    save_jeu,
)
from orchestrator.job_search.sources.base import ExtractedFacts, TechRequirement
from orchestrator.job_search.storage.db import init_db

FACTS = ExtractedFacts(
    seniority_required="intermediate",
    techs_required=[TechRequirement(name="python", importance="core")],
    domain="ai_engineering",
    role_level="ic",
)


@pytest.fixture
def conn():
    c = sqlite3.connect(":memory:")
    c.row_factory = sqlite3.Row
    init_db(c)
    return c


def _insert_offer(conn, offer_id, title, description, facts: ExtractedFacts | None):
    conn.execute(
        "INSERT INTO offers (id, source, source_id, fingerprint, title, description, "
        "extracted_facts_json, fetched_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (
            offer_id,
            "france_travail",
            f"FT-{offer_id}",
            f"fp-{offer_id}",
            title,
            description,
            facts.model_dump_json() if facts else None,
            "2026-10-01T00:00:00+00:00",
        ),
    )
    conn.commit()


# ---------------------------------------------------------------------------
# Critère 1 — ajout, préremplissage, marque « non relu »
# ---------------------------------------------------------------------------


def test_critere1_ajoute_une_offre_prereplie_non_relue(tmp_path, conn):
    _insert_offer(conn, 1, "Dev IA", "Texte de l'offre", FACTS)
    jeu_path = tmp_path / "jeu.json"

    report = add_offers(conn, [1], jeu_path=jeu_path)

    assert report.added == [1]
    entries = load_jeu(jeu_path)
    assert entries["1"].title == "Dev IA"
    assert entries["1"].text == "Texte de l'offre"
    assert entries["1"].attendu == FACTS
    assert entries["1"].relu is False


def test_critere1_offre_sans_faits_extraits_est_ignoree(tmp_path, conn):
    _insert_offer(conn, 2, "Dev IA", "Texte", None)
    jeu_path = tmp_path / "jeu.json"

    report = add_offers(conn, [2], jeu_path=jeu_path)

    assert report.added == []
    assert report.skipped_no_facts == [2]
    assert load_jeu(jeu_path) == {}


# ---------------------------------------------------------------------------
# Critère 2 — relance avec d'autres identifiants : fusion, attendu et marque
# inchangés sur les entrées déjà présentes
# ---------------------------------------------------------------------------


def test_critere2_relance_ajoute_les_nouvelles_garde_les_existantes(tmp_path, conn):
    _insert_offer(conn, 1, "Dev IA", "Texte 1", FACTS)
    _insert_offer(conn, 2, "Dev Python", "Texte 2", FACTS)
    jeu_path = tmp_path / "jeu.json"

    add_offers(conn, [1], jeu_path=jeu_path)
    entries = load_jeu(jeu_path)
    entries["1"].relu = True
    entries["1"].attendu = entries["1"].attendu.model_copy(update={"domain": "backend"})
    save_jeu(entries, jeu_path)

    report = add_offers(conn, [1, 2], jeu_path=jeu_path)

    assert report.added == [2]
    assert report.skipped_existing == [1]
    entries = load_jeu(jeu_path)
    assert entries["1"].relu is True  # marque conservée
    assert entries["1"].attendu.domain == "backend"  # attendu corrigé conservé
    assert "2" in entries
    assert entries["2"].relu is False


# ---------------------------------------------------------------------------
# Critère 13 — empreinte du jeu
# ---------------------------------------------------------------------------


def test_critere13_empreinte_change_si_un_attendu_change(tmp_path, conn):
    _insert_offer(conn, 1, "Dev IA", "Texte", FACTS)
    jeu_path = tmp_path / "jeu.json"
    add_offers(conn, [1], jeu_path=jeu_path)
    entries = load_jeu(jeu_path)
    fp_avant = jeu_fingerprint(entries)

    entries["1"].attendu = entries["1"].attendu.model_copy(update={"domain": "backend"})
    fp_apres = jeu_fingerprint(entries)

    assert fp_avant != fp_apres


def test_critere13_empreinte_stable_sur_un_jeu_inchange(tmp_path, conn):
    _insert_offer(conn, 1, "Dev IA", "Texte", FACTS)
    jeu_path = tmp_path / "jeu.json"
    add_offers(conn, [1], jeu_path=jeu_path)
    entries_a = load_jeu(jeu_path)
    entries_b = load_jeu(jeu_path)

    assert jeu_fingerprint(entries_a) == jeu_fingerprint(entries_b)


# ---------------------------------------------------------------------------
# Ce qui ne doit pas arriver — le préremplissage ne marque jamais « relu »
# ---------------------------------------------------------------------------


def test_prereplissage_ne_marque_jamais_relu(tmp_path, conn):
    _insert_offer(conn, 1, "Dev IA", "Texte", FACTS)
    jeu_path = tmp_path / "jeu.json"

    add_offers(conn, [1], jeu_path=jeu_path)

    assert load_jeu(jeu_path)["1"].relu is False
