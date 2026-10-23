"""Tests EXE-202 — navigateur réel (Playwright/Chromium, H5) sur les critères
1 à 5 et 7 : la section « en erreur » de l'onglet Lettre, l'annulation
d'en-tête qui remet le bloc d'envoi à jour, et la revue hors périmètre de la
vue opérateur.

Front (`npm run dev`, sous-processus, groupe de process à part) et API
(`uvicorn.Server` dans un thread du même interpréteur, H2 : `DB_PATH` est
forcé par monkeypatch sur les modules déjà importés, lu à chaque appel de
`get_conn()`) démarrent une fois pour tout le module (critère 8), sur des
ports libres choisis au lancement (critère 10) ; `api.main` est réimporté à
chaque lancement pour repartir d'un middleware CORS non figé, et son origine
autorisée est élargie au port du front choisi ce lancement-ci — aucune ligne
de `api/main.py` n'est modifiée, c'est une construction propre au test.
Chaque test pose sa propre base dans un dossier temporaire (fixture
`db_path`, comme `test_exe201_corrections_jet46.py`) : le serveur déjà lancé
la relit à chaque requête (`DB_PATH` est un attribut de module relu par
`get_conn()`, jamais figé à l'import).
"""

from __future__ import annotations

import importlib
import os
import re
import signal
import socket
import sqlite3
import subprocess
import sys
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

import pytest
from playwright.sync_api import expect, sync_playwright

import api.db as api_db
import orchestrator.job_search.storage.db as storage_db
from orchestrator.job_search.storage.db import init_db
from orchestrator.job_search.suivi import etats as suivi_etats
from orchestrator.job_search.suivi import storage as suivi_storage

REPO_ROOT = Path(__file__).resolve().parent.parent
WEB_DIR = REPO_ROOT / "web"
REAL_DB_PATH = REPO_ROOT / "data" / "job_search.sqlite"

START_TIMEOUT_S = 30


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _real_db_stat() -> tuple[float, int] | None:
    if not REAL_DB_PATH.exists():
        return None
    st = REAL_DB_PATH.stat()
    return (st.st_mtime, st.st_size)


def _wait_http_ok(
    url: str, timeout_s: float, proc: subprocess.Popen | None, nom: str
) -> None:
    deadline = time.monotonic() + timeout_s
    dernier_err: Exception | None = None
    while time.monotonic() < deadline:
        if proc is not None and proc.poll() is not None:
            sortie = proc.stdout.read() if proc.stdout else ""
            pytest.fail(
                f"{nom} s'est arrêté avant d'être prêt (code {proc.returncode}).\n"
                f"Dernières lignes :\n{sortie[-2000:]}"
            )
        try:
            urllib.request.urlopen(url, timeout=1)
            return
        except Exception as e:  # noqa: BLE001 — on retente jusqu'au délai
            dernier_err = e
            time.sleep(0.3)
    pytest.fail(f"{nom} n'a pas répondu sur {url} en {timeout_s}s : {dernier_err}")


class _ServeurAPI:
    """API démarrée dans un thread du même process (H2) — `uvicorn.Server`,
    pour que les monkeypatch de `DB_PATH` posés par chaque test s'appliquent
    sans traverser de frontière de process."""

    def __init__(self, port: int, front_port: int):
        import threading

        import uvicorn
        from fastapi.middleware.cors import CORSMiddleware
        from starlette.middleware import Middleware

        if "api.main" in sys.modules:
            api_main = importlib.reload(sys.modules["api.main"])
        else:
            import api.main as api_main  # noqa: PLC0415

        patched = False
        for i, mw in enumerate(api_main.app.user_middleware):
            if mw.cls is CORSMiddleware:
                kwargs = dict(mw.kwargs)
                origines = list(kwargs.get("allow_origins", []))
                origine_front = f"http://localhost:{front_port}"
                if origine_front not in origines:
                    origines.append(origine_front)
                kwargs["allow_origins"] = origines
                api_main.app.user_middleware[i] = Middleware(CORSMiddleware, **kwargs)
                patched = True
                break
        assert patched, (
            "CORSMiddleware introuvable sur api.main.app (api/main.py a changé ?)"
        )

        self.port = port
        config = uvicorn.Config(
            api_main.app, host="127.0.0.1", port=port, log_level="warning"
        )
        self.server = uvicorn.Server(config)
        self.thread = threading.Thread(target=self.server.run, daemon=True)
        self.thread.start()
        deadline = time.monotonic() + START_TIMEOUT_S
        while not self.server.started:
            if time.monotonic() > deadline:
                pytest.fail("L'API (uvicorn, même process) n'a pas démarré à temps.")
            time.sleep(0.05)

    def stop(self) -> None:
        self.server.should_exit = True
        self.thread.join(timeout=10)


