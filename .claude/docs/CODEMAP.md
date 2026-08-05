# CODEMAP — job-search

> Carte de retrieval. Générée par codemap-builder le 2026-08-05.
> Pointeurs vers le code réel. Ne pas recopier le code. Régénérable — ne pas éditer à la main.

---

## Chemins canoniques

- **REPO_ROOT** : `orchestrator/job_search/paths.py:9` — racine du repo, source unique de résolution
- **DB_PATH** : `orchestrator/job_search/paths.py:11` → `data/job_search.sqlite` (SQLite partagée orchestrator ↔ api)
- **PROFILE_PATH** : `orchestrator/job_search/paths.py:13` → `profiles/gregoire.yaml` (profil mutable, par défaut)
- **ALIAS_PATH** : `orchestrator/job_search/paths.py:14` → `profiles/alias.yaml` (canonicalisation technos)
- **TRACES_PATH** : `orchestrator/job_search/paths.py:12` → `data/traces/extract_facts.jsonl` (logs LLM append-only)

---

## Schémas de données (Pydantic)

### JobOffer — schéma neutre source-agnostique
`orchestrator/job_search/sources/base.py:50-71`
- Champs clés : `source`, `source_id`, `fingerprint`, `title`, `description` (Markdown), `description_raw` (brut source)
- `extracted_facts` : ExtractedFacts populate par LLM (étage 4), None à l'ingestion
- Tous les adaptateurs sources mappent leur schéma natif vers JobOffer ici ; aucun champ source brut ne fuit à l'aval

### ExtractedFacts — faits intrinsèques extraits par LLM
`orchestrator/job_search/sources/base.py:27-48`
- Champs : `seniority_required` (SeniorityLevel), `techs_required` (list[TechRequirement]), `domain` (str, 8 valeurs), `role_level` (RoleLevel), `langues_requises`, `parse_failed`
- Persisté une fois sur `offers.extracted_facts_json`, immuable (sauf `--re-extract`)
- Coerce v1 : list[str] → list[TechRequirement] (model_validator L36)

### TechRequirement — technologie exigée avec poids
`orchestrator/job_search/sources/base.py:22-25`
- Champs : `name` (str, canonicalisé au scoring), `importance` (Literal["core"|"required"|"nice_to_have"])
- Poids au calcul atteignabilité : core=3.0, required=2.0, nice_to_have=0.5 (`scoring/attainability.py:31`)

### Profile — profil cible mutable
`orchestrator/job_search/matching/profile.py:36-52`
- Champs : `profile_id`, `role_ceiling` (RoleCeiling: ic|lead|manager), `seniority_ceiling` (SeniorityLevel | None), `skills` (dict[str, SkillEntry]), `zones` (dict[str, Zone]), `search_criteria` (SearchCriteria)
- Chargé via `load_profile(path)` → (Profile, sha256_hex) `matching/profile.py:56`
- Immuable en base — tout changement est édition YAML + rescore Python

### Zone — localisation recherche
`orchestrator/job_search/matching/profile.py:23-27`
- Champs : `insee` (list[str], codes communes), `dept` (list[str], préfixes), `keywords` (list[str], mots-clés libellés)
- Résolu depuis profil YAML au startup `run.py:60-64`

### SearchCriteria — critères de recherche immuables
`orchestrator/job_search/matching/profile.py:29-33`
- Champs : `keywords` (list[str]), `domains` (list[str]), `locations` (list[str], noms de zones + "remote"), `contract_types` (list[str], codes FT : "cdi", "cdd", "freelance"…)

### Enum — valeurs fermées

#### SeniorityLevel
`orchestrator/job_search/sources/base.py:9-13` : junior | intermediate | senior | lead

#### RoleLevel
`orchestrator/job_search/sources/base.py:16-19` : ic | lead | manager

#### RoleCeiling
`orchestrator/job_search/matching/profile.py:12-15` : ic | lead | manager

#### Category (catégorisation)
`orchestrator/job_search/scoring/categorize.py:10-14` : parfait | reve | atteignable | hors

#### HorsPerimetreCause (gates éliminatoires)
`orchestrator/job_search/scoring/hors_perimetre.py:18-22` : no_tech | mgmt_role | langue | contrat

---

