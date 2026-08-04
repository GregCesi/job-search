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

## Journal — écriture dans Notion

Le journal de ce projet vit dans la base Journal de l'espace Notion « Cockpit - IA Engineer ».
Tu y écris. Tu n'y lis jamais : ton état de démarrage reste `.claude/state/STATE.md`.
`state/journal.md` et `state/DECISIONS.md` sont gelés — archives, plus aucune écriture.

### Quand écrire
Une entrée = **un chantier terminé**. Pas une session.
- Chantier étalé sur quatre sessions → une entrée, à la fin.
- Deux chantiers clos le même jour → deux entrées.
- Fin de session en milieu de chantier → aucune entrée, seulement `STATE.md` mis à jour.

### Pour qui
Pour le chat, qui ne lit pas ce repo : ni les fichiers, ni les numéros de phase, ni `git log`.
Trois tests avant d'écrire une ligne :
1. Un lecteur sans le code comprend-il ce qui a changé dans le comportement du système ?
2. `git log` le dit-il déjà ? Si oui, ne l'écris pas.
3. Cette entrée rend-elle fausse une entrée antérieure ? Si oui, dis-le explicitement.

### Ce qu'on tait
Noms de fichiers, numéros de phase, listes de fichiers touchés, comptes de tests,
formulations de commit. Le journal dit ce que le système fait désormais, pas ce que tu as tapé.

### Format du corps — trois sections, dans cet ordre
**## Ce qui change** — le comportement du système avant / après. Obligatoire.
**## Ce que ça révèle** — l'arbitrage rendu et l'alternative écartée, quand il y en a eu un.
  Si l'arbitrage décrit le code et changera avec lui, il va dans `.claude/rules/`, pas ici.
**## Ce que ça invalide** — ce qu'une entrée antérieure affirmait et qui est maintenant faux.
  Omets la section s'il n'y a rien. N'invente jamais son contenu.

### Appel

Utilise `notion-create-pages` avec :

parent: { "data_source_id": "8c11bcb6-13f7-4aab-a3db-63d48cf09412" }

properties:
- "Titre"            — phrase qui dit le changement, pas le sujet.
                       « Le matching techs passe côté back », pas « Chantier matching ».
- "date:Date:start"  — YYYY-MM-DD, jour de clôture du chantier
- "date:Date:is_datetime" — 0
- "Type"             — "Session"
- "Auteur"           — "Claude Code"
- "Projet"           — ["https://app.notion.com/3b2268d8af348137b1f4f7960e55e224"]
- "Résumé"           — 2 lignes max. Doit se suffire en vue liste.
- "Reste à faire"    — une ligne par item, format `- {P0|P1|P2} · {< 1h|Demi-journée|Journée} · {libellé}`
                       séparateur `<br>`. Vide si rien. Chaque ligne doit pouvoir devenir un ticket
                       sans réécriture. Pas de "continuer X".
- "Tickets"          — ne pas renseigner. Le chat rattache.

content: le corps en Markdown, sections ci-dessus. Pas de titre H1 en tête.