class _ServeurFront:
    """Front Nuxt démarré en sous-processus réel (H2), dans son propre groupe
    de process pour pouvoir tuer tous ses enfants à l'arrêt (critère 11)."""

    def __init__(self, port: int, api_port: int):
        if not (WEB_DIR / "node_modules").exists():
            pytest.fail(
                "web/node_modules est absent : lance d'abord `bash scripts/barre.sh` "
                "une fois (elle fait npm ci dans web/), puis relance la suite (H8)."
            )
        env = {**os.environ, "NUXT_PUBLIC_API_BASE": f"http://127.0.0.1:{api_port}"}
        self.port = port
        self.proc = subprocess.Popen(
            ["npm", "run", "dev", "--", "--port", str(port)],
            cwd=WEB_DIR,
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            start_new_session=True,
        )
        try:
            # Nuxt dev n'écoute qu'en IPv6 (`::1`) par défaut, jamais sur
            # 127.0.0.1 (constaté ici) — la sonde et la navigation utilisent
            # toutes deux `localhost`, jamais l'adresse IPv4 littérale.
            _wait_http_ok(
                f"http://localhost:{port}/",
                START_TIMEOUT_S,
                self.proc,
                "Le front (npm run dev)",
            )
        except BaseException:
            # Un échec ici ne doit pas laisser un process Nuxt orphelin tenir
            # le verrou de `web/` pour le prochain lancement (critère 11).
            self.stop()
            raise

    def stop(self) -> None:
        try:
            os.killpg(os.getpgid(self.proc.pid), signal.SIGTERM)
        except ProcessLookupError:
            return
        try:
            self.proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            os.killpg(os.getpgid(self.proc.pid), signal.SIGKILL)
            self.proc.wait(timeout=10)


@pytest.fixture(scope="module")
def navigateur_env(tmp_path_factory):
    # H8 : si le front doit faire `npm ci` lui-même (node_modules manquant),
    # ce n'est pas la responsabilité de ces tests — voir le message de
    # `_ServeurFront` ci-dessus.
    avant = _real_db_stat()

    # Avant même de démarrer le serveur, poser `DB_PATH` sur un fichier hors
    # dépôt : `_migrate_db()` (lifespan de l'API) ne doit jamais toucher
    # data/job_search.sqlite (critère 10), même pendant la fenêtre où aucun
    # test n'a encore posé sa propre base.
    from _pytest.monkeypatch import MonkeyPatch

    mp = MonkeyPatch()
    placeholder = tmp_path_factory.mktemp("navigateur_boot") / "placeholder.sqlite"
    conn = sqlite3.connect(placeholder)
    init_db(conn)
    conn.close()
    import orchestrator.job_search.paths as paths_mod

    mp.setattr(paths_mod, "DB_PATH", placeholder)
    mp.setattr(storage_db, "DB_PATH", placeholder)
    mp.setattr(api_db, "DB_PATH", placeholder)

    front_port = _free_port()
    api_port = _free_port()

    api_srv = _ServeurAPI(api_port, front_port)
    try:
        front_srv = _ServeurFront(front_port, api_port)
    except BaseException:
        api_srv.stop()
        raise

    yield {"front_port": front_port, "api_port": api_port}

    front_srv.stop()
    api_srv.stop()
    mp.undo()

    apres = _real_db_stat()
    assert apres == avant, (
        "data/job_search.sqlite a changé pendant la suite (critère 10) : "
        f"avant={avant}, après={apres}"
    )


