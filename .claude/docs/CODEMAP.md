# CODEMAP — job-search

> Carte de retrieval du sourcing & scoring automatique d'offres d'emploi.
> Générée le 2026-07-06. Pointeurs vers le code réel (fichier:lignes). Régénérable.

## Architecture générale

Pipeline matinal : fetch (3 sources) → dédup (fingerprint) → filtres durs → LLM extraction (faits atomiques) → scoring Python (désirabilité × atteignabilité) → persistance (SQLite + ChromaDB) → digest + API REST → interface web Nuxt 4.

Trois briques autour d'une base partagée `data/job_search.sqlite` :
- **Orchestrator** (CLI matinale) : `orchestrator/job_search/` — orchestration, sourcing, scoring
- **API** (FastAPI, port 8000) : `api/` — endpoints offers, export, traces
- **Web** (Nuxt 4, port 3000) : `web/` — interface pilotage

---

## Orchestrator — pipeline d'ingestion

### Point d'entrée principal

- **CLI run** : `orchestrator/job_search/run.py:14-135` — orchestrateur matinal
  - Entrée : `python -m orchestrator.job_search.run [--profile profiles/gregoire.yaml] [--max 150] [--since-hours 24] [--no-remotive] [--no-indeed]`
  - Étapes : 
    1. Charge profil YAML + calcul hash SHA256 (ligne 52)
    2. Charge alias table (ligne 53)
    3. Init DB + Embedder (lignes 57-63)
    4. Fetch 3 sources (lignes 66-79)
    5. Dédup cross-source (ligne 82)
    6. Itère : filtre durs → extraction LLM → scoring Python → catégorisation → persist (lignes 86-115)
    7. Purge hors-périmètre (ligne 118)
    8. Digest versement (lignes 122-131)

### Schémas de domaine

- **JobOffer** : `orchestrator/job_search/sources/base.py:49-70`
  - Identifiants : source, source_id, fingerprint (cross-source), title
  - Description : description (Markdown dérivé), description_raw (brut immuable)
  - Métadonnées : company, location, remote, contract_type, nature_contract, alternance, full_time, company_size, experience_required, rome_code, rome_label, url, fetched_at
  - Faits extraits : extracted_facts (ExtractedFacts, rempli par LLM, persiste)

- **ExtractedFacts** : `orchestrator/job_search/sources/base.py:27-46`
  - seniority_required : SeniorityLevel (junior|intermediate|senior|lead)
  - techs_required : list[TechRequirement] (chaque tech a name + importance ∈ {core, required, nice_to_have})
  - domain : domaine métier {ai_engineering, data_engineering, data_science, backend, devops, fullstack, embedded, other}
  - role_level : RoleLevel (ic|lead|manager)
  - parse_failed : flag si dégradation LLM (fallback appliqué, jamais crash)

- **Source (ABC)** : `orchestrator/job_search/sources/base.py:72-75` — interface abstraite fetch() → list[JobOffer]

### Sources (adapters pluggables)

- **FranceTravailSource** : `orchestrator/job_search/sources/france_travail.py:31` — OAuth2 FT API, mots-clés {python, data engineer, machine learning, développeur}, commune INSEE 67482 + rayon 30km
- **RemotiveSource** : `orchestrator/job_search/sources/remotive.py:14` — API https://remotive.com, HTML → Markdown, tous les jobs remote=True
- **IndeedFileSource** : `orchestrator/job_search/sources/indeed_file.py:20` — JSONL inbox data/indeed_inbox/

### Dédup cross-source

- **fingerprint()** : `orchestrator/job_search/sources/fingerprint.py:10` — SHA256[:16](titre norm | entreprise | lieu), universel
- **filter_new()** : `orchestrator/job_search/storage/dedup.py:6` — retourne offres absentes de DB
- **POST /offers/check-known** : `api/offers.py:187` — bulk dédup read-only

### Profil cible (YAML mutable)

- **Profile** : `orchestrator/job_search/matching/profile.py:27-41` — profile_id, role_ceiling (ic|lead|manager), skills[tech → {level:1-10, desire:0-10}], search_criteria
- **load_profile()** : `orchestrator/job_search/matching/profile.py:51` — charge YAML, retourne (Profile, sha256_hex)
- **Exemple** : `profiles/gregoire.yaml` — profile_id=gregoire, role_ceiling=ic, ~40 technos (python/fastapi/langgraph/rag/llm/vue/nuxt/java/etc.), domaines=[ai_engineering, automation, backend], localisations=[strasbourg_area, remote]

### Filtres durs (pré-LLM, 0 coût)

- **apply_hard_filters()** : `orchestrator/job_search/scoring/filters.py:20` — exclut alternance/stage/off-location → (filtered_out:bool, reason:str|None)

### Extraction LLM (1 appel/offre, jamais recalculée)

- **extract_facts()** : `orchestrator/job_search/scoring/extractor.py:102` — Ollama local, JSON structured output
  - System prompt (ligne 29) : règles seniority/techs/domain/role
  - Few-shot (ligne 57) : 3 exemples (IC, Tech Lead, Backend)
  - User prompt : titre + description (8000 chars) + hints (seniority, ROME, alternance)
  - Parsing défensif (ligne 150) : retry 2×, fallback parse_failed=True
  - Trace écrite : data/traces/extract_facts.jsonl

