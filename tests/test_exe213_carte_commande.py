"""Tests EXE-213 — la commande `python -m outils.carte`, ses sorties et ses
signalements (critères 1 à 3, 6, 8, 9, 19 à 22, 26, 28 à 30, 33, 34).

Les critères vus à l'écran sont dans `tests/test_exe213_carte_navigateur.py`.
"""

from __future__ import annotations

import re
import subprocess
import tomllib

import pytest

from tests.carte_terrains import (
    PAS_DE_PHRASE,
    REPO,
    fichiers_du_disque,
    lancer_carte,
    lire_donnees,
    poser_depot_essai,
)


@pytest.fixture(scope="module")
def vrai_depot(tmp_path_factory):
    sortie = tmp_path_factory.mktemp("carte_vraie") / "index.html"
    return lancer_carte(REPO, sortie), sortie


@pytest.fixture
def essai(tmp_path):
    return poser_depot_essai(tmp_path / "essai")


def _page_essai(racine):
    return racine / "docs" / "carte" / "index.html"


class TestLaCommande:
    def test_critere1_rend_0_depuis_la_racine(self, vrai_depot):
        res, _ = vrai_depot
        assert res.returncode == 0, res.stdout + res.stderr

    def test_critere2_ecrit_la_page_par_defaut_sous_docs_carte(self, essai):
        res = lancer_carte(essai)
        assert res.returncode == 0, res.stdout + res.stderr
        assert _page_essai(essai).is_file()

    def test_critere3_ligne_de_resume(self, essai):
        res = lancer_carte(essai)
        assert re.search(
            r"4 fichiers, 1 flèche entre fichiers, 2 systèmes", res.stdout
        ), res.stdout

    def test_critere6_lit_sans_executer(self, essai):
        res = lancer_carte(essai)
        assert res.returncode == 0, res.stdout + res.stderr
        assert "b2 ne s'importe pas" not in res.stdout + res.stderr

    def test_critere34_derniere_ligne_est_le_chemin_de_la_page(self, essai):
        res = lancer_carte(essai)
        lignes = res.stdout.strip().splitlines()
        assert lignes, res.stderr
        assert lignes[-1] == str(_page_essai(essai))

    def test_critere34_vrai_depot(self, vrai_depot):
        res, sortie = vrai_depot
        lignes = res.stdout.strip().splitlines()
        assert lignes, res.stderr
        assert lignes[-1] == str(sortie)


class TestLesSystemesDuVraiDepot:
    def test_critere8_chaque_fichier_dans_un_systeme_et_un_seul(self, vrai_depot):
        res, sortie = vrai_depot
        assert res.returncode == 0, res.stdout + res.stderr
        donnees = lire_donnees(sortie)
        ranges = [f for s in donnees["systemes"] for f in s["fichiers"]]
        assert len(ranges) == len(set(ranges))
        assert sorted(ranges) == fichiers_du_disque(REPO)
        assert sorted(donnees["fichiers"]) == fichiers_du_disque(REPO)
        assert donnees["autres"] == []

    def test_critere9_le_cv_porte_ses_routes(self, vrai_depot):
        _, sortie = vrai_depot
        donnees = lire_donnees(sortie)
        fichiers = donnees["fichiers"]
        assert (
            fichiers["orchestrator/job_search/cv/service.py"]["systeme"]
            == fichiers["api/cv.py"]["systeme"]
        )


