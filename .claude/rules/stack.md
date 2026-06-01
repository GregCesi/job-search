# Stack — détails et contraintes

## Runtime & langage
- **Python** (venv ou uv). Pydantic pour les schémas.
- **FastAPI** — exposition API (lecture offres, verdicts). Livré dans `api/`. Lancé via `uvicorn api.main:app --reload` (port 8000).

## LLM — Ollama local
- Modèle local 7B/8B (réaliste sur la machine). Zéro API payante.
- Scoring via structured output (JSON par critère). Préférer un format JSON strict, température basse.
- **Hypothèse risquée** : stabilité de notation d'un 7B/8B sur critère atomique. Si instable → baisser température, renforcer few-shot, réduire le nombre de critères.

## Embeddings — ChromaDB
- Recapitalise `rag-job-matching`. Base d'offres persistante sur disque.
- Profil ré-embeddé uniquement au changement de hash (cf. architecture.md §2).

## Persistance — SQLite
- 2 tables : `offers`, `verdicts`. Léger, requêtable, dataset V2-ready.
- Fichier : `data/job_search.sqlite` à la racine du repo, partagé entre `orchestrator/` (écriture) et `api/` (lecture/écriture verdicts). Chaque brique résout le chemin depuis `Path(__file__).parent...` ou depuis le CWD.

## Source externe — API France Travail (Offres d'emploi v2)
- **OAuth2** : token à obtenir + rafraîchir. Stocker les credentials hors repo (`.env`, jamais commité).
- Quotas / rate-limits à respecter — ne pas marteler l'API au debug.
- Filtres pull : localisation Strasbourg + rayon, OR full-remote.
- Doc : https://francetravail.io/data/api/offres-emploi (vérifier le schéma au câblage du livrable 2).

## Frontend — Nuxt 4 + Pinia v3
- Livré dans `web/`. Tailwind CSS, Pinia v3, `@nuxtjs/tailwindcss`.
- API base : `http://localhost:8000` (configurable via `runtimeConfig.public.apiBase` dans `nuxt.config.ts`).
- Lancé via `cd web && npm run dev` (port 3000 par défaut).
