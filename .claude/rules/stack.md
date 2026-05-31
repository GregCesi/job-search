# Stack — détails et contraintes

## Runtime & langage
- **Python** (venv ou uv). Pydantic pour les schémas.
- **FastAPI** — exposition API (run déclenché / consultation), ultérieur. Le run matinal en V1 peut être un simple `run.py` CLI.

## LLM — Ollama local
- Modèle local 7B/8B (réaliste sur la machine). Zéro API payante.
- Scoring via structured output (JSON par critère). Préférer un format JSON strict, température basse.
- **Hypothèse risquée** : stabilité de notation d'un 7B/8B sur critère atomique. Si instable → baisser température, renforcer few-shot, réduire le nombre de critères.

## Embeddings — ChromaDB
- Recapitalise `rag-job-matching`. Base d'offres persistante sur disque.
- Profil ré-embeddé uniquement au changement de hash (cf. architecture.md §2).

## Persistance — SQLite
- 2 tables : `offers`, `verdicts` (cf. IMPLEMENTATION.md). Léger, requêtable, dataset V2-ready.

## Source externe — API France Travail (Offres d'emploi v2)
- **OAuth2** : token à obtenir + rafraîchir. Stocker les credentials hors repo (`.env`, jamais commité).
- Quotas / rate-limits à respecter — ne pas marteler l'API au debug.
- Filtres pull : localisation Strasbourg + rayon, OR full-remote.
- Doc : https://francetravail.io/data/api/offres-emploi (vérifier le schéma au câblage du livrable 2).

## Frontend — Nuxt 3
- Ultérieur. Pas en V1. Le digest V1 est un livrable texte/poussable, pas une UI.
