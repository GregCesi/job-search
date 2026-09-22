"""Chemins canoniques du projet — source unique.

REPO_ROOT ancré sur __file__ (orchestrator/job_search/paths.py → repo/).
Tous les modules qui ont besoin d'un chemin vers data/, profiles/, etc.
importent depuis ici au lieu de recalculer localement.
"""
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent

DB_PATH = REPO_ROOT / "data" / "job_search.sqlite"
TRACES_PATH = REPO_ROOT / "data" / "traces" / "extract_facts.jsonl"
PROFILE_PATH = REPO_ROOT / "profiles" / "gregoire.yaml"
VUE_CANDIDAT_PATH = REPO_ROOT / "profiles" / "vue_candidat.yaml"
ALIAS_PATH = REPO_ROOT / "profiles" / "alias.yaml"