## Orchestrateur — CLI run matinal

### Point d'entrée principal
`orchestrator/job_search/run.py:15-144` — main()
- Arguments : `--profile`, `--max`, `--since-hours`, `--no-remotive`, `--no-indeed`
- Pipeline : fetch → dédup → hard-filter → LLM-extract → score (d/a) → gate hors-périmètre → persist → digest

### Étage 1 : Fetch (sources pluggables)
`orchestrator/job_search/sources/base.py:73-76` — interface Source (ABC)
  - Méthode abstraite : `fetch() -> list[JobOffer]`

Sources implémentées :
- **FranceTravailSource** : `orchestrator/job_search/sources/france_travail.py:30-150+`
  - OAuth2 token : `_get_token()` L51-69
  - Recherche paginée : `_search_page()` L75-99+
  - Mapping FT → JobOffer : `_map()` interne
  - Keywords paramétrisés (jamais hardcodés) : `__init__` L31-43

- **RemotiveSource** : `orchestrator/job_search/sources/remotive.py` — fetch depuis API Remotive publique
- **IndeedFileSource** : `orchestrator/job_search/sources/indeed_file.py` — fetch depuis JSON files dropzone

Fingerprint (dédup cross-source) : `orchestrator/job_search/sources/fingerprint.py:fingerprint()` — hash(titre normalisé | entreprise | localisation)[:16]

### Étage 2 : Dédup
`orchestrator/job_search/storage/dedup.py:6-27` — filter_new(conn, offers)
- Clé primaire : (source, source_id) [voir schema DB L37]
- Clé secondaire : fingerprint [idx L47]
- Garde intra-batch : une offre dupliquée dans le fetch n'est comptée qu'une fois

### Étage 3 : Hard filters (localisation + contrat)
`orchestrator/job_search/scoring/filters.py:31-78` — apply_hard_filters(offer, criteria, zones)
  - Règle contrat : alternance=True → out ; codes stage (STA/STG/APP/PRO) → out ; nature_contract contient stage/apprentissage → out ; si contract_types renseigné, seuls les types mappés passent
  - Règle localisation : remote=True ET "remote" in locations → OK ; sinon match zone via dept (préfixe) ou keywords (substring) ; ni l'un ni l'autre → location:hors_zone
  - Mapping contrat FT → clés profil : CDI→cdi, CDD→cdd, LIB→freelance, MIS→mis `filters.py:23-28`

### Étage 4 : LLM Extraction (faits intrinsèques)
`orchestrator/job_search/scoring/extractor.py:96-180+` — extract_facts(offer, model, host)
- LLM : Ollama local, modèle paramétrisé (défaut "llama3"), température 0.1 [L26-27]
- System prompt : L29-59 (8 domaines, importance levels, faits intrinsèques seulement)
- Few-shot : L61-84 (3 exemples complètement annotés)
- Validation schéma : SeniorityLevel, RoleLevel, importance, domain (8 valeurs) — fallback `_fallback()` L96-100 si parsing échoue
- Retry logic : 3 tentatives totales, fallback dégradé (techs_required=[], domain="other", parse_failed=True)
- Tracing : append JSONL dans TRACES_PATH `scoring/tracing.py:_write_trace()` — vocabulaire brut LLM conservé intacts (source de vérité audit)

### Étage 5 : Scoring (Python pur, 0 LLM)
Deux axes : désirabilité (veux-je cette offre ?) et atteignabilité (peux-je la décrocher ?)

#### Désirabilité (envie × domaine)
`orchestrator/job_search/scoring/desirability.py:72-100+` — compute_desirability(facts, criteria, profile, table)
- Fonction pure : ExtractedFacts + SearchCriteria + Profile → Desirability(score: 0-100, detail: dict)
- Gradient domaine : ai_engineering=1.0, data_science/data_engineering/backend=0.5-0.4, fullstack=0.25, devops=0.2, embedded=0.1, other=0.0 (L20-29)
- Facteur envie-techno : ∈ [_DESIRE_FLOOR=0.5, 1.0], basé sur moyenne des `desire` (0-10) profil sur techs exigées (techs exclues ignorées) (L41-61)
- Score = domain_gradient × desire_factor × 100
- Seuil catégorisation : > 50 = "désirable" (`categorize.py:18`)