### Scoring Python (0 LLM, recalculable si profil change)

#### Hors-périmètre (court-circuit)
- **derive_hors_perimetre()** : `orchestrator/job_search/scoring/hors_perimetre.py:21` — no_tech | mgmt_role

#### Désirabilité (0-100)
- **compute_desirability()** : `orchestrator/job_search/scoring/desirability.py:72` — domain_gradient × desire_factor × 100
  - domain_gradient (ligne 20) : ai_engineering=1.0 → data_science=0.7 → backend=0.5 → other=0.0
  - desire_factor (ligne 41) : moyenne desire sur techs connues (inconnu=1.0 neutre, floor=0.5)

#### Atteignabilité (0-100)
- **compute_attainability()** : `orchestrator/job_search/scoring/attainability.py:138` — min(attain_tech, attain_role) non-compensatoire
  - attain_tech (ligne 62) : moyenne pondérée {core:3.0, required:2.0, nice_to_have:0.5}
  - attain_role (ligne 115) : portail gradué (même_cran=100, +1=40, +2+=0) vs role_ceiling profil
  - Observable : techs_matched, techs_missing, blocked_by

#### Catégorisation (4 cases)
- **categorize()** : `orchestrator/job_search/scoring/categorize.py:22` — seuils DESIRABILITY=50, ATTAINABILITY=40
  - parfait (d>50 ∧ a>40), reve (d>50 ∧ a≤40), atteignable (d≤50 ∧ a>40), hors (d≤50 ∧ a≤40)

#### Canonicalisation techno
- **canonicalize()** : `orchestrator/job_search/scoring/aliases.py:56` — tech brute → forme canon | None (exclu)
- **load_alias_table()** : `orchestrator/job_search/scoring/aliases.py:24` — charge profiles/alias.yaml

### Persistance offres (SQLite)

- **save_offer()** : `orchestrator/job_search/storage/offers.py:27` — upsert (source, source_id), persiste extracted_facts_json, category, techs_matched_json, techs_missing_json
- **get_offers_since()** : `orchestrator/job_search/storage/offers.py:94` — offres non-filtrées depuis datetime, triées par catégorie

### Embeddings (ChromaDB)

- **Embedder** : `orchestrator/job_search/matching/embedder.py:36` — client PersistentClient(data/chroma), collection "job_offers" cosine
  - embed_profile() (ligne 66) : ré-embed ssi hash change, cache dans data/profile_cache.json
  - add_offer() (ligne 79) : upsert offre
  - similarity() (ligne 91) : cosine [0,1] offre ↔ profil

### Digest

- **generate_digest()** : `orchestrator/job_search/digest/formatter.py:24` — texte par catégorie, fichier data/digest_YYYYmmdd_HHMM.txt

---

## Database — SQLite + ChromaDB

### Schéma SQLite

- **offers** : `orchestrator/job_search/storage/db.py:16` — source, source_id, fingerprint, title, company, location, description, description_raw, extracted_facts_json, category, hors_perimetre_reason, techs_matched_json, techs_missing_json, filtered_out, filter_reason, reviewed_at, categorie_suggeree, categorie_corrigee, remarque, seen_candidat, etc.
  - UNIQUE(source, source_id), index fingerprint

- **verdicts** : `orchestrator/job_search/storage/db.py:41` — offer_id, status, created_at (statut=retenu|rejeté|candidaté|masqué|hors_perimetre_ok|hors_perimetre_faux_pos)

- **human_reviews** : `orchestrator/job_search/storage/db.py:50` — offer_id, ratings_json, ai_snapshot_json (snapshot figé), global_audit_text, created_at

### Initialisation & migrations

- **get_connection()** : `orchestrator/job_search/storage/db.py:7` — DB_PATH=data/job_search.sqlite
- **init_db()** : `orchestrator/job_search/storage/db.py:14` — crée tables
- **migrate_offers_schema()** : `orchestrator/job_search/storage/db.py:63` — migrations incrémentales (ajoute colonnes, renomme seen→seen_candidat, supprime anciens champs score)

### ChromaDB

- Chemin : data/chroma/ (PersistentClient)
- Collection : "job_offers", metric=cosine
- Embedding : DefaultEmbeddingFunction (Sentence Transformers)

---

## API — FastAPI

### Point d'entrée

