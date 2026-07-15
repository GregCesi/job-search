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

## Docs .claude/
- STATE.md (`.claude/state/STATE.md`) — état courant (lecture obligatoire au début de chaque session)
- IMPLEMENTATION-*.md (`.claude/state/`) — plans d'exécution par chantier, état d'avancement
- CODEMAP.md (`.claude/docs/CODEMAP.md`) — carte de retrieval du code (régénérable)
- Rules (`.claude/rules/`) — règles de dev modulaires, lues automatiquement
- Commands (`.claude/commands/`) — `/status`, `/handoff`

## Workflow (rappel — détails dans rules/workflow.md)
- Une étape à la fois, validation explicite avant la suivante
- str_replace ciblé, pas de réécriture
- Pas de préambule, pas de récap final
- Mettre à jour IMPLEMENTATION.md + STATE.md après chaque livrable (cf. rules/update-protocol.md — NON négociable)