@pytest.fixture(scope="module")
def navigateur(navigateur_env):
    with sync_playwright() as p:
        browser = p.chromium.launch()
        try:
            yield browser
        finally:
            browser.close()


@pytest.fixture
def page(navigateur):
    context = navigateur.new_context()
    pg = context.new_page()
    yield pg
    context.close()


@pytest.fixture
def front_url(navigateur_env):
    return f"http://localhost:{navigateur_env['front_port']}"


@pytest.fixture
def db_path(tmp_path, monkeypatch):
    path = tmp_path / "job_search.sqlite"
    monkeypatch.setattr(storage_db, "DB_PATH", path)
    monkeypatch.setattr(api_db, "DB_PATH", path)
    conn = sqlite3.connect(path)
    init_db(conn)
    conn.close()
    return path


# ---------------------------------------------------------------------------
# Fixtures DB locales — mêmes conventions que test_exe201_corrections_jet46.py
# ---------------------------------------------------------------------------


def _insert_offer(db_path, offer_id, retenue=True):
    conn = sqlite3.connect(db_path)
    try:
        conn.execute(
            "INSERT INTO offers (id, source, source_id, fingerprint, title, "
            "description_raw, hors_perimetre_reason) VALUES (?, 'test', ?, 'fp', ?, "
            "'Texte de l offre', ?)",
            (offer_id, str(offer_id), f"Poste de test {offer_id}", None),
        )
        if retenue:
            suivi_storage.appliquer_geste(
                conn, offer_id, suivi_etats.RETENIR, effet_at=_now()
            )
        conn.commit()
    finally:
        conn.close()


def _insert_offer_hors_perimetre(db_path, offer_id):
    conn = sqlite3.connect(db_path)
    try:
        conn.execute(
            "INSERT INTO offers (id, source, source_id, fingerprint, title, "
            "description_raw, hors_perimetre_reason) VALUES (?, 'test', ?, 'fp', ?, "
            "'Texte de l offre', 'no_tech')",
            (offer_id, str(offer_id), f"Poste hors périmètre {offer_id}"),
        )
        suivi_storage.appliquer_geste(
            conn, offer_id, suivi_etats.RETENIR, effet_at=_now()
        )
        conn.commit()
    finally:
        conn.close()


def _insert_fiche(db_path, offer_id, statut="done", error_message=None):
    conn = sqlite3.connect(db_path)
    try:
        conn.execute(
            "INSERT INTO fiches_entreprise (offer_id, statut, presentation, "
            "points_json, error_message, created_at) VALUES (?, ?, 'Présentation', "
            "'[]', ?, ?)",
            (offer_id, statut, error_message, _now()),
        )
        conn.commit()
    finally:
        conn.close()


def _insert_lettre(
    db_path,
    offer_id,
    statut="aucune",
    decision="a_decider",
    marque_pret_at=None,
    regeneration_en_cours=0,
    error_message=None,
    texte="Texte de la lettre de test.",
):
    conn = sqlite3.connect(db_path)
    try:
        conn.execute(
            "INSERT INTO lettres (offer_id, statut, decision, marque_pret_at, "
            "regeneration_en_cours, error_message, texte, created_at) VALUES "
            "(?, ?, ?, ?, ?, ?, ?, ?)",
            (
                offer_id,
                statut,
                decision,
                marque_pret_at,
                regeneration_en_cours,
                error_message,
                texte,
                _now(),
            ),
        )
        conn.commit()
    finally:
        conn.close()


