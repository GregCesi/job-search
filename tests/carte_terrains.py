"""Terrains des tests EXE-213 (carte du code) : le vrai dépôt et le dépôt d'essai.

Le vrai dépôt : la carte générée depuis le code du worktree, écrite dans un
dossier temporaire. Le dépôt d'essai : un petit arbre posé dans un dossier
temporaire, avec deux systèmes A (a1, a2) et B (b1, b2). La commande se lance
toujours dans un sous-processus, comme à la main : aucun test n'importe le
code de la commande, et aucun n'écrit sous api/, orchestrator/ ou docs/ du dépôt.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
PAS_DE_PHRASE = "Pas de phrase pour ce fichier."

TEXTES_ESSAI = """\
[[systeme]]
id = "a"
nom = "Système A"
role = "Rôle du système A."
fichiers = ["api/a1.py", "api/a2.py"]

[[systeme]]
id = "b"
nom = "Système B"
role = "Rôle du système B."
fichiers = ["orchestrator/b1.py", "orchestrator/b2.py"]
"""

FICHIERS_ESSAI = {
    "api/__init__.py": "",
    "orchestrator/__init__.py": "",
    "api/a1.py": (
        '"""Première phrase de a1. Seconde phrase de a1."""\n\n'
        "from orchestrator import b1\n\n"
        "VALEUR = b1.VALEUR\n"
    ),
    "api/a2.py": "VALEUR = 2\n",
    "orchestrator/b1.py": '"""Fournit une valeur à a1."""\n\nVALEUR = 1\n',
    "orchestrator/b2.py": (
        '"""Lève une erreur dès qu\'on l\'importe."""\n\n'
        'raise RuntimeError("b2 ne s\'importe pas")\n'
    ),
    "tests/test_a1.py": "import api.a1\n\n\ndef test_a1():\n    assert api.a1\n",
    "docs/carte/textes.toml": TEXTES_ESSAI,
}


def poser_depot_essai(racine: Path) -> Path:
    for rel, contenu in FICHIERS_ESSAI.items():
        chemin = racine / rel
        chemin.parent.mkdir(parents=True, exist_ok=True)
        chemin.write_text(contenu, encoding="utf-8")
    return racine


def lancer_carte(
    racine: Path, sortie: Path | None = None
) -> subprocess.CompletedProcess:
    """Lance `python -m outils.carte` depuis `racine`, comme à la main."""
    cmd = [sys.executable, "-m", "outils.carte"]
    if sortie is not None:
        cmd += ["--sortie", str(sortie)]
    env = dict(os.environ, PYTHONPATH=str(REPO))
    return subprocess.run(
        cmd, cwd=racine, env=env, capture_output=True, text=True, timeout=120
    )


def lire_donnees(page_html: Path) -> dict:
    """Les données que la page embarque, lues dans le fichier écrit."""
    assert page_html.is_file(), f"page absente : {page_html}"
    texte = page_html.read_text(encoding="utf-8")
    trouve = re.search(
        r'<script id="donnees" type="application/json">(.*?)</script>', texte, re.S
    )
    assert trouve, "la page n'embarque pas ses données"
    return json.loads(trouve.group(1))


def fichiers_du_disque(racine: Path) -> list[str]:
    """Fichiers Python de api/ et orchestrator/, sans les `__init__.py` vides
    (aucune ligne autre que vide ou commentaire)."""
    trouves = []
    for dossier in ("api", "orchestrator"):
        for p in sorted((racine / dossier).rglob("*.py")):
            if "__pycache__" in p.parts:
                continue
            if p.name == "__init__.py":
                lignes = [
                    ligne
                    for ligne in p.read_text(encoding="utf-8").splitlines()
                    if ligne.strip() and not ligne.strip().startswith("#")
                ]
                if not lignes:
                    continue
            trouves.append(p.relative_to(racine).as_posix())
    return sorted(trouves)


# ── Dépôt d'essai étendu (EXE-214) : la chaîne de l'écran à la table ──────────
#
# Le dépôt d'essai d'EXE-213 reste tel quel pour ses tests ; celui-ci lui ajoute
# une table `choses`, ses routes, ses lectures et écritures, et un front.

TEXTES_ESSAI_ETENDU = TEXTES_ESSAI.replace(
    'fichiers = ["api/a1.py", "api/a2.py"]',
    'fichiers = ["api/a1.py", "api/a2.py", "api/choses.py", '
    '"orchestrator/a_metier.py", "orchestrator/storage/choses.py"]',
).replace(
    'fichiers = ["orchestrator/b1.py", "orchestrator/b2.py"]',
    'fichiers = ["orchestrator/b1.py", "orchestrator/b2.py", '
    '"orchestrator/b_choses.py"]',
) + (
    "\n[phrases]\n"
    '"web/app/pages/choses.vue" = "Affiche les choses."\n'
    '"web/app/stores/choses.ts" = "Charge une chose depuis l\'API."\n'
    '"web/app/components/ChoseCarte.vue" = "Montre une chose."\n'
    '"web/app/components/ChoseSuite.vue" = "Demande la suite d\'une chose."\n'
)

