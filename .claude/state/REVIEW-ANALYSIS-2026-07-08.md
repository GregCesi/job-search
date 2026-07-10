# Analyse de review — 48 offres annotées (2026-07-08)

Corpus : 48 offres catégorisées parfait/rêve/atteignable/hors, annotées manuellement avec remarques de correction.

---

## Taxonomie des erreurs — 7 buckets

### P — Profil incomplet (~14 mentions)
Compétences maîtrisées absentes de `gregoire.yaml`, écrasent l'atteignabilité.

Offres impactées :
- Consultant IA Générative (parfait, att=38) — json, rest manquants
- Reflet digital ×2 (parfait, att=12/9) — zapier, make, chatgpt, claudia (aussi alias)
- Data manager Plus que Pro (rêve) — ci_cd léger
- QuadCode Python Backend (rêve, att=27) — postgresql
- Développeur Java CDI (att=49) — postgresql
- Quinncia Frontend (att=40) — css, js, ts, react, nextjs → "le profil est faux"
- Développeur C# .NET (att=4) — csharp, .net, angular
- Full Stack .NET (att=36) — c#, .net
- FRONT END Mercato (att=43) — tailwind, vite, bootstrap, php
- Alternance Data Analyst Nexa — excel, csharp, make, zapier
- Spécialiste évaluation IA / AI Voice Trainer — français natif non reconnu

**Techs à ajouter** (~19) : `json`, `rest`, `postgresql`, `excel`, `css`, `javascript`, `typescript`, `react`, `nextjs`, `csharp`/`.net`, `angular`, `tailwind`, `vite`, `bootstrap`, `php`, `ci_cd` (léger), `french` (natif), `agile`.

### A — Alias / normalisation (~11 mentions)
La compétence existe mais le scoring ne la reconnaît pas.

| Extraction | Devrait mapper vers |
|---|---|
| `graph` | `langgraph` |
| `zapier`, `make` | famille automatisation (`n8n`) |
| `chatgpt`, `claudia` | outils LLM / assistants IA |
| `net` vs `.net` | Même tech, deux formes |
| `c#` vs `csharp` | Même tech |
| `large_language_models` | `llm` |
| `claude_code`, `cursor`, `codex` | outils dev IA |
| `ci/cd` vs `ci_cd` | Normalisation slash/underscore |
| `ia`, `ai` | **PAS une tech** — terme de niveau domaine, exclure du matching tech |

### G — Gates éliminatoires absents (~12 offres)
Critères binaires traités comme des techs pondérées au lieu d'être éliminatoires.

**Langues :**
- Lightcast — `portuguese` requis
- QuadCode AI Skills (parfait, 93/50) — "Russian Native" → **faux positif critique, non détecté même en review manuelle**
- QuadCode Python (rêve, 80/27) — "Fluent Russian C2"
- TELUS — résidence Canada 5 ans

**Contrat :**
- Alternances ×4 : Achenheim, Nexa ×2, Socomec
- Stages ×2 : Helci (non rémunéré), Sightengine (internship)

### D — Domaine miscalibré (~9 offres)
`data_science` a un gradient de désirabilité trop haut et le domaine est trop hétérogène.

Offres : Data Ingénieur ETL Sopra (dés=70), Alternance Data visu (dés=70), BIO-INFO Inserm (dés=63), Concepteur BI (dés=70), Senior DS Lemon.io (dés=63), CapsLock ×2 (dés=58), ANALYSTE BI (dés=70), Inserm Bioinfo (dés=63).

Remarque récurrente : "data_science IA" vs "BI/bioinfo" n'ont pas la même désirabilité. Impact modéré — ces offres finissent en `hors`, c'est du bruit de ranking.

### X — Extraction bruitée (~7 offres)
Désirabilité=100 systématique quand extraction pauvre + domaine ai_engineering.

| Offre | dés/att | Techs extraites | Problème |
|---|---|---|---|
| EverAI | 100/0 | ai, video editing... | Domaine mal classé (montage vidéo) |
| NVIDIA | 100/0 | c, cpp, cuda... | 100 car domaine=ai_engineering, 0 recouvrement |
| Neuronaix | 100/0 | ia, robotique | Extraction quasi vide |
| Helci | 100/0 | ia, marketing digital | Stage non rémunéré à dés=100 |
| Dév IA alternance | 100/0 | ia | 1 seule "tech" |
| LawnStarter | 0/0 | ai, claude_code... | Tout cassé |
| Plus que Pro ×3 | variable | Rôles lead/ic/lead | Doublons, extraction non déterministe |