def _historique_longueur(db_path, offer_id) -> int:
    conn = sqlite3.connect(db_path)
    try:
        return conn.execute(
            "SELECT COUNT(*) FROM historique_gestes WHERE offer_id = ?",
            (offer_id,),
        ).fetchone()[0]
    finally:
        conn.close()


def _running_add(offer_id: int):
    import api.lettre as api_lettre

    api_lettre._running.add(offer_id)


def _running_discard(offer_id: int):
    import api.lettre as api_lettre

    api_lettre._running.discard(offer_id)


def _open_onglet_lettre(page):
    """Ouvre la carte Lettre — si la lettre est déjà générée (`statut`
    'done'), le premier clic ouvre l'aperçu plein écran (EXE-129) : il faut
    alors cliquer Modifier pour atteindre les sections de la carte. Chaque
    étape attend son résultat (`expect`, qui réessaie) au lieu d'un
    `.count()`/`.is_visible()` immédiat — sans ça, un clic qui a bien eu
    lieu mais dont le re-rendu Vue n'est pas encore commis se lit comme
    « rien n'est affiché » (constaté ici, source de faux rouges). Le repos
    réseau attend aussi `chargerLettre()` : cliquer avant qu'elle ne réponde
    fait ouvrir l'onglet au lieu de l'aperçu pour une lettre déjà générée
    (constaté ici)."""
    page.wait_for_load_state("networkidle")
    page.get_by_text("Lettre de motivation", exact=True).first.click()
    modifier = page.get_by_role("button", name="Modifier")
    onglet = _onglet(page)
    # `.first` : une fois l'aperçu ouvert, Modifier et le conteneur `onglet`
    # (mêmes classes que l'aperçu) sont tous deux visibles — `.or_()` seul
    # viole le mode strict (2 éléments).
    expect(modifier.or_(onglet).first).to_be_visible()
    if modifier.is_visible():
        modifier.click()
        expect(onglet).to_be_visible()


def _badge_lettre(page):
    # Le titre de la carte existe deux fois une fois l'onglet ouvert (la
    # mini-carte ET le `<h2>` de l'overlay) : `.first` prend la mini-carte,
    # qui précède l'overlay dans le document. `.font-medium` écarte le
    # switch Prêt/pas prêt (PieceReadyToggle), lui aussi `rounded-full`,
    # mais sans cette classe.
    titre = page.get_by_text("Lettre de motivation", exact=True).first
    ligne = titre.locator("xpath=ancestor::div[contains(@class,'justify-between')][1]")
    return ligne.locator("span.rounded-full.font-medium")


def _onglet(page):
    """Panneau plein écran de la carte Lettre (overlay `activeCard`) — portée
    des assertions « pas d'éditeur » : la colonne de gauche porte son propre
    bouton « Enregistrer » (URL employeur), sans lien avec la lettre."""
    return page.locator(".fixed.inset-0.z-50")


def _assert_pas_editeur_ni_regenerer(page):
    onglet = _onglet(page)
    assert onglet.get_by_role("button", name="Enregistrer", exact=True).count() == 0
    assert onglet.get_by_role("button", name="Régénérer", exact=True).count() == 0


# ---------------------------------------------------------------------------
# Critère 1 — lettre en erreur après une génération ratée
# ---------------------------------------------------------------------------


class TestCritere1LettreEnErreurApresGeneration:
    def test_onglet_affiche_en_erreur_message_et_generer_sans_editeur(
        self, page, front_url, db_path
    ):
        offer_id = 2001
        _insert_offer(db_path, offer_id)
        _insert_fiche(db_path, offer_id, statut="done")
        _insert_lettre(
            db_path,
            offer_id,
            statut="error",
            decision="demandee",
            error_message="Un message de test.",
        )

        page.goto(f"{front_url}/offers/{offer_id}")
        _open_onglet_lettre(page)

        assert page.get_by_text("En erreur", exact=True).count() == 1
        assert page.get_by_text("Un message de test.", exact=True).count() == 1
        generer = page.get_by_role("button", name="Générer la lettre")
        assert generer.count() == 1
        assert generer.is_enabled()
        _assert_pas_editeur_ni_regenerer(page)
        assert _badge_lettre(page).inner_text() == "Erreur"