FICHIERS_ESSAI_ETENDU = {
    **FICHIERS_ESSAI,
    "docs/carte/textes.toml": TEXTES_ESSAI_ETENDU,
    "api/choses.py": (
        '"""Routes des choses."""\n\n'
        "from fastapi import APIRouter\n\n"
        "from orchestrator import a_metier\n\n"
        'router = APIRouter(prefix="/choses")\n\n\n'
        '@router.get("/{chose_id}")\n'
        "def lire_chose(chose_id: int):\n"
        "    return a_metier.lire(chose_id)\n\n\n"
        '@router.delete("/{chose_id}")\n'
        "def supprimer_chose(chose_id: int, conn=None):\n"
        '    conn.execute("DELETE FROM choses WHERE id = ?", (chose_id,))\n'
    ),
    "orchestrator/a_metier.py": (
        '"""Règle des choses."""\n\n\n'
        "def lire(chose_id, conn=None):\n"
        "    return conn.execute(\n"
        '        "SELECT nom FROM choses WHERE id = ?", (chose_id,)\n'
        "    ).fetchone()\n"
    ),
    "orchestrator/storage/__init__.py": "",
    "orchestrator/storage/choses.py": (
        '"""Stockage des choses."""\n\n\n'
        "def creer(conn):\n"
        '    conn.execute("CREATE TABLE IF NOT EXISTS choses (id INTEGER, nom TEXT)")\n'
        "\n\n"
        "def ajouter(conn, nom):\n"
        '    conn.execute("INSERT INTO choses (nom) VALUES (?)", (nom,))\n'
    ),
    "orchestrator/b_choses.py": (
        '"""Renomme les choses."""\n\n\n'
        "def renommer(conn, nom):\n"
        '    conn.execute("UPDATE choses SET nom = ?", (nom,))\n'
        "\n\n"
        "def tout_lire(conn, nom_de_table):\n"
        '    return conn.execute(f"SELECT * FROM {nom_de_table}").fetchall()\n'
    ),
    "web/app/pages/choses.vue": (
        "<template>\n"
        "  <div>\n"
        "    <ChoseCarte />\n"
        "  </div>\n"
        "</template>\n\n"
        '<script setup lang="ts">\n'
        "import { useChosesStore } from '~/stores/choses'\n\n"
        "const choses = useChosesStore()\n"
        "</script>\n"
    ),
    "web/app/stores/choses.ts": (
        "import { defineStore } from 'pinia'\n\n"
        "export const useChosesStore = defineStore('choses', () => {\n"
        "  const base = useRuntimeConfig().public.apiBase\n"
        "  async function charger(id: number) {\n"
        "    return await $fetch(`${base}/choses/${id}`)\n"
        "  }\n"
        "  return { charger }\n"
        "})\n"
    ),
    "web/app/components/ChoseCarte.vue": (
        "<template>\n"
        "  <p>Une chose</p>\n"
        "</template>\n\n"
        '<script setup lang="ts">\n'
        "const config = useRuntimeConfig()\n"
        "const base = config.public.apiBase\n"
        "async function charger() {\n"
        "  return await $fetch(`${base}/inconnu`)\n"
        "}\n"
        "</script>\n"
    ),
    "web/app/components/ChoseSuite.vue": (
        "<template>\n"
        "  <p>La suite</p>\n"
        "</template>\n\n"
        '<script setup lang="ts">\n'
        "const props = defineProps<{ adresse: string }>()\n"
        "async function suite() {\n"
        "  return await $fetch(`${props.adresse}/suite`, { method: 'POST' })\n"
        "}\n"
        "</script>\n"
    ),
}


def poser_depot_essai_etendu(racine: Path) -> Path:
    for rel, contenu in FICHIERS_ESSAI_ETENDU.items():
        chemin = racine / rel
        chemin.parent.mkdir(parents=True, exist_ok=True)
        chemin.write_text(contenu, encoding="utf-8")
    return racine


def fichiers_front_du_disque(racine: Path) -> list[str]:
    """Fichiers .vue et .ts de web/app/, hors node_modules et .nuxt."""
    trouves = []
    for p in sorted((racine / "web" / "app").rglob("*")):
        parts = p.relative_to(racine).parts
        if p.suffix not in (".vue", ".ts") or not p.is_file():
            continue
        if "node_modules" in parts or ".nuxt" in parts:
            continue
        trouves.append(p.relative_to(racine).as_posix())
    return sorted(trouves)