- **app** : `api/main.py:9` — FastAPI, CORS allow_origins=[http://localhost:3000], routers {offers, export, traces}

### Endpoints offres

- **GET /offers** : `api/offers.py:53` — filtres {remote, source, verdict, filtered_out, category, hors_perimetre, etat_review, q}, tri multi-col (sort={fetched_at|title|company|category|seen_candidat|location}, order={asc|desc})
- **POST /offers/check-known** : `api/offers.py:187` — bulk fingerprint check
- **GET /offers/{offer_id}** : `api/offers.py:216` — offre complète + extracted_facts, techs_matched/missing
- **PUT /offers/{offer_id}/verdict** : `api/offers.py:292` — upsert status (204)
- **DELETE /offers/{offer_id}/verdict** : `api/offers.py:391` — reset (204)
- **PUT /offers/{offer_id}/category-review** : `api/offers.py:326` — review humaine (204)
- **GET /offers/{offer_id}/review** : `api/offers.py:368` — fetch review

### Endpoints export

- **GET /export/offers** : `api/export.py:31` — Markdown contextualisé
- **GET /export/calibration** : `api/export.py:189` — comparaison human vs IA

### Endpoints traces LLM

- **GET /traces/counts** : `api/traces.py:89` — count traces/offer
- **GET /traces** : `api/traces.py:95` — list traces détaillées
- **PUT /traces/{trace_key}/note** : `api/traces.py:117` — upsert annotation
- **GET /traces/export** : `api/traces.py:154` — JSONL

### Schémas API

- **OfferRow** : `api/schemas.py:6` — id, title, company, location, remote, contract_type, category, verdict, seen_candidat, filtered_out, hors_perimetre_reason, categorie_{suggeree|corrigee|finale}, etat_review, remarque, reviewed_at
- **OfferDetail** : `api/schemas.py:42` — OfferRow + source_id, description, url, source, extracted_facts, techs_matched, techs_missing
- **ExtractedFactsSchema** : `api/schemas.py:34` — seniority_required, techs_required, domain, role_level, parse_failed

### Helpers API

- **_derive_review_fields()** : `api/offers.py:28` — dérive categorie_finale (corrigee ?? suggeree) + etat_review (non_relue|validee|corrigee), jamais persistés

---

## Frontend — Nuxt 4 + Pinia v3

### Config

- **nuxt.config.ts** : `web/nuxt.config.ts:1` — apiBase=http://localhost:8000, modules {@pinia/nuxt, @nuxtjs/tailwindcss}

### Stores Pinia

- **useOffersStore** : `web/app/stores/offers.ts:84` — state {offers[], openedOffer, activeView, filters, loading}, VIEW_PRESETS candidat={cibles|gaps|filet|retenues}, opérateur={a_traiter|hors_perimetre|tout}
- **useTracesStore** : `web/app/stores/traces.ts:33` — state {traces[], selectedTrace, filters}

### Pages

- **index.vue** : `web/app/pages/index.vue` — candidat view
- **operateur.vue** : `web/app/pages/operateur.vue` — opérateur view + review humaine
- **traces.vue** : `web/app/pages/traces.vue` — inspect extractions LLM

### Components

- **OffersTable.vue** — affiche offres, tri, filtres
- **OfferDetail.vue** — offre complète + facts + verdict
- **FiltersPanel.vue** — filtres dynamiques
- **ExportPopover.vue** — export contextuel → Markdown
- **VerdictBadge.vue** — badge statut

---

## Fichiers périphériques (cartographiés par nom/sig)

- `orchestrator/job_search/verdict.py:53` — CLI interaction verdict
- `orchestrator/job_search/rescore.py:15` — CLI rescore (0 LLM)
- `orchestrator/job_search/sources/_clean.py` — html_to_markdown()
- `orchestrator/job_search/storage/reviews.py` — helpers human_reviews
- `orchestrator/job_search/calibration/disagreement.py:27` — score divergence humain vs IA
- `orchestrator/job_search/scoring/tracing.py` — LLMTrace + writer
- `api/traces_reader.py` — lecteur traces disk
- `api/db.py:9` — get_conn()
- `web/app/app.vue` — layout root

---

## Invariants détectés

1. **Sources pluggables** (architecture.md §1) — Toute source → JobOffer. Mapping interne. Pipeline aval agnostique source natif. Implémentations : FranceTravailSource, RemotiveSource, IndeedFileSource.

2. **Profil mutable, ré-embedding ssi hash change** (architecture.md §2) — load_profile() retourne hash SHA256. Embedder compare avant ré-embed ChromaDB. Multiples profils possibles.

3. **Scoring explicable par construction** (architecture.md §3) — LLM note faits atomiques. Scores Python agrégés. Jamais score opaque en bloc. Parsing défensif obligatoire (fallback parse_failed). Critères + justifs persistés observable.

4. **0 LLM au recalcul** (architecture.md §4) — LLM 1× ingestion. Scoring Python recalculable sans coût (profil change → 0 appel LLM). Séparation extractor vs scoring functions pures.

5. **Separation offers/verdicts/human_reviews** — 3 tables distinctes. Verdicts + reviews ne sont PAS intrants recalcul. Signal apprentissage préservé.

6. **Dédup cross-source par fingerprint universel** — SHA256[:16](titre norm | entreprise | lieu). Détecte doublons FT ↔ Remotive ↔ Indeed. Formule centralisée, jamais réimplémentée.

7. **Description double** — description=Markdown dérivé (viewer+LLM), description_raw=brut immuable (traçabilité source). Chaque adapter appelle html_to_markdown() + conserve raw.

8. **Alias centralisée** — YAML externe (mutable), chargée run. Canonicalize appliquée attainability + desirability. Exclu (alias=None) retirés du calcul.