# ---------------------------------------------------------------------------
# Critère 2 — lettre orpheline (API redémarrée en cours de génération)
# ---------------------------------------------------------------------------


class TestCritere2LettreOrpheline:
    def test_onglet_affiche_en_erreur_interrompue_avec_generer(
        self, page, front_url, db_path
    ):
        offer_id = 2002
        _insert_offer(db_path, offer_id)
        _insert_fiche(db_path, offer_id, statut="done")
        _insert_lettre(db_path, offer_id, statut="pending", decision="demandee")

        page.goto(f"{front_url}/offers/{offer_id}")
        _open_onglet_lettre(page)

        assert page.get_by_text("En erreur", exact=True).count() == 1
        assert (
            page.get_by_text(
                "Génération interrompue (API redémarrée). Relancer la lettre.",
                exact=True,
            ).count()
            == 1
        )
        generer = page.get_by_role("button", name="Générer la lettre")
        assert generer.count() == 1
        assert generer.is_enabled()
        _assert_pas_editeur_ni_regenerer(page)


# ---------------------------------------------------------------------------
# Critère 3 — Générer la lettre relance depuis l'erreur, sans rechargement
# ---------------------------------------------------------------------------


class TestCritere3GenererRelanceSansRechargement:
    def test_clic_generer_depuis_en_erreur_passe_en_generation(
        self, page, front_url, db_path, monkeypatch
    ):
        import orchestrator.job_search.lettre.service as lettre_service
        from orchestrator.job_search.lettre.boucle import (
            GENERIQUE_ID,
            RAISON_RIEN_A_REDIRE,
            Jugement,
            ResultatBoucle,
        )

        def _resultat_lent(*_a, **_k) -> ResultatBoucle:
            # Un petit délai (thread à part, H2) pour laisser le temps à
            # l'assertion ci-dessous d'observer « en génération » avant que
            # la génération simulée ne se termine.
            time.sleep(1)
            texte = "Voici ma lettre de motivation."
            lettre = {
                "texte": texte,
                "nb_mots": len(texte.split()),
                "tournures_signalees": [],
                "jugement": Jugement(
                    rien_a_redire=True,
                    ressenti="bien",
                    details="d",
                    reussites="r",
                    verdict="v",
                ),
                "releve_redaction": {"tournures": [], "lieux": [], "affirmations": []},
                "releve_correction": None,
            }
            return ResultatBoucle(
                fait_retenu=GENERIQUE_ID,
                texte_type_id="tt",
                lettres=[lettre],
                nb_tours=1,
                raison_fin=RAISON_RIEN_A_REDIRE,
                appels=[],
            )

        monkeypatch.setattr(
            lettre_service, "generer_lettre_depuis_donnees", _resultat_lent
        )

        offer_id = 2003
        _insert_offer(db_path, offer_id)
        _insert_fiche(db_path, offer_id, statut="done")
        _insert_lettre(
            db_path,
            offer_id,
            statut="error",
            decision="demandee",
            error_message="Un message de test.",
        )

        page.goto(f"{front_url}/offers/{offer_id}")
        _open_onglet_lettre(page)
        page.get_by_role("button", name="Générer la lettre").click()

        # La transition passe par `chargerPieces()` (fetch asynchrone) :
        # `expect` réessaie jusqu'au délai, `.click()` seul ne l'attend pas.
        expect(page.get_by_text("Génération en cours…", exact=True)).to_be_visible()
        assert page.get_by_text("En erreur", exact=True).count() == 0
        assert f"/offers/{offer_id}" in page.url


# ---------------------------------------------------------------------------
# Critère 4 — chacun des sept états a sa section propre, mini-carte cohérente
# ---------------------------------------------------------------------------


