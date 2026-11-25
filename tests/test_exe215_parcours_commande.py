"""Tests EXE-215 — la commande : parcours du vrai dépôt (critères 7, 14 à 21),
relevé et changements sur le dépôt d'essai (critères 22, 23, 25, 27 à 30), et
relevé suivi par git (critère 32).

La commande se lance en sous-processus (`tests/carte_terrains.py`). Sur le vrai
dépôt, page et relevé s'écrivent dans un dossier temporaire.
"""

from __future__ import annotations

import json
import re
import subprocess

import pytest

from tests.carte_terrains import (
    REPO,
    lancer_carte,
    lire_donnees,
    poser_depot_essai_etendu,
)

NOMS = [
    "Je retiens une offre : son CV est généré et rangé en base",
    "Le run : d'une source à une offre classée",
    "Je change mon profil : tout se reclasse sans appeler un modèle",
    "Je marque une candidature envoyée",
]
ORCH = "orchestrator/job_search/"


@pytest.fixture(scope="module")
def parcours(tmp_path_factory):
    dossier = tmp_path_factory.mktemp("parcours_vrai")
    res = lancer_carte(REPO, dossier / "page" / "index.html", dossier / "graphe.json")
    assert res.returncode == 0, res.stdout + res.stderr
    donnees = lire_donnees(dossier / "page" / "index.html")
    return {p["nom"]: p["etapes"] for p in donnees.get("parcours", [])}, donnees


def _elements(etapes):
    return [(e["genre"], e["element"]) for e in etapes]


def _dans_l_ordre(etapes, attendus):
    """Les éléments attendus apparaissent dans les étapes, dans cet ordre."""
    i = 0
    for e in etapes:
        if i < len(attendus) and attendus[i](e):
            i += 1
    return i == len(attendus)


def _fichier(chemin):
    return lambda e: e["genre"] == "fichier" and e["element"] == chemin


def _route(rid):
    return lambda e: e["genre"] == "route" and e["element"] == rid


def _ecran(e):
    return e["genre"] == "fichier" and e["element"].startswith("web/app/")


class TestLesParcoursDuVraiDepot:
    def test_critere7_quatre_parcours_sous_ces_noms(self, parcours):
        assert list(parcours[0]) == NOMS

    def test_critere14_je_retiens_une_offre(self, parcours):
        etapes = parcours[0][NOMS[0]]
        assert _dans_l_ordre(
            etapes,
            [
                _ecran,
                _route("POST /offers/{offer_id}/geste"),
                _fichier("api/cv.py"),
                _fichier(ORCH + "cv/service.py"),
            ],
        ), _elements(etapes)
        assert _elements(etapes)[-1] == ("table", "cvs")

    def test_critere15_les_deux_barrieres(self, parcours):
        etapes = parcours[0][NOMS[0]]
        fonctions = {
            e["fonction"]
            for e in etapes
            if e["genre"] == "fichier" and e["element"] == ORCH + "cv/skills.py"
        }
        assert {"compute_permitted_additions", "filter_model_groups"} <= fonctions

    def test_critere16_le_run(self, parcours):
        etapes = parcours[0][NOMS[1]]
        assert _elements(etapes)[0] == ("fichier", ORCH + "run.py")
        assert _dans_l_ordre(
            etapes,
            [
                lambda e: e["element"].startswith(ORCH + "sources/"),
                _fichier(ORCH + "storage/dedup.py"),
                _fichier(ORCH + "scoring/extractor.py"),
                _fichier(ORCH + "scoring/categorize.py"),
            ],
        ), _elements(etapes)
        assert _elements(etapes)[-1] == ("table", "offers")

    def test_critere17_je_change_mon_profil(self, parcours):
        etapes = parcours[0][NOMS[2]]
        elements = _elements(etapes)
        assert elements[0] == ("fichier", ORCH + "rescore.py")
        assert ("fichier", ORCH + "scoring/attainability.py") in elements
        assert ("fichier", ORCH + "scoring/desirability.py") in elements
        assert elements[-1] == ("table", "offers")

    def test_critere18_renvoi_a_la_regle(self, parcours):
        etapes = parcours[0][NOMS[2]]
        assert any(
            e["regle"] == ".claude/rules/architecture.md, section 4" for e in etapes
        )

    def test_critere19_candidature_envoyee(self, parcours):
        etapes = parcours[0][NOMS[3]]
        assert _dans_l_ordre(
            etapes,
            [
                _fichier("web/app/pages/offers/[id].vue"),
                _route("PUT /offers/{offer_id}/envoyee"),
                _fichier(ORCH + "suivi/etats.py"),
                _fichier(ORCH + "suivi/storage.py"),
            ],
        ), _elements(etapes)
        assert _elements(etapes)[-1] == ("table", "historique_gestes")

    def test_critere20_chaque_etape_cite_un_element_de_la_carte(self, parcours):
        noms, donnees = parcours
        presents = {
            "fichier": set(donnees["fichiers"]) | set(donnees["fichiers_front"]),
            "route": set(donnees["routes"]),
            "table": set(donnees["tables"]),
        }
        etapes = [e for p in noms.values() for e in p]
        assert len(etapes) >= 20
        for e in etapes:
            assert e["element"] in presents[e["genre"]], e
            assert e["phrase"].strip(), e

    def test_interdit_aucune_phrase_ne_juge_le_code(self, parcours):
        noms, donnees = parcours
        phrases = [e["phrase"] for p in noms.values() for e in p]
        phrases += [b["role"] for b in donnees["ensemble"]["blocs"]]
        for phrase in phrases:
            assert not re.search(r"mal fait|à refaire|dette", phrase, re.I), phrase


