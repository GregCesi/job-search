# job-search-zone-a

## Contexte
Run matinal de sourcing & tri auto d'offres d'emploi : pull France Travail → dédup → scoring LLM explicable offre↔profil → digest. Contrainte forte : scoring **explicable** (score dérivé de critères notés côté code, jamais produit en bloc par le LLM) + sources pluggables + profil cible mutable.

## Stack
Python, FastAPI, Ollama (LLM local), ChromaDB (embeddings), SQLite (persistance), Pydantic. API France Travail Offres v2 (OAuth2). Frontend Nuxt 3 (ultérieur). Zéro API payante.

## Architecture
- IMPLEMENTATION.md (`.claude/state/IMPLEMENTATION.md`) — plan d'exécution, état d'avancement, schémas cibles
- STATE.md (`.claude/state/STATE.md`) — état courant (lecture obligatoire au début de chaque session)
- Rules (`.claude/rules/`) — règles de dev modulaires, lues automatiquement
- Commands (`.claude/commands/`) — `/status`, `/handoff`

## Workflow (rappel — détails dans rules/workflow.md)
- Une étape à la fois, validation explicite avant la suivante
- str_replace ciblé, pas de réécriture
- Pas de préambule, pas de récap final
- Mettre à jour IMPLEMENTATION.md + STATE.md après chaque livrable (cf. rules/update-protocol.md — NON négociable)