#### Atteignabilité (techs + rôle + séniorité)
`orchestrator/job_search/scoring/attainability.py:1-140+` — compute_attainability(facts, profile, table)
- Fonction pure : ExtractedFacts + Profile → Attainability(score, attain_tech, attain_role, seniority_malus, techs_matched, techs_missing, blocked_by)
- Matching techs : moyenne pondérée des niveaux profil (1-10) sur techs exigées, pondérée par importance (core=3.0, required=2.0, nice_to_have=0.5) (L62-100)
  - Canonicalisation via alias.yaml : variante → forme canonique, exclus → retirés du calcul
  - Techs inconnues (pas alias ni profil) : auto-canonicalisées lowercase
  - Dédup canonique : N tokens bruts → même canonical = compte une fois (importance = max vu)
- Matching rôle : role_level de l'offre vs role_ceiling profil, min() non-compensatoire (L120-140)
- Séniorité : malus par cran au-dessus du plafond : SENIORITY_MALUS_PER_STEP=20 par cran (L22-23)
- Score final = max(0, min(attain_tech, attain_role) − seniority_malus)
- Seuil catégorisation : > 40 = "atteignable" (`categorize.py:19`)
- Retourne aussi `techs_matched` et `techs_missing` pour affichage front

#### Canonicalisation technos
`orchestrator/job_search/scoring/aliases.py:24-66` — load_alias_table(path), canonicalize(tech, table)
- Chargement depuis `profiles/alias.yaml` : index inverse variante→canonique, set d'exclusions
- Règles : variante connue → canonique ; terme exclu → None ; inconnu → tech.lower().strip() passthrough
- Appliquée au scoring seulement, jamais à l'ingestion ni aux traces

#### Catégorisation (2×2)
`orchestrator/job_search/scoring/categorize.py:22-36` — categorize(desirability, attainability)
- Seuils : DESIRABILITY_THRESHOLD=50, ATTAINABILITY_THRESHOLD=40 (calibrables)
- Cases : parfait (d>50 ∧ a>40), reve (d>50 ∧ a≤40), atteignable (d≤50 ∧ a>40), hors (d≤50 ∧ a≤40)

#### Gate hors-périmètre (post-scoring)
`orchestrator/job_search/scoring/hors_perimetre.py:44-77` — derive_hors_perimetre(facts, title, description, contract_type, nature_contract, alternance)
- Retourne list[HorsPerimetreCause] (vide = dans le périmètre)
- Causes : no_tech (techs_required == []), mgmt_role (role_level == manager), langue (keyword scan langs tierces), contrat (MIS / stage / apprentissage keywords ou types code)
- Gate appliqué APRÈS d/a calculés — les scores sont conservés intacts (observabilité décision)

### Étage 6 : Persistance
`orchestrator/job_search/storage/offers.py:27-95` — save_offer(conn, offer, category, filtered_out, filter_reason, perimetre_causes, techs_matched, techs_missing)
- UPSERT offres sur (source, source_id) — une ligne par offre, mise à jour si rescorée
- Colonnes clés : `extracted_facts_json`, `category`, `techs_matched_json`, `techs_missing_json`, `hors_perimetre_reason` (causes jointes), `filtered_out`, `filter_reason`, `perimetre_causes` (JSON list), `rescored_at` (timestamp)
- Offres filtrées/hors-périmètre conservées en base, jamais supprimées (seules les colonnes de scoring sont vides/null)

### Étage 7 : Digest (sortie matinale)
`orchestrator/job_search/digest/formatter.py:24-42` — generate_digest(offers, run_at)
- Filtre : offres de catégorie parfait/reve/atteignable seulement
- Tri : par ordre de préférence (parfait < reve < atteignable)
- Limite : TOP_N=15 offres retenues
- Format texte lisible (titre, entreprise, localisation, URL)
- Écrit dans `data/digest_YYYYMMDD_HHMM.txt`

### Rescore — recalcul Python sans LLM
`orchestrator/job_search/rescore.py:16-100+` — main()
- Relit `extracted_facts_json` depuis base (jamais recalcul LLM)
- Recalcule d/a pour toutes les offres non-filtrées/non-hors-périmètre
- Réévalue catégorisation et gates hors-périmètre
- UPSERT en base avec `rescored_at` timestamp
- Cas d'usage : changement profil YAML, ajustement seuils/calibration

