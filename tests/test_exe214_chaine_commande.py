"""Tests EXE-214 — la chaîne de l'écran à la table, lue par la commande
`python -m outils.carte` : routes, écrans, tables, couches et appels directs à
la base (critères 5, 6, 12, 13, 16, 17, 22, 24, 25, 27).

Les critères vus à l'écran sont dans `tests/test_exe214_chaine_navigateur.py`.
Chaque test lit ce que la page embarque ; une donnée absente fait échouer
l'assertion, pas la collecte.
"""

from __future__ import annotations

import re
import subprocess
import sys

import pytest

from tests.carte_terrains import (
    REPO,
    fichiers_front_du_disque,
    lancer_carte,
    lire_donnees,
    poser_depot_essai_etendu,
)

METHODES = ("get", "post", "put", "patch", "delete")


@pytest.fixture(scope="module")
def vrai_depot(tmp_path_factory):
    sortie = tmp_path_factory.mktemp("chaine_vraie") / "index.html"
    res = lancer_carte(REPO, sortie)
    assert res.returncode == 0, res.stdout + res.stderr
    return res, lire_donnees(sortie)


@pytest.fixture(scope="module")
def essai(tmp_path_factory):
    racine = poser_depot_essai_etendu(tmp_path_factory.mktemp("chaine") / "essai")
    res = lancer_carte(racine)
    assert res.returncode == 0, res.stdout + res.stderr
    return res, lire_donnees(racine / "docs" / "carte" / "index.html")


def _routes_relues(racine) -> list[tuple[str, str]]:
    """Les routes de api/, relues par expressions régulières : chaque nom posé
    sur `APIRouter(...)` ou `FastAPI(...)` avec son préfixe, puis chaque
    décorateur `@nom.methode("chemin")`."""
    trouvees = []
    for p in sorted((racine / "api").rglob("*.py")):
        texte = p.read_text(encoding="utf-8")
        prefixes = {}
        for m in re.finditer(
            r"^(\w+)\s*=\s*(?:APIRouter|FastAPI)\((.*?)\)", texte, re.M | re.S
        ):
            pref = re.search(r"prefix\s*=\s*[\"']([^\"']*)[\"']", m.group(2))
            prefixes[m.group(1)] = pref.group(1) if pref else ""
        motif = r"^\s*@(\w+)\.(" + "|".join(METHODES) + r")\(\s*[\"']([^\"']*)[\"']"
        for m in re.finditer(motif, texte, re.M):
            assert m.group(1) in prefixes, f"{p}: routeur inconnu {m.group(1)}"
            trouvees.append((m.group(2).upper(), prefixes[m.group(1)] + m.group(3)))
    return sorted(trouvees)


def _tables_relues(racine) -> list[str]:
    noms = set()
    for dossier in ("api", "orchestrator"):
        for p in (racine / dossier).rglob("*.py"):
            noms.update(
                re.findall(
                    r"CREATE TABLE (?:IF NOT EXISTS )?(\w+)",
                    p.read_text(encoding="utf-8"),
                )
            )
    return sorted(noms)


class TestLesRoutes:
    def test_critere5_routes_du_vrai_depot(self, vrai_depot):
        _, donnees = vrai_depot
        attendues = _routes_relues(REPO)
        assert len(attendues) >= 79
        lues = sorted(
            (r["methode"], r["chemin"]) for r in donnees.get("routes", {}).values()
        )
        assert lues == attendues


