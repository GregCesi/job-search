"""Test EXE-107 (TCK-221) — critère 16 : le README nomme la commande qui
ajoute des offres au jeu de référence et celle qui le rejoue."""

from pathlib import Path

REPO = Path(__file__).resolve().parent.parent


def test_critere16_readme_nomme_les_deux_commandes():
    text = (REPO / "README.md").read_text(encoding="utf-8")

    assert "orchestrator.job_search.reference.ajouter" in text
    assert "orchestrator.job_search.reference.rejouer" in text
