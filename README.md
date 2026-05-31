# job-search-zone-a

Run matinal de sourcing et tri automatique d'offres d'emploi : pull France Travail → dédup → scoring LLM explicable → digest.

Voir [CLAUDE.md](CLAUDE.md) pour l'architecture et les règles de développement.

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

## Usage

```bash
# Run matinal complet (fetch → dédup → score → digest)
python -m job_search.run

# Options
python -m job_search.run --max 100          # nombre max d'offres à fetcher
python -m job_search.run --since-hours 48   # fenêtre du digest (défaut: 24h)
python -m job_search.run --profile profiles/gregoire.yaml  # profil cible

# Lire une annonce avant de juger
python -m job_search.view                   # liste interactive
python -m job_search.view --offer-id 3      # direct par id

# Enregistrer un verdict
python -m job_search.verdict                # interactif
python -m job_search.verdict --offer-id 3 --status favori
# statuts : favori | rejeté | candidaté
```

## Profil cible

Editer `profiles/gregoire.yaml` — le scoring se recalibre automatiquement au prochain run (ré-embed conditionnel au hash du fichier).