class TestCritere4SeptEtatsSectionPropreEtMiniCarteCoherente:
    def test_a_decider(self, page, front_url, db_path):
        offer_id = 2010
        _insert_offer(db_path, offer_id)

        page.goto(f"{front_url}/offers/{offer_id}")
        _open_onglet_lettre(page)

        assert page.get_by_role("button", name="Générer la lettre").count() == 1
        assert (
            page.get_by_text("Sans lettre pour cette annonce.", exact=True).count() == 0
        )
        assert page.get_by_text("En erreur", exact=True).count() == 0
        assert _badge_lettre(page).inner_text() == "à produire"

    def test_demandee(self, page, front_url, db_path):
        offer_id = 2011
        _insert_offer(db_path, offer_id)
        _insert_fiche(db_path, offer_id, statut="pending")
        _insert_lettre(db_path, offer_id, statut="aucune", decision="demandee")

        page.goto(f"{front_url}/offers/{offer_id}")
        _open_onglet_lettre(page)

        assert (
            page.get_by_text(
                "La lettre partira dès que la fiche entreprise sera terminée.",
                exact=True,
            ).count()
            == 1
        )
        assert _badge_lettre(page).inner_text() == "en attente"

    def test_en_generation(self, page, front_url, db_path):
        offer_id = 2012
        _insert_offer(db_path, offer_id)
        _insert_fiche(db_path, offer_id, statut="done")
        _insert_lettre(db_path, offer_id, statut="pending", decision="demandee")
        _running_add(offer_id)
        try:
            page.goto(f"{front_url}/offers/{offer_id}")
            _open_onglet_lettre(page)

            assert page.get_by_text("Génération en cours…", exact=True).count() == 1
            assert page.get_by_role("button", name="Générer la lettre").count() == 0
            assert _badge_lettre(page).inner_text() == "Génération…"
        finally:
            _running_discard(offer_id)

    def test_generee(self, page, front_url, db_path):
        offer_id = 2013
        _insert_offer(db_path, offer_id)
        _insert_fiche(db_path, offer_id, statut="done")
        _insert_lettre(db_path, offer_id, statut="done", decision="demandee")

        page.goto(f"{front_url}/offers/{offer_id}")
        _open_onglet_lettre(page)

        assert (
            _onglet(page).get_by_role("button", name="Enregistrer", exact=True).count()
            == 1
        )
        assert (
            page.get_by_text(
                "La lettre partira dès que la fiche entreprise sera terminée.",
                exact=True,
            ).count()
            == 0
        )
        assert page.get_by_text("En erreur", exact=True).count() == 0
        assert _badge_lettre(page).inner_text() == "en cours"

    def test_prete(self, page, front_url, db_path):
        offer_id = 2014
        _insert_offer(db_path, offer_id)
        _insert_fiche(db_path, offer_id, statut="done")
        _insert_lettre(
            db_path,
            offer_id,
            statut="done",
            decision="demandee",
            marque_pret_at=_now(),
        )

        page.goto(f"{front_url}/offers/{offer_id}")
        _open_onglet_lettre(page)

        assert (
            _onglet(page).get_by_role("button", name="Enregistrer", exact=True).count()
            == 1
        )
        assert _badge_lettre(page).inner_text() == "prête"

    def test_sans_lettre(self, page, front_url, db_path):
        offer_id = 2015
        _insert_offer(db_path, offer_id)
        _insert_lettre(db_path, offer_id, statut="aucune", decision="sans_lettre")

        page.goto(f"{front_url}/offers/{offer_id}")
        _open_onglet_lettre(page)

        assert (
            page.get_by_text("Sans lettre pour cette annonce.", exact=True).count() == 1
        )
        assert page.get_by_role("button", name="Revenir sur ce choix").count() == 1
        assert _badge_lettre(page).inner_text() == "Sans lettre"

    def test_en_erreur(self, page, front_url, db_path):
        offer_id = 2016
        _insert_offer(db_path, offer_id)
        _insert_fiche(db_path, offer_id, statut="done")
        _insert_lettre(
            db_path,
            offer_id,
            statut="error",
            decision="demandee",
            error_message="Boum.",
        )

        page.goto(f"{front_url}/offers/{offer_id}")
        _open_onglet_lettre(page)

        assert page.get_by_text("En erreur", exact=True).count() == 1
        assert _badge_lettre(page).inner_text() == "Erreur"