### Verdict humain — statut + annotation
`orchestrator/job_search/verdict.py:16-70` — CLI pour enregistrer le statut humain
- Statut : enum fermé à définir (favori, rejeté, candidaté, …)
- Enregistrement : `verdicts` table, jamais écrit dans `offers` (scores IA immuables)

---

## API FastAPI

### Point d'entrée
`api/main.py:34-52`
- App : FastAPI titre="job-search-api" version="0.1.0"
- Middleware CORS : allow_origins=["http://localhost:3000"]
- Migration DB au startup : `_migrate_db()` L13-25 (idempotent)
- Health endpoint : GET /health

### Routers inclus
- `api/offers.py` → `/offers/*` (read, upsert verdict, upsert category-review, export)
- `api/export.py` → `/export/*` (offers markdown, calibration CSV)
- `api/traces.py` → `/traces/*` (read, annotate, export JSONL)

### Offers — Endpoints principaux
`api/offers.py:188-220+`

#### GET /offers (list)
- Query params : filters (category, filtered_out, remote, contract_type…), sort, page
- Response : list[OfferRow] — champs pour grille : id, title, company, location, remote, contract_type, category, reviewed_at
- Derive à la volée : `score_breakdown` (ligne expliquant catégorisation), `categorie_finale` (dérivé de category IA + categoria_corrigee humain)

#### GET /offers/{offer_id} (détail)
- Response : OfferDetail — tous champs, y compris `extracted_facts_json` parsé, techs_matched/missing listes, review info
- Dérive : score_breakdown, categorie_finale, etat_review (not_reviewed | reviewed | flagged)

#### PUT /offers/{offer_id}/verdict (upsert verdict)
- Request : VerdictIn (status: str)
- Crée row dans `verdicts` table, timestamp now
- Ne modifie pas `offers` (isolation données IA)

#### PUT /offers/{offer_id}/category-review (upsert human review par-critère)
- Request : CategoryReviewIn (ratings_json: dict[criterion: int], global_audit_text: str, global_score: int | None)
- Crée/update row dans `human_reviews` table, snapshot `ai_snapshot_json` = copy de extracted_facts_json à l'instant du review
- Persisté pour calibration d'IA

#### GET /offers/{offer_id}/review (read human review)
- Response : ReviewOut (human ratings, AI snapshot, disagreement score)
- Appelle `calibration/disagreement.py:disagreement()` pour comparer IA vs humain

#### DELETE /offers/{offer_id}/verdict (delete verdict)
- Supprime row `verdicts` pour cet offer_id

### Score breakdown — dérivé à la volée
`api/offers.py:49-82`
- Charge profil + alias table (cached module-level) une seule fois
- Recalcule d/a pour l'offre depuis extracted_facts_json
- Retourne ligne unique expliquant pourquoi offre dans sa catégorie (parfait/reve/atteignable/hors)
- Null si extracted_facts absent ou parse_failed=True

### Schemas — réponses API
`api/schemas.py` (lecture complète pour schémas OfferRow, OfferDetail, ReviewOut, VerdictIn, CategoryReviewIn)

### Export — endpoints
`api/export.py:31-250+`

#### GET /export/offers (Markdown)
- Response : PlainTextResponse
- Tableau Markdown : titre, entreprise, score, catégorie, techs matched/missing, URLs
- Champs sélectionnables via query param `fields`

#### GET /export/calibration (CSV)
- Response : PlainTextResponse (CSV)
- Lignes : offres reviewées (humain) uniquement, avec IA snapshot + human ratings + écart disagreement
- Pour étude calibration modèle

### Traces — debug & audit
`api/traces.py:18-180+`

#### GET /traces/counts
- Response : dict[str, int] — comptage offres par trace status

#### GET /traces (list)
- Response : list[TraceOut] — traces LLM + annotations humaines
- Lecture depuis JSONL + annotations (table `trace_notes`)

#### PUT /traces/{trace_key}/note (upsert annotation)
- Request : TraceNoteIn (body: str)
- Crée/update row `trace_notes` table pour feedback sur extraction LLM

