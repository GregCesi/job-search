# IMPLEMENTATION — Remédiation code mort (ChromaDB, purge, view)

## Vue d'ensemble

Suppression du code mort résiduel d'une architecture antérieure (matching par embeddings ChromaDB, remplacé par scoring déterministe Python). Aucun changement de comportement du pipeline — uniquement des suppressions d'étapes mortes et de dépendances inutilisées. Première chose à attaquer : le bloc ChromaDB (le plus gros, le plus de fichiers touchés).

Périmètre gelé : toute découverte annexe va dans le registre de dette (L9), pas dans cette session.

## Phases

### Phase 1 — Suppressions code mort (L1–L8)

- [x] **L1** — Supprimer `orchestrator/job_search/matching/embedder.py` (fichier entier). Le dossier `matching/` conserve `__init__.py` et `profile.py`. **XS**

- [x] **L2** — Nettoyer `run.py` : retirer l'import `Embedder` (ligne 27), l'instanciation + `embed_profile` (lignes 61-63), l'appel `embedder.add_offer(offer)` (ligne 100). Renumérotation des commentaires d'étapes si nécessaire. **S**

- [x] **L3** — Retirer `chromadb>=0.5` de `requirements.txt`. **XS**

- [x] **L4** — Supprimer `data/chroma/` et `data/profile_cache.json`. Vérifier `.gitignore` : l'entrée `chroma/` peut rester (gardien passif) ou partir — au choix, pas bloquant. **XS**

- [x] **L5** — Supprimer `insert_stub()` dans `storage/dedup.py` (lignes 29-51) + l'import `JobOffer` s'il devient orphelin. Garder `filter_new()`. **XS**

- [x] **L6** — Supprimer `storage/purge.py` (fichier entier — ne contient que le no-op `purge_irrelevant()`). **XS**

- [x] **L7** — Retirer les 2 appels `purge_irrelevant` : import + appel dans `run.py` (lignes 43, 133-136), import + appel dans `rescore.py` (lignes 37, 179-181). Retirer les lignes de log associées (`{purged} offres purgées`). **S**

- [x] **L8** — Supprimer `orchestrator/job_search/view.py` (fichier entier). Retirer la référence dans `CODEMAP.md:217`. Retirer aussi la ligne `purge.py` dans `CODEMAP.md:221`. **XS**

✋ Verify before continuing:
- [x] `pytest` : 136 passed, 1 failed (pré-existant — alias outils_dev_ia, commit 72628db)
- [x] `python -m orchestrator.job_search.run` : import OK (run complet requiert Ollama + API FT)
- [x] `python -m orchestrator.job_search.rescore --dry-run` : sans erreur, 0 appel LLM ✓
- [x] `grep -rn "embedder\|chroma\|sentence_transformers\|insert_stub\|purge_irrelevant" --include="*.py" orchestrator/ api/` : zéro occurrence ✓

### Phase 2 — Registre de dette (L9)

- [x] **L9** — Ajouter dans `DECISIONS.md` une section « Dette acceptée — remédiation 2026-07-14 » avec 3 entrées datées : (1) distance 30 km hardcodée (`france_travail.py`) — réveil : besoin >30 km ; (2) seuils catégorie 50/40 hardcodés (`categorize.py`) — réveil : recalibrage des catégories ; (3) chantier persistance/exposition API (dérivés recalculés, GET effet de bord seen, workflow human_reviews orphelin, bugs export/filtres) — réveil : vague 4. **XS**

✋ Verify before continuing:
- [x] Les 3 entrées sont datées et chaque entrée a son déclencheur de réveil ✓
- [x] `grep` : toujours zéro occurrence ✓

## Livrables détaillés

1. **L1** — Suppression `embedder.py` — done : fichier absent, `matching/` garde `profile.py` — **XS**
2. **L2** — Nettoyage `run.py` (Embedder) — done : aucune référence `embedder`/`Embedder`/`embed_profile`/`add_offer` dans `run.py` — **S**
3. **L3** — Retrait dep `chromadb` — done : absent de `requirements.txt` — **XS**
4. **L4** — Suppression `data/chroma/` + `data/profile_cache.json` — done : absents du filesystem — **XS**
5. **L5** — Suppression `insert_stub()` — done : absent de `dedup.py`, `filter_new()` intact — **XS**
6. **L6** — Suppression `purge.py` — done : fichier absent — **XS**
7. **L7** — Retrait appels `purge_irrelevant` — done : 0 occurrence dans `run.py` et `rescore.py` — **S**
8. **L8** — Suppression `view.py` + refs — done : fichier absent, CODEMAP.md nettoyé — **XS**
9. **L9** — 3 entrées dette dans `DECISIONS.md` — done : section présente avec déclencheurs — **XS**

## Garde-fous

- Si un grep post-suppression trouve une référence résiduelle (`embedder`, `chroma`, `insert_stub`, `purge_irrelevant`) dans du code Python (hors CARTE.md, hors `.venv`) → ne pas conclure, traquer et supprimer l'import/appel.
- Si `run --max 5` échoue sur un import manquant → la suppression a cassé une dépendance non cartographiée. Lire le traceback, corriger l'import, ne pas ajouter de fonctionnalité.