@pytest.fixture
def essai(tmp_path):
    return poser_depot_essai_etendu(tmp_path / "essai")


def _releve(racine):
    return racine / "docs" / "carte" / "graphe.json"


def _remplacer(racine, rel, avant, apres):
    chemin = racine / rel
    texte = chemin.read_text(encoding="utf-8")
    assert avant in texte
    chemin.write_text(texte.replace(avant, apres), encoding="utf-8")


class TestUnParcoursFaux:
    def test_critere21_etape_sur_un_fichier_absent(self, essai):
        textes = essai / "docs" / "carte" / "textes.toml"
        textes.write_text(
            textes.read_text(encoding="utf-8")
            + '\n[[parcours]]\nid = "p"\nnom = "Parcours d\'essai"\n'
            '\n[[parcours.etape]]\nfichier = "api/a1.py"\nphrase = "Un."\n'
            '\n[[parcours.etape]]\nfichier = "api/absent.py"\nphrase = "Deux."\n',
            encoding="utf-8",
        )
        res = lancer_carte(essai)
        sortie = res.stdout + res.stderr
        assert res.returncode == 1, sortie
        assert "Parcours d'essai" in sortie
        assert re.search(r"étape 2\b", sortie), sortie
        assert "api/absent.py" in sortie


class TestLeReleve:
    def test_critere22_contenu_du_releve(self, essai):
        res = lancer_carte(essai)
        assert res.returncode == 0, res.stdout + res.stderr
        releve = json.loads(_releve(essai).read_text(encoding="utf-8"))
        assert "api/a1.py" in releve["fichiers"]
        assert "web/app/stores/choses.ts" in releve["fichiers"]
        assert ["api/a1.py", "orchestrator/b1.py"] in releve["fleches"]
        assert releve["routes"]["GET /choses/{chose_id}"] == "api/choses.py"
        assert releve["tables"]["orchestrator/a_metier.py"]["lues"] == ["choses"]
        assert releve["tables"]["orchestrator/storage/choses.py"]["ecrites"] == [
            "choses"
        ]
        assert releve["appels_base"]["orchestrator/b_choses.py"] == 2

    def test_critere23_deux_lancements_meme_releve(self, essai):
        lancer_carte(essai)
        premier = _releve(essai).read_bytes()
        res = lancer_carte(essai)
        assert res.returncode == 0, res.stdout + res.stderr
        assert _releve(essai).read_bytes() == premier

    def test_critere24_premier_lancement_rend_0(self, essai):
        assert not _releve(essai).exists()
        res = lancer_carte(essai)
        assert res.returncode == 0, res.stdout + res.stderr
        assert lire_donnees(essai / "docs/carte/index.html")["depuis"]["premier"]

    def test_critere25_fleche_disparue(self, essai):
        lancer_carte(essai)
        _remplacer(
            essai, "api/a1.py", "from orchestrator import b1\n\nVALEUR = b1.VALEUR", ""
        )
        res = lancer_carte(essai)
        assert res.returncode == 0, res.stdout + res.stderr
        assert (
            "signalé : flèche disparue : api/a1.py → orchestrator/b1.py" in res.stdout
        ), res.stdout

    def test_critere27_fleche_nouvelle(self, essai):
        lancer_carte(essai)
        _remplacer(
            essai,
            "orchestrator/b1.py",
            "VALEUR = 1\n",
            "from api import a2\n\nVALEUR = 1\n",
        )
        res = lancer_carte(essai)
        assert (
            "signalé : flèche nouvelle : orchestrator/b1.py → api/a2.py" in res.stdout
        ), res.stdout

    def test_criteres28_29_appels_directs_et_hors_stockage(self, essai):
        lancer_carte(essai)
        _remplacer(
            essai,
            "orchestrator/b_choses.py",
            '    conn.execute("UPDATE choses SET nom = ?", (nom,))\n',
            "    return nom\n",
        )
        res = lancer_carte(essai)
        lignes = res.stdout.splitlines()
        assert (
            "signalé : appels directs à la base : orchestrator/b_choses.py : 2 → 1"
            in lignes
        ), res.stdout
        assert "signalé : hors stockage : 4 → 3" in lignes, res.stdout

    def test_critere30_fichier_disparu(self, essai):
        nouveau = essai / "orchestrator" / "nouveau.py"
        nouveau.write_text('"""Neuf."""\n', encoding="utf-8")
        lancer_carte(essai)
        nouveau.unlink()
        res = lancer_carte(essai)
        assert "signalé : fichier disparu : orchestrator/nouveau.py" in res.stdout, (
            res.stdout
        )


class TestLeDepot:
    def test_critere32_le_releve_est_suivi(self):
        suivi = subprocess.run(
            ["git", "ls-files", "--error-unmatch", "docs/carte/graphe.json"],
            cwd=REPO,
            capture_output=True,
        )
        assert suivi.returncode == 0
        ignore = subprocess.run(
            ["git", "check-ignore", "-q", "docs/carte/graphe.json"], cwd=REPO
        )
        assert ignore.returncode == 1

    def test_interdit_ni_date_ni_commit_dans_le_releve(self):
        texte = (REPO / "docs" / "carte" / "graphe.json").read_text(encoding="utf-8")
        assert not re.search(r"\d{4}-\d{2}-\d{2}|\d{1,2}:\d{2}", texte)
        assert "commit" not in texte and "genere_le" not in texte