#### GET /traces/export (export JSONL)
- Response : JSONL avec traces + annotations inline
- Pour archivage audit

---

## Persistance — SQLite

### Schéma de base
`orchestrator/job_search/storage/db.py:13-119` — init_db(conn), migrate_offers_schema(conn)

#### Table : offers
`db.py:15-38` — CREATE TABLE IF NOT EXISTS offers (…)
- Clé primaire : UNIQUE(source, source_id)
- Colonnes clés :
  - `source, source_id, fingerprint` (dédup multi-source)
  - `title, company, location, remote, contract_type, nature_contract, alternance, full_time, company_size` (métadatas source)
  - `experience_required, rome_code, rome_label, url, fetched_at` (FT-specific, mappage source)
  - `description, description_raw` (description Markdown dérivée + brut source immuable)
  - `seen_candidat` (flag interactions)
  - `extracted_facts_json` (ExtractedFacts sérialisé, immuable sauf --re-extract)
  - `category` (parfait/reve/atteignable/hors, null si filtrée/hors-périmètre)
  - `filtered_out, filter_reason` (hard-filter gate)
  - `hors_perimetre_reason, perimetre_causes` (gate hors-périmètre)
  - `techs_matched_json, techs_missing_json` (détail matching tech)
  - `rescored_at` (timestamp dernier rescore)

#### Table : verdicts
`db.py:40-45` — CREATE TABLE IF NOT EXISTS verdicts (…)
- Foreign key : offer_id REFERENCES offers(id)
- Colonnes : `status` (statut humain : favori/rejeté/candidaté/…), `created_at`
- Isolation : n'écrit jamais dans `offers` (scores IA immuables)

