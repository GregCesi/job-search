# job-search

## Contexte
Run matinal de sourcing & tri auto d'offres d'emploi : pull France Travail → dédup → scoring LLM explicable offre↔profil → digest + interface de pilotage. Contrainte forte : scoring **explicable** (score dérivé de critères notés côté code, jamais produit en bloc par le LLM) + sources pluggables + profil cible mutable.

## Stack
Python, FastAPI, Ollama (LLM local), SQLite (persistance), Pydantic. API France Travail Offres v2 (OAuth2). Nuxt 4 + Pinia v3 (frontend livré). Zéro API payante.

## Architecture — 3 briques autour d'une base partagée

```
job-search/
├── orchestrator/job_search/   ← CLI run matinal (fetch → dédup → score → digest)
├── api/                       ← FastAPI (lecture offres, verdicts)
├── web/                       ← Nuxt 4 + Tailwind + Pinia v3 (interface de pilotage)
├── data/                      ← SQLite (partagé orchestrator ↔ api)
└── profiles/                  ← profils YAML (profil cible mutable)
```

- `orchestrator/` et `api/` lisent/écrivent tous deux `data/job_search.sqlite` — chemin absolu résolu depuis la racine du repo dans chaque brique.
- `web/` ne dépend que de l'URL `http://localhost:8000` (api/).

## Où sont les règles

- `.claude/rules/quality-gate.md` — la barre de fin de ticket, passée par `bash scripts/barre.sh`.
- `.claude/rules/workflow.md` — le régime d'exécution : lecture du ticket, points d'arrêt, verdict et entrée Journal.
- Règles d'architecture — `architecture.md`, `pipeline.md`, `scoring.md`, `sources.md`, `stack.md`, `frontend.md`.

Les outils ECC (skills, agents, commandes) sont des moyens. Ils ne remplacent
aucune de ces règles, et une note d'évaluation ECC n'est pas un verdict.

`.claude/state/` (STATE.md, IMPLEMENTATION*.md, DECISIONS.md, JOURNAL.md) est
l'archive du flow précédent, gelée depuis le 28 septembre 2026 (TCK-235) : tu ne
la lis pas pour savoir quoi faire, et tu n'y écris pas. Ce que tu dois produire est
dans ton ticket.

## Ce que tu ne décides pas

Tu décides *comment*, jamais *quoi*. Le périmètre d'un ticket vient du ticket.

Tu n'écris jamais dans `.claude/rules/`, `.claude/settings.json`, `.claude/agents/`,
`.claude/skills/`, `scripts/`, `pyproject.toml`, `requirements-dev.txt`, ni dans ce
fichier. Ce sont la barre contre laquelle tu es jugé et le périmètre dans lequel tu
travailles.

Tu t'arrêtes et tu le dis dans trois cas :
- un objet nommé par ton ticket est absent du terrain ;
- il est présent mais n'est pas de la nature supposée ;
- une prémisse explicite de ton prompt est fausse sur le terrain.
