"""Chemins canoniques du projet — source unique.

REPO_ROOT ancré sur __file__ (orchestrator/job_search/paths.py → repo/).
Tous les modules qui ont besoin d'un chemin vers data/, profiles/, etc.
importent depuis ici au lieu de recalculer localement.
"""

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent

DB_PATH = REPO_ROOT / "data" / "job_search.sqlite"
TRACES_PATH = REPO_ROOT / "data" / "traces" / "extract_facts.jsonl"
# Appel d'identification d'une offre ajoutée à la main sans titre (EXE-82), à part des
# traces d'extraction : le viewer de traces ne lit que des faits extraits.
IDENTIFICATION_TRACES_PATH = REPO_ROOT / "data" / "traces" / "identify_offer.jsonl"
CV_REFERENCE_PATH = REPO_ROOT / "data" / "cv" / "cv_reference.html"
PROFILE_PATH = REPO_ROOT / "profiles" / "gregoire.yaml"
VUE_CANDIDAT_PATH = REPO_ROOT / "profiles" / "vue_candidat.yaml"
ALIAS_PATH = REPO_ROOT / "profiles" / "alias.yaml"
INTERMEDIAIRES_PATH = REPO_ROOT / "profiles" / "intermediaires.yaml"
FICHE_COMMAND_PATH = REPO_ROOT / ".claude" / "commands" / "fiche-entreprise.md"
# cwd stable des sessions Claude Agent SDK de la fiche entreprise : `resume` retrouve une session
# par son répertoire de travail, run_fiche et la route explain doivent donc partager le même.
FICHE_CWD = Path.home() / ".cache" / "job-search" / "fiche_cwd"
# cwd dédié à la génération de CV (EXE-58) : pas de `resume` ici (un seul appel, pas de suite),
# mais un répertoire propre évite de mêler ses sessions à celles de la fiche entreprise.
CV_CWD = Path.home() / ".cache" / "job-search" / "cv_cwd"
# Fichiers de la lettre de motivation (EXE-65) : hors git comme tout data/, posés à part
# (H3 du ticket). Aucun `resume` ici non plus : un seul appel par génération.
LETTRE_PREFERENCES_PATH = REPO_ROOT / "data" / "lettre" / "preferences_ton.md"
LETTRE_TOURNURES_PATH = REPO_ROOT / "data" / "lettre" / "tournures_interdites.txt"
LETTRE_CWD = Path.home() / ".cache" / "job-search" / "lettre_cwd"
# Coordonnées du candidat pour les PDF CV/lettre (EXE-102, H4) : hors git, posées à
# part comme les autres fichiers de data/lettre/.
COORDONNEES_PATH = REPO_ROOT / "data" / "lettre" / "coordonnees.txt"
