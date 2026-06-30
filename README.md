# job-search

Run matinal de sourcing et tri automatique d'offres d'emploi : pull France Travail → dédup → scoring LLM explicable → digest + interface de pilotage web.

## Architecture

```
job-search/
├── orchestrator/job_search/   ← CLI run matinal
├── api/                       ← FastAPI (offres + verdicts)
├── web/                       ← Nuxt 4 + Tailwind + Pinia v3
├── data/                      ← SQLite + ChromaDB (partagés)
└── profiles/                  ← profils YAML
```

## Setup

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env  # puis remplir les credentials
```

Credentials nécessaires dans `.env` :
- `FRANCE_TRAVAIL_CLIENT_ID` / `FRANCE_TRAVAIL_CLIENT_SECRET` — [francetravail.io](https://francetravail.io) > Mes applications > API Offres d'emploi v2
- `OLLAMA_HOST` / `OLLAMA_MODEL` — Ollama local (`ollama pull llama3.1:8b`)

## Lancement

### Orchestrateur (run matinal)

Ollama doit tourner avant le run.

```bash
# Run complet (fetch → dédup → score → digest)
python -m orchestrator.job_search.run --profile profiles/gregoire.yaml

# Options
python -m orchestrator.job_search.run --max 100            # nombre max d'offres à fetcher
python -m orchestrator.job_search.run --since-hours 48     # fenêtre du digest (défaut : 24h)
```

### API

```bash
uvicorn api.main:app --reload
# → http://localhost:8000
```

### Interface web

```bash
cd web && npm run dev
# → http://localhost:3000
```

## Profil cible

Éditer `profiles/gregoire.yaml` — le scoring se recalibre automatiquement au prochain run (ré-embed conditionnel au hash du fichier).

## CLI utilitaires

```bash
# Lire une annonce
python -m orchestrator.job_search.view
python -m orchestrator.job_search.view --offer-id 3

# Enregistrer un verdict
python -m orchestrator.job_search.verdict
python -m orchestrator.job_search.verdict --offer-id 3 --status favori
# statuts : favori | rejeté | candidaté

# Rescore (recatégorisation des offres)
python -m orchestrator.job_search.rescore                   # offres sans catégorie uniquement
python -m orchestrator.job_search.rescore --force            # recalcule toutes les offres
python -m orchestrator.job_search.rescore --re-extract       # force ré-extraction LLM
python -m orchestrator.job_search.rescore --dry-run          # affiche sans écrire en base
python -m orchestrator.job_search.rescore --profile profiles/gregoire.yaml  # profil custom
```