class TestLesPhrases:
    def test_critere19_premiere_phrase_de_la_docstring(self, essai):
        lancer_carte(essai)
        donnees = lire_donnees(_page_essai(essai))
        assert donnees["fichiers"]["api/a1.py"]["phrase"] == "Première phrase de a1."

    def test_critere20_phrase_du_fichier_de_textes(self, essai):
        textes = essai / "docs" / "carte" / "textes.toml"
        textes.write_text(
            textes.read_text(encoding="utf-8")
            + '\n[phrases]\n"api/a2.py" = "Porte la valeur deux."\n',
            encoding="utf-8",
        )
        res = lancer_carte(essai)
        assert res.returncode == 0, res.stdout + res.stderr
        donnees = lire_donnees(_page_essai(essai))
        assert donnees["fichiers"]["api/a2.py"]["phrase"] == "Porte la valeur deux."
        assert "fichier sans phrase" not in res.stdout

    def test_critere21_fichier_sans_phrase_signale(self, essai):
        res = lancer_carte(essai)
        assert res.returncode == 0, res.stdout + res.stderr
        assert "signalé : fichier sans phrase : api/a2.py" in res.stdout
        donnees = lire_donnees(_page_essai(essai))
        assert donnees["fichiers"]["api/a2.py"]["phrase"] == PAS_DE_PHRASE

    def test_critere22_vrai_depot_aucun_fichier_sans_phrase(self, vrai_depot):
        res, sortie = vrai_depot
        assert "fichier sans phrase" not in res.stdout
        donnees = lire_donnees(sortie)
        sans = [
            c for c, f in donnees["fichiers"].items() if f["phrase"] == PAS_DE_PHRASE
        ]
        assert sans == []
        assert len(donnees["fichiers"]) == len(fichiers_du_disque(REPO))


class TestLesSignalements:
    def test_critere26_fichier_nouveau_non_range(self, essai):
        (essai / "orchestrator" / "nouveau.py").write_text('"""Neuf."""\n')
        res = lancer_carte(essai)
        assert res.returncode == 0, res.stdout + res.stderr
        assert (
            "signalé : fichier nouveau qu'aucun système ne range : "
            "orchestrator/nouveau.py" in res.stdout
        )
        donnees = lire_donnees(_page_essai(essai))
        assert donnees["autres"] == ["orchestrator/nouveau.py"]

    def test_critere28_fichier_cite_supprime(self, essai):
        (essai / "orchestrator" / "b2.py").unlink()
        res = lancer_carte(essai)
        assert res.returncode == 1, res.stdout + res.stderr
        assert "orchestrator/b2.py" in res.stdout + res.stderr

    def test_critere29_fichier_dans_deux_systemes(self, essai):
        textes = essai / "docs" / "carte" / "textes.toml"
        textes.write_text(
            textes.read_text(encoding="utf-8").replace(
                '"orchestrator/b2.py"]', '"orchestrator/b2.py", "api/a2.py"]'
            ),
            encoding="utf-8",
        )
        res = lancer_carte(essai)
        sortie = res.stdout + res.stderr
        assert res.returncode == 1, sortie
        assert "api/a2.py" in sortie
        assert "Système A" in sortie and "Système B" in sortie


class TestLeDepot:
    def test_critere30_la_page_n_est_pas_suivie(self):
        res = subprocess.run(
            ["git", "check-ignore", "-q", "docs/carte/index.html"], cwd=REPO
        )
        assert res.returncode == 0

    def test_critere30_le_fichier_de_textes_est_suivi(self):
        textes = REPO / "docs" / "carte" / "textes.toml"
        assert textes.is_file()
        tomllib.loads(textes.read_text(encoding="utf-8"))
        res = subprocess.run(
            ["git", "check-ignore", "-q", "docs/carte/textes.toml"], cwd=REPO
        )
        assert res.returncode == 1


class TestLeReadme:
    def test_critere33_section_carte_du_code(self):
        texte = (REPO / "README.md").read_text(encoding="utf-8")
        trouve = re.search(r"^## Carte du code\n(.*?)(?=^## |\Z)", texte, re.S | re.M)
        assert trouve, "pas de section « Carte du code »"
        section = trouve.group(1)
        blocs = re.findall(r"```(?:bash|sh)?\n(.*?)```", section, re.S)
        assert len(blocs) == 1
        lignes = [ligne for ligne in blocs[0].splitlines() if ligne.strip()]
        assert len(lignes) == 1
        ligne = lignes[0]
        assert ".venv/bin/python -m outils.carte" in ligne
        assert "open docs/carte/index.html" in ligne
        assert ligne.index("outils.carte") < ligne.index("open ")
        phrase = section.split("```")[0].strip()
        assert phrase and "carte" in phrase.lower()