#### Table : human_reviews
`db.py:49-57` — CREATE TABLE IF NOT EXISTS human_reviews (…)
- Clé primaire : offer_id (TEXT)
- Colonnes : `ratings_json` (dict[criterion: int]), `ai_snapshot_json` (ExtractedFacts copie figée à l'instant review), `global_audit_text` (libre), `global_score` (int | None), `seen_at_review` (flag), `created_at`
- Snapshot : rend chaque review auto-portante, capable de survivre aux changements de profil/scoring

#### Table : trace_notes
`api/traces.py:22-29` — CREATE TABLE IF NOT EXISTS trace_notes (…)
- Clé primaire : trace_key (identifiant unique JSONL)
- Colonnes : `body` (annotation humaine), `created_at, updated_at`

### Migration incrémentale
`db.py:62-119` — migrate_offers_schema(conn)
- Ajout des colonnes progressivement via ALTER TABLE (idempotent)
- Renommages : `seen` → `seen_candidat` (L101-103)
- Suppressions : `score, criteria_json` (ancien scoring) et `desirability, attainability, score_in_category, attain_tech, attain_role, blocked_by` (ancienne v2) (L105-117)

### Connexion
`api/db.py:7-10` — get_conn() → sqlite3.Connection (row_factory=Row)

---

## Frontend — Nuxt 4 + Pinia v3

### Point d'entrée
`web/package.json:1-23`
- Dépendances clés : @nuxtjs/tailwindcss, @pinia/nuxt, pinia v3, nuxt 4, vue 3, marked, dompurify

### Store (state management)
Logs: `/web/stores/offers.ts` — Pinia store (lecture nécessaire pour détails)
- VIEW_PRESETS : 6 vues (candidat : cibles/gaps/filet/retenues ; opérateur : a_traiter/hors_perimetre/tout)
- Champs dérivés `categorie_finale` et `etat_review` : calculés côté API seulement, jamais côté front
- Zéro logique métier — chaque store fait fetch API + state management

### Configuration
`web/nuxt.config.ts` — config Nuxt (lecture nécessaire pour détails)
- API base : `runtimeConfig.public.apiBase` → `http://localhost:8000` (configurable)
- Tailwind CSS via @nuxtjs/tailwindcss

### Composants
Logs: `/web/components/**/*.vue` — composants Nuxt (lectures nécessaires pour détails)
- Grille offres : filtres, tri, pagination
- Détail offre : scores, techs, review form
- Export markdown

---

## Dépendances

### Python (requirements.txt)
`requirements.txt:1-10`
- **pydantic** ≥2.0 — schémas + validation
- **pyyaml** ≥6.0 — chargement profil/alias YAML
- **ollama** ≥0.3 — client LLM Ollama
- **requests** ≥2.31 — HTTP client (France Travail API, Remotive API)
- **python-dotenv** ≥1.0 — .env loader (credentials FT)
- **fastapi** ≥0.111 — API web
- **uvicorn[standard]** ≥0.29 — serveur ASGI
- **html2text** ≥2024.2 — conversion HTML → Markdown
- **ruff** ≥0.11.0 — linter/formatter

### JavaScript / Node (web/package.json)
- **nuxt** ^4.4.6 — SSR + framework
- **pinia** ^3.0.4 — state management
- **vue** ^3.5.34 — runtime
- **vue-router** ^5.0.7 — routing
- **@nuxtjs/tailwindcss** ^6.12.2 — CSS utility framework
- **dompurify** ^3.4.10 — sanitize HTML (review display)
- **marked** ^18.0.5 — parse Markdown (description affichage)

---

## Calibration — étude IA

### Disagreement score
`orchestrator/job_search/calibration/disagreement.py:18-50+` — DisagreementScore, disagreement(review)
- Calcule l'écart entre notations IA et humaines par-critère
- Détails : écart absolu, écart normalisé, ratio critères avec désaccord > seuil

### Rescore workflow
Pour observer la stabilité du modèle et des seuils de catégorisation :
1. Scorer batch initial (run.py)
2. Reviewer subset d'offres (human_reviews)
3. Exporter calibration CSV (GET /export/calibration)
4. Ajuster alias.yaml / seuils (`DESIRABILITY_THRESHOLD`, `ATTAINABILITY_THRESHOLD`, poids importance)
5. Rescore (rescore.py) → comparer scores pré/post
6. Itérer jusqu'à stabilité acceptable

---

## Invariants détectés

### 1. Scoring explicable par construction
- Faits intrinsèques extraits UNE SEULE FOIS par offre (étage 4, LLM)
- Tous les recalculs aval = Python pur sur `extracted_facts_json` (étage 5, rescore)
- Critères notés atomiquement (0-10 chacun) ; agrégation pondérée côté code, jamais bloc LLM
- Score global = min(attain_tech, attain_role) − seniority_malus (non-compensatoire)

### 2. Sources pluggables
- Interface unique `Source.fetch() -> list[JobOffer]`
- Schéma neutre `JobOffer` seul transitaire en aval
- Mapping source → JobOffer vit DANS l'adapter, nulle part ailleurs

### 3. Profil YAML = source unique de pilotage
- Toute variable de pilotage (zones, contrats, seuils, skills, desires) vit dans YAML
- Code consomme profil, ne le duplique jamais en dicts internes
- Changement YAML = rescore Python, 0 code touché

### 4. Zéro LLM au rescore
- Étage 4 (extraction) : 1 appel LLM/offre à l'ingestion
- Étage 5 (scoring) : Python pur, jamais relancé sauf si offre change ou --re-extract explicite
- Rescore 4000 offres = 4000 calculs Python, 0 appel LLM, CPU froid

### 5. Trace brute sacrée
- Canonicalisation (`alias.yaml`) appliquée au scoring seulement
- Vocabulaire brut LLM conservé intacts dans JSONL (`data/traces/extract_facts.jsonl`)
- Source de vérité pour audit et calibration

### 6. Gates post-scoring observables
- `perimetre_causes` = liste de causes (pas booléen)
- Scores d/a calculés et persistés MÊME SI offre gatée (observabilité)
- Offres jamais supprimées, seulement marquées filtrées/hors-périmètre

### 7. Données d'interaction isolées
- `verdicts` et `human_reviews` = interaction (même statut que `seen_candidat`)
- Jamais écrit dans `offers` (scores IA immuables)
- Snapshot `ai_snapshot_json` dans `human_reviews` = auto-portant (survive changements scoring)
- Écart human ↔ IA = signal d'apprentissage (fusionner le détruit)

### 8. Dédup multi-source
- Clé primaire : (source, source_id)
- Fallback cross-source : fingerprint (hash titre|entreprise|localisation)
- Guard intra-batch : duplicate dans même fetch ne compte qu'une fois