class TestLesEcrans:
    def test_critere6_chaque_fichier_du_front_dans_ecrans(self, vrai_depot):
        _, donnees = vrai_depot
        attendus = fichiers_front_du_disque(REPO)
        assert len(attendus) >= 30
        ecrans = donnees.get("ecrans") or {}
        assert ecrans.get("nom") == "Écrans"
        assert sorted(ecrans.get("fichiers", [])) == attendus
        assert sorted(donnees.get("fichiers_front", {})) == attendus

    def test_critere12_appel_sans_route_trouvee(self, essai):
        res, _ = essai
        lignes = [
            ligne
            for ligne in res.stdout.splitlines()
            if ligne.startswith("signalé : appel sans route trouvée : ")
        ]
        assert len(lignes) == 1, res.stdout
        assert "web/app/components/ChoseCarte.vue" in lignes[0]
        assert "${base}/inconnu" in lignes[0]

    def test_critere13_adresse_illisible(self, essai):
        res, donnees = essai
        lignes = [
            ligne
            for ligne in res.stdout.splitlines()
            if ligne.startswith("signalé : adresse illisible : ")
        ]
        assert len(lignes) == 1, res.stdout
        assert "web/app/components/ChoseSuite.vue" in lignes[0]
        assert "${props.adresse}/suite" in lignes[0]
        front = donnees.get("fichiers_front", {})
        appels = front.get("web/app/components/ChoseSuite.vue", {}).get("appels", [])
        assert len(appels) == 1
        assert appels[0]["routes"] == []
        assert all(
            "web/app/components/ChoseSuite.vue" not in r["appelee_par"]
            for r in donnees.get("routes", {}).values()
        )


class TestLesTables:
    def test_critere16_une_table_sur_l_essai(self, essai):
        _, donnees = essai
        assert sorted(donnees.get("tables", {})) == ["choses"]

    def test_critere17_tables_du_vrai_depot(self, vrai_depot):
        _, donnees = vrai_depot
        attendues = _tables_relues(REPO)
        assert len(attendues) >= 19
        assert sorted(donnees.get("tables", {})) == attendues

    def test_critere22_table_illisible(self, essai):
        res, donnees = essai
        assert "signalé : table illisible : orchestrator/b_choses.py:9" in res.stdout, (
            res.stdout
        )
        illisibles = donnees.get("a_verifier", {}).get("tables_illisibles", [])
        assert {"fichier": "orchestrator/b_choses.py", "ligne": 9} in illisibles


class TestLesCouches:
    def test_critere24_couche_de_chaque_fichier(self, essai):
        _, donnees = essai
        f = donnees["fichiers"]
        assert f["api/choses.py"].get("couche") == "route"
        assert f["orchestrator/storage/choses.py"].get("couche") == "stockage"
        autres = set(f) - {"api/choses.py", "orchestrator/storage/choses.py"}
        assert autres
        assert {f[c].get("couche") for c in autres} == {"métier"}

    def test_critere25_appels_directs_par_fichier(self, essai):
        _, donnees = essai
        f = donnees["fichiers"]
        attendus = {
            "api/choses.py": 1,
            "orchestrator/a_metier.py": 1,
            "orchestrator/storage/choses.py": 2,
            "orchestrator/b_choses.py": 2,
        }
        for chemin, n in attendus.items():
            assert f[chemin].get("appels_base") == n, chemin
        assert all(f[c].get("appels_base") == 0 for c in set(f) - set(attendus))


class TestLeCliquet:
    def test_critere27_meme_compte_que_le_cliquet(self, vrai_depot):
        _, donnees = vrai_depot
        res = subprocess.run(
            [sys.executable, "scripts/cliquet.py", "--mesure"],
            cwd=REPO,
            capture_output=True,
            text=True,
            timeout=300,
        )
        assert res.returncode == 0, res.stdout + res.stderr
        lignes = res.stdout.splitlines()
        total = int(re.fullmatch(r"execute hors stockage : (\d+)", lignes[0]).group(1))
        par_fichier = {}
        for ligne in lignes[1:]:
            m = re.fullmatch(r"\s+(\d+)\s+(\S+\.py)", ligne)
            if not m:
                break
            par_fichier[m.group(2)] = int(m.group(1))
        assert par_fichier
        base = donnees.get("base", {})
        assert base.get("hors_stockage") == total
        assert dict(base.get("fichiers", [])) == par_fichier
        for chemin, n in par_fichier.items():
            assert donnees["fichiers"][chemin].get("appels_base") == n, chemin