# ---------------------------------------------------------------------------
# Critère 5 — l'annulation d'en-tête remet « Envoyée le » à jour
# ---------------------------------------------------------------------------


class TestCritere5AnnulationEnTeteRemetBlocEnvoiAJour:
    def test_annuler_dernier_geste_retire_envoyee_le_sans_reload(
        self, page, front_url, db_path
    ):
        offer_id = 2005
        _insert_offer(db_path, offer_id)
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        try:
            suivi_storage.appliquer_geste(
                conn, offer_id, suivi_etats.MARQUER_ENVOYEE, effet_at=_now()
            )
        finally:
            conn.close()

        page.goto(f"{front_url}/offers/{offer_id}")

        # `onMounted` charge l'offre et les pièces de façon asynchrone :
        # `expect` réessaie jusqu'au délai (élargi ici, chargement initial
        # plus lourd que les transitions suivantes), `.count()` seul lirait
        # avant que le premier rendu n'arrive.
        expect(page.get_by_text(re.compile(r"^Envoyée le "))).to_be_visible(
            timeout=15000
        )
        bouton_annuler = page.locator("header").get_by_role(
            "button", name=re.compile(r"^Annuler ")
        )
        assert bouton_annuler.count() == 1
        bouton_annuler.click()

        expect(page.get_by_role("button", name="Candidature envoyée")).to_be_visible(
            timeout=15000
        )
        assert page.get_by_text(re.compile(r"^Envoyée le ")).count() == 0
        assert f"/offers/{offer_id}" in page.url


# ---------------------------------------------------------------------------
# Critère 7 — un clic sur une revue active la retire, jamais le tri
# ---------------------------------------------------------------------------


class TestCritere7RevueActiveSeRetireSansToucherAuTri:
    def test_clic_revue_active_la_retire(self, page, front_url, db_path):
        offer_id = 2007
        _insert_offer_hors_perimetre(db_path, offer_id)
        conn = sqlite3.connect(db_path)
        try:
            suivi_storage.marquer_revue_hors_perimetre(
                conn, offer_id, "hors_perimetre_ok"
            )
        finally:
            conn.close()
        historique_avant = _historique_longueur(db_path, offer_id)

        page.goto(f"{front_url}/operateur")
        # Attendre le repos réseau (dépendances Vite pré-bundlées au premier
        # chargement d'une route neuve) avant d'interagir : sans ce repos, un
        # clic trop tôt sur l'onglet se fait écraser par le `setView`
        # tardif de l'`onMounted` initial de la page (constaté ici).
        page.wait_for_load_state("networkidle")
        expect(
            page.get_by_text("Aucune offre dans cette vue.", exact=True)
        ).to_be_visible()
        page.get_by_role("button", name="Hors-périmètre").click()
        page.get_by_text(f"Poste hors périmètre {offer_id}", exact=True).click()
        page.get_by_role("button", name="✓ Confirmé HP").click()

        # Le bouton n'est plus actif (classe verte retirée) — la revue est
        # retirée sans que « ✗ Faux positif » ne devienne actif à sa place.
        bouton_confirme = page.get_by_role("button", name="✓ Confirmé HP")
        expect(bouton_confirme).not_to_have_class(re.compile(r"bg-green-50"))

        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        try:
            assert suivi_storage.revue_hors_perimetre(conn, offer_id) is None
            assert suivi_storage.est_retenue(conn, offer_id) is True
        finally:
            conn.close()
        assert _historique_longueur(db_path, offer_id) == historique_avant