**Mécanisme** : la désirabilité sature à 100 au lieu de s'abstenir quand <N techs extraites.

### R — Taxonomie rôle (4 offres)
- EURO INFORMATION — `lead` mais management pur
- Bitschhoffen — "référent IA, piloter la brique IA" ≠ `ic`
- LawnStarter — lead d'agents IA ≠ lead humain
- Neuronaix — "Technical Advisor" ≠ `ic`

### S — Seuils de catégorie (4 offres)
- SFEIR (rêve, att=29) — limite rêve/parfait
- QuadCode Python (rêve, att=27) — limite rêve/parfait
- Data Engineer Mercato (rêve, att=41) — senior devrait le mettre en rêve
- Sightengine (rêve, dés=90) — impossible à classer rêve/hors

---

## Distinction architecturale des leviers

Invariant §4 (zéro LLM au rescore) coupe les leviers en deux :

**Rescore-only** (Python + yaml, gratuit) :
- P — édition `gregoire.yaml`
- A — table d'alias côté scoring (sur strings stockées, pas à l'ingestion)
- G-langues — gate déterministe (langues déjà extraites comme techs)
- G-contrat — gate alternance/stage (champ contrat + titre)
- D — baisser gradient `data_science`
- X-cap — plafonner désirabilité quand <N techs extraites
- S — recalibrage seuils

**Re-ingestion LLM** (coûteux, à grouper en batch) :
- X-domaine — EverAI mal classée
- R — taxonomie rôle (manager, advisor)
- Doublons Plus que Pro — rôles incohérents

---

## Table de pivot — priorisation

### Priorité 1 — Critiques (parallélisables)

**G — Gates éliminatoires** (~12 offres)
- Impact : Critique — faux positifs en parfait (QuadCode ×2 Russian)
- Levier : Gate pré-scoring → langue non possédée, contrat alternance/stage → `hors_perimetre`
- Mode : Rescore-only | Coût : Moyen

**P — Profil incomplet** (~14 offres)
- Impact : Critique — atteignabilité écrasée sur les cibles parfait/rêve
- Levier : Enrichir `gregoire.yaml` (~19 techs), calibrer niveaux
- Mode : Rescore-only | Coût : Nul

### Priorité 2

**A — Alias / normalisation** (~11 offres)
- Impact : Haut — même mécanisme que P
- Levier : Enrichir `alias.yaml` + exclure `ia`/`ai` du matching tech
- Mode : Rescore-only | Coût : Faible

### Priorité 3

**X — Extraction bruitée** (~7 offres)
- Impact : Moyen — fausses rêve 100/0, bruit
- Levier : Plafonner désirabilité si extraction pauvre ; re-extraction domaine en batch
- Mode : Mixte (rescore + re-ingestion LLM partielle) | Coût : Faible/Moyen

### Priorité 4

**D — Domaine miscalibré** (~9 offres)
- Impact : Moyen — bruit de ranking dans hors
- Levier : Baisser gradient `data_science` ; envisager split `ds_ml` vs `analytics`
- Mode : Rescore-only | Coût : Faible

### Priorité 5

**S — Seuils de catégorie** (4 offres)
- Impact : Moyen mais dépendant des corrections 1→4
- Levier : Recalibrer frontières + effet séniorité après re-score
- Mode : Rescore-only | Coût : Faible

### Priorité 6 / Backlog

**R — Taxonomie rôle** (4 offres)
- Impact : Faible
- Levier : Étendre taxonomie (manager, advisor)
- Mode : Re-ingestion LLM | Coût : Moyen

**Séquence** : Lot 1 = P + G (critiques, indépendants). Lot 2 = A + X-cap, re-score, mesure delta. Puis D et S sur données propres. R attend batch re-ingestion.

---

## Chantier annexe

Dédoublonnage : Plus que Pro ×3, CapsLock ×2, Reflet ×2. Hors scope scoring mais fausse les stats de review.
