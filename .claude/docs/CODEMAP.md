# CODEMAP — job-search
> Carte de retrieval du sourcing & scoring automatique d'offres d'emploi.
> Générée le 2026-07-06. Pointeurs vers le code réel (fichier:lignes). Régénérable.

## Architecture générale
Pipeline d'ingestion et de scoring : fetch (3 sources) → dédup (fingerprint) → filtres durs → LLM extraction (faits atomiques) → scoring Python (désirabilité × atteignabilité) → persistance (SQLite + ChromaDB) → digest + API REST → interface web Nuxt 4.

Trois briques autour d'une base partagée `data/job_search.sqlite` :
- **Orchestrator** (CLI matinale) : `orchestrator/job_search/` — run.py principal
- **API** (FastAPI, port 8000) : `api/` — offers, export, traces routers
- **Web** (Nuxt 4, port 3000) : `web/` — interface pilotage + candidat

---

## Orchestrator — pipeline d'ingestion

### Point d'entrée principal
- **CLI run** : `orchestrator/job_search/run.py:14-135` — orchestrateur matinal
  - Entrée : `python -m orchestrator.job_search.run [--profile profiles/gregoire.yaml] [--max 150] [--since-hours 24] [--no-remotive] [--no-indeed]`
  - Étapes : 
    1. Charge profil YAML + calcul hash (ligne 52)
    2. Charge alias table (ligne 53)
    3. Init DB + Embedder (lignes 57-63)
    4. Fetch 3 sources (lignes 66-79)
    5. Dédup (ligne 82)
    6. Itère : filtre durs → extraction LLM → scoring Python → catégorisation → persist (lignes 86-115)
    7. Purge (ligne 118)
    8. Digest (lignes 122-131)

### Schémas de domaine

- **JobOffer** : `orchestrator/job_search/sources/base.py:49-70`
  - Pivots : source, source_id (stable/source), fingerprint (hash cross-source), title
  - Description : description (Markdown dérivé), description_raw (brut immuable)
  - Métadata : company, location, remote, contract_type, nature_contract, alternance, full_time, company_size, experience_required, rome_code, rome_label
  - URL + fetched_at
  - Extracted facts : ExtractedFacts (rempli par LLM, persiste)
  - Compat v1 : techs_required initialement list[str] → coercé via validateur _coerce_techs_v1 (lignes 35-46)

- **ExtractedFacts** : `orchestrator/job_search/sources/base.py:27-46`
  - seniority_required : SeniorityLevel (junior, intermediate, senior, lead)
  - techs_required : list[TechRequirement] — chaque tech a (name, importance ∈ {core, required, nice_to_have})
  - domain : str — domaine métier {ai_engineering, data_engineering, data_science, backend, devops, fullstack, embedded, other}
  - role_level : RoleLevel (ic, lead, manager)
  - parse_failed : bool — flag si extraction LLM dégradée (jamais crash, fallback)

- **TechRequirement** : `orchestrator/job_search/sources/base.py:22-24`
  - name : str, importance : Literal["core", "required", "nice_to_have"]

- **Source (ABC)** : `orchestrator/job_search/sources/base.py:72-75`
  - Méthode abstraite : fetch() → list[JobOffer]
  - Implémentations : FranceTravailSource, RemotiveSource, IndeedFileSource

### Sources (adapters)

#### FranceTravailSource
- **Classe** : `orchestrator/job_search/sources/france_travail.py:31-166`
- **Auth OAuth2** : `_get_token():52-70` — token + expiry. Scope : api_offresdemploiv2 o2dsoffre
- **Pagination** : `_search_page():76-86` (100/page), `_fetch_all():88-100` (boucle pagination)
- **Mapping** : `_map():106-137` — payload FT → JobOffer. Détection remote par keywords (ligne 18-27). Calcul full_time depuis dureeTravailLibelleConverti.
- **Fetch** : `fetch():143-166` — itère mots-clés, collecte par commune (INSEE 67482 Strasbourg) + rayon 30km
- **Mots-clés** : ["python", "data engineer", "machine learning", "développeur"] (ligne 44)

#### RemotiveSource
- **Classe** : `orchestrator/job_search/sources/remotive.py:14-56`
- **Fetch** : API https://remotive.com/api/remote-jobs?category=software-dev
- **Mapping** : HTML description → Markdown via html_to_markdown() (ligne 43), conservation description_raw (HTML)
- **Propriétés** : Tous les jobs remote=True

#### IndeedFileSource
- **Classe** : `orchestrator/job_search/sources/indeed_file.py:20`
- **Source** : JSONL inbox directory data/indeed_inbox/ (par défaut)
- **Mapping** : Ligne 50, _map() → JobOffer. HTML→Markdown, fingerprint universel
- **Source_id** : fallback hash si absent dans brut

### Dédup

- **filter_new()** : `orchestrator/job_search/storage/dedup.py:6-26`
  - Retourne offres absentes de la DB
  - Vérifie (source, source_id) ∈ seen_ids ET fingerprint ∈ seen_fps
  - Garde-fou doublon batch : ajoute à seen_ids/fps en itérant

- **fingerprint()** : `orchestrator/job_search/sources/fingerprint.py:10`
  - SHA256[:16] hash (titre normalisé + entreprise + localisation)
  - Universel cross-source

### API dédup amont (read-only)

- **POST /offers/check-known** : `api/offers.py:187-215`
  - Entrée : list[{source_id, title, company, location}]
  - Retour : dict[source_id] → {known: bool}
  - 0 mutation DB

### Profil cible (mutable YAML)

- **Profile** : `orchestrator/job_search/matching/profile.py:27-41`
  - profile_id : str
  - role_ceiling : RoleCeiling (ic, lead, manager) — plafond de rôle assumé
  - skills : dict[str, SkillEntry] — tech_name → {level:1-10, desire:0-10}
  - search_criteria : SearchCriteria — {domains, locations, contract_types}
  - Méthodes : tech_level(tech:str) → int|None, tech_desire(tech:str) → int|None

- **load_profile()** : `orchestrator/job_search/matching/profile.py:51-57`
  - Charge YAML depuis path
  - Retourne (Profile, sha256_hex) — hash sur contenu brut (détecte tout changement)

- **Exemple** : `profiles/gregoire.yaml`
  - role_ceiling: ic
  - skills : python/fastapi/langgraph/rag/llm (level/desire), technos héritées (java/typescript/react/spring), notions (agents/nlp/ml)
  - search_criteria : domains=[ai_engineering, automation, backend], locations=[strasbourg_area, remote], contract_types=[cdi, freelance]

### Filtres durs (pré-scoring, 0 LLM)

- **apply_hard_filters()** : `orchestrator/job_search/scoring/filters.py:20-52`
  - Contrat : alternance/stage (codes _STAGE_CODES={STA,STG,APP,PRO}) → filtered_out=True
  - Location : remote OK (remote=True && "remote" ∈ criteria.locations) OU strasbourg_area (77xxx, STRASBOURG, BAS-RHIN) → pass ; sinon → filtered_out=True
  - Retourne (filtered_out:bool, reason:str|None)

### Extraction LLM (1 appel/offre, jamais recalculée)

- **extract_facts()** : `orchestrator/job_search/scoring/extractor.py:102-150+`
  - Client Ollama (host configurable, model configurable)
  - System prompt : lignes 29-55 — structure JSON + règles
  - Few-shot : lignes 57-80 — 3 exemples (IC mixte importance, tech lead, backend legacy)
  - User prompt : built lines 119-125 (titre + description + experience hint + ROME + alternance)
  - Parse JSON strictement, retry ×2, fallback parse_failed=True (jamais crash)
  - Retourne ExtractedFacts avec flag parse_failed
  - Tracing : appel écrit dans data/traces/ via _write_trace() (ligne 15)

### Scoring Python (0 LLM, recalculable si profil change)

#### Filtrage hors-périmètre (court-circuit)
- **derive_hors_perimetre()** : `orchestrator/job_search/scoring/hors_perimetre.py:21-27`
  - no_tech : techs_required == [] (incertain, à inspecter)
  - mgmt_role : role_level == manager
  - Retourne HorsPerimetreReason | None

#### Désirabilité (0-100)
- **compute_desirability()** : `orchestrator/job_search/scoring/desirability.py:72-102`
  - Gradient domaine (ligne 20-29) : {ai_engineering:1.0, data_science:0.7, data_engineering:0.5, backend:0.5, fullstack:0.25, devops:0.2, embedded:0.1, other:0.0}
  - Facteur envie-techno (ligne 41-61) : moyenne desire sur techs connues de l'offre. Inconnu neutre=1.0. Floor=0.5 si desire=0 sur toutes.
  - Score = gradient × desire_factor × 100
  - Retour : Desirability {score:float, detail:dict} observable

#### Atteignabilité (0-100)
- **compute_attainability()** : `orchestrator/job_search/scoring/attainability.py:138-150+`
  - Techno matching : _compute_attain_tech() (ligne 62-106)
    - Poids importance : {core:3.0, required:2.0, nice_to_have:0.5} (ligne 31)
    - Moyenne pondérée : Σ(level_i × weight_i) / Σ(weight_i) × 10 → 0-100
    - Techno absente : level=0 (neutre, dilue)
    - Techno exclue (alias=None) : retirée du calcul
  - Role ceiling : _compute_attain_role() (ligne 115-126)
    - Portail gradué IC/lead/manager
    - Même cran/en-dessous → 100. +1 → 40. +2+ → 0
  - Score final : min(attain_tech, attain_role) — non-compensation
  - Retour : Attainability {score, attain_tech, attain_role, techs_matched, techs_missing, blocked_by}

#### Catégorisation (4 cases)
- **categorize()** : `orchestrator/job_search/scoring/categorize.py:22-36`
  - parfait : d > 50 && a > 40
  - reve : d > 50 && a ≤ 40
  - atteignable : d ≤ 50 && a > 40
  - hors : d ≤ 50 && a ≤ 40
  - Seuils DESIRABILITY_THRESHOLD=50, ATTAINABILITY_THRESHOLD=40 (calibrables)

#### Canonicalisation/Alias
- **canonicalize()** : `orchestrator/job_search/scoring/aliases.py:56`
  - Map tech brute → forme canonique OR None (exclu)
  - Table chargée depuis profiles/alias.yaml (externe, mutable)
  - Appliqué dans attainability + desirability

### Persistance offres (SQLite)

- **save_offer()** : `orchestrator/job_search/storage/offers.py:27-91`
  - Upsert offre. INSERT ON CONFLICT(source, source_id) DO UPDATE
  - Persiste : extracted_facts_json, category, description, techs_matched_json, techs_missing_json, filtered_out, filter_reason, hors_perimetre_reason
  - Sérialisation : JSON string pour facts et listes techs

- **StoredOffer** : `orchestrator/job_search/storage/offers.py:10-24`
  - Dataclass léger pour digest : id, source, source_id, title, company, location, remote, contract_type, url, fetched_at, category, description, filtered_out, filter_reason

- **get_offers_since()** : `orchestrator/job_search/storage/offers.py:94-138`
  - Retourne offres non-filtrées depuis datetime
  - Triées par catégorie (parfait→reve→atteignable→hors)
  - Limit 50 défaut

### Embeddings (ChromaDB)

- **Embedder** : `orchestrator/job_search/matching/embedder.py:36-102`
  - Client PersistentClient(data/chroma)
  - Collection "job_offers", metric=cosine
  - embed_profile(profile, profile_hash) → bool
    - Hash-basé, ré-embed seulement si hash change
    - Cache JSON dans data/profile_cache.json
  - add_offer(offer) — upsert dans ChromaDB
  - similarity(offer) → cosine ∈ [0, 1]
  - IDs ChromaDB : "{source}:{source_id}"

### Digest

- **generate_digest()** : `orchestrator/job_search/digest/formatter.py:24`
  - Formaté texte par catégorie
  - Sauvegardé data/digest_YYYYMMDD_HHMM.txt

---

## Database — SQLite + ChromaDB

### DB Schema (SQLite)

- **offers** : `orchestrator/job_search/storage/db.py:16-39` — DDL CREATE TABLE
  - PK : id (INTEGER PRIMARY KEY)
  - UNIQUE : (source, source_id)
  - Colonnes principales : source, source_id, fingerprint, title, company, location, remote, contract_type, nature_contract, alternance, full_time, company_size, experience_required, rome_code, rome_label, url, fetched_at, description, description_raw
  - LLM : extracted_facts_json (TEXT)
  - Scoring : category (TEXT), hors_perimetre_reason (TEXT)
  - Matching : techs_matched_json, techs_missing_json (TEXT)
  - Interaction : seen_candidat (INTEGER), categorie_suggeree, categorie_corrigee, remarque, reviewed_at
  - Filtrage : filtered_out (INTEGER), filter_reason (TEXT)
  - Index : idx_offers_fingerprint

- **verdicts** : `orchestrator/job_search/storage/db.py:41-46` — DDL
  - id (PK), offer_id (FK → offers.id), status (TEXT), created_at (TEXT)
  - status ∈ {retenu, rejeté, candidaté, masqué, hors_perimetre_ok, hors_perimetre_faux_pos}

- **human_reviews** : `orchestrator/job_search/storage/db.py:50-58` — DDL
  - offer_id (TEXT PK), ratings_json (TEXT), ai_snapshot_json (TEXT), global_audit_text (TEXT), global_score (INTEGER), seen_at_review (INTEGER), created_at (TEXT)
  - Snapshot = observabilité décision IA au moment review (survit à changements ultérieurs)

### Initialisation & migrations

- **get_connection()** : `orchestrator/job_search/storage/db.py:7-11`
  - DB_PATH = Path("data/job_search.sqlite")
  - Crée parent dir, retourne connexion avec row_factory=sqlite3.Row

- **init_db()** : `orchestrator/job_search/storage/db.py:14-61`
  - Crée tables if not exists via executescript
  - Appelle migrate_offers_schema()

- **migrate_offers_schema()** : `orchestrator/job_search/storage/db.py:63-116`
  - Migrations incrémentales
  - Ajoute colonnes manquantes (lignes 67-93 : description, seen_candidat, nature_contract, alternance, full_time, company_size, experience_required, rome_code, rome_label, extracted_facts_json, filtered_out, filter_reason, category, hors_perimetre_reason, categorie_suggeree, categorie_corrigee, remarque, reviewed_at, description_raw, techs_matched_json, techs_missing_json)
  - Renomme seen → seen_candidat (lignes 99-100)
  - Supprime anciens champs scoring : score, criteria_json (lignes 103-105)
  - Supprime vieux scoring détail (lignes 108-114 : desirability, desirability_detail, attainability, attainability_detail, score_in_category, attain_tech, attain_role, blocked_by)

### ChromaDB

- **Chemin** : data/chroma/ (PersistentClient)
- **Collection** : "job_offers"
- **Embedding** : DefaultEmbeddingFunction (Sentence Transformers)
- **Métadata HNSW** : cosine space

---

## API — FastAPI

### Point d'entrée

- **app** : `api/main.py:9-27`
  - FastAPI(title="job-search-api", version="0.1.0")
  - CORS : allow_origins=["http://localhost:3000"]
  - Routers : offers, export, traces
  - Health check : GET /health (ligne 25-27)

### Schémas réponse (Pydantic)

- **OfferRow** : `api/schemas.py:6-26`
  - id, title, company, location, remote, contract_type, category, verdict, hors_perimetre_reason, seen_candidat, fetched_at, filtered_out, filter_reason
  - Review champs : categorie_suggeree, categorie_corrigee, categorie_finale (dérivé), etat_review (dérivé), remarque, reviewed_at

- **OfferDetail** : `api/schemas.py:42-49` — étend OfferRow
  - + source_id, description, url, source, extracted_facts, techs_matched, techs_missing

- **ExtractedFactsSchema** : `api/schemas.py:34-39`
  - seniority_required, techs_required (list[TechSchema]), domain, role_level, parse_failed

- **TechSchema** : `api/schemas.py:29-31` — name, importance (str|None, compat v1)

### Endpoints — Offres

- **GET /offers** : `api/offers.py:53-180+`
  - Filtres : remote, source, verdict, seen_candidat, filtered_out, category, exclude_category, hors_perimetre, etat_review, q (full-text sur title+company), sort (multi-col), order
  - Par défaut filtered_out=0 (exclut filtrées) sauf si filtered_out=True
  - Tri : sort ∈ {fetched_at, title, company, category, seen_candidat, location}
  - Retour : list[OfferRow]

- **POST /offers/check-known** : `api/offers.py:187-215`
  - Batch dédup par fingerprint
  - Entrée : list[{source_id, title, company, location}]
  - Retour : dict[source_id] → {known: bool}

- **GET /offers/{offer_id}** : `api/offers.py:216-260`
  - Offre complète + review linked
  - Parsed extracted_facts depuis JSON
  - techs_matched, techs_missing parsés depuis JSON
  - Retour : OfferDetail

- **PUT /offers/{offer_id}/verdict** : `api/offers.py:292-324`
  - Upsert verdict, status ∈ {retenu, rejeté, candidaté, masqué, hors_perimetre_ok, hors_perimetre_faux_pos}
  - 204 No Content

- **DELETE /offers/{offer_id}/verdict** : `api/offers.py:390-409`
  - Supprime verdict pour offer_id
  - 204 No Content

- **PUT /offers/{offer_id}/category-review** : `api/offers.py:326-365`
  - Review humaine catégorie
  - Entrée : categorie_corrigee (opt), remarque (opt)
  - 204 No Content

- **GET /offers/{offer_id}/review** : `api/offers.py:367-388`
  - Récupère review liée
  - Retour : ReviewOut

### Endpoints — Export

- **GET /export/offers** : `api/export.py:30-114`
  - Export scoring/verdicts en Markdown
  - Contextualisé par filtre
  - Retour : PlainTextResponse

- **GET /export/calibration** : `api/export.py:188-230`
  - Export comparaison human_reviews vs scores IA
  - Listes divergences par critère

### Endpoints — Traces (LLM debugging)

- **GET /traces/counts** : `api/traces.py:89-93`
  - Retour : dict[offer_id] → count traces

- **GET /traces** : `api/traces.py:95-116`
  - Retour : list[TraceOut] (parsed JSON LLM)
  - Enrichi avec annotations trace_notes

- **PUT /traces/{trace_key}/note** : `api/traces.py:117-152`
  - Upsert annotation (note, cause, severite)

- **GET /traces/export** : `api/traces.py:153`
  - Export traces en JSONL

### Helpers API

- **_derive_review_fields()** : `api/offers.py:28-46`
  - Dérive categorie_finale et etat_review à la volée (jamais persistés)
  - categorie_finale = corrigee ?? suggeree
  - etat_review ∈ {non_relue, validee, corrigee}

- **get_conn()** : `api/db.py:9`
  - Retourne connexion SQLite (DB_PATH depuis racine repo)

- **_parse_facts()** : `api/offers.py:262-291`
  - Parse extracted_facts_json (JSON → ExtractedFactsSchema)
  - Fallback None si malformé

---

## Frontend — Nuxt 4 + Pinia

### Config

- **nuxt.config.ts** : `web/nuxt.config.ts:1-10`
  - runtimeConfig.public.apiBase : "http://localhost:8000"
  - Modules : @pinia/nuxt, @nuxtjs/tailwindcss
  - devtools enabled
  - compatibilityDate : 2025-07-15

### Store Pinia — Offres

- **useOffersStore** : `web/app/stores/offers.ts:84-200+`
  - Interfaces : OfferRow, OfferDetail, ExtractedFacts, TechInfo, Filters
  - State : offers[], openedOffer, activeView, filters, loading, traceCounts
  - ActiveView : CandidateView (cibles|gaps|filet|retenues) | OperatorView (a_traiter|hors_perimetre|tout)
  - VIEW_PRESETS (lignes 70-80) : 6 vues prédéfinies avec filters + sort/order
    - candidat : cibles (parfait), gaps (reve), filet (atteignable), retenues (verdict=retenu)
    - opérateur : a_traiter (etat_review=non_relue), hors_perimetre, tout
  - Actions : fetchTraceCounts(), setActiveView(), upsertVerdict(), upsertCategoryReview(), export contextuel

### Store Pinia — Traces

- **useTracesStore** : `web/app/stores/traces.ts:33`
  - State : traces[], selectedTrace, filters
  - Actions : list, filter, upsert note

### Pages

- **index.vue** : `web/app/pages/index.vue`
  - Candidat view (cibles/gaps/filet/retenues)
  - Table offres + detail modal

- **operateur.vue** : `web/app/pages/operateur.vue`
  - Opérateur view (à_traiter/hors_perimetre/tout)
  - Review humaine catégorie
  - Verdict change

- **traces.vue** : `web/app/pages/traces.vue`
  - Inspect extractions LLM
  - Note/cause/severite debugging

### Components

- **OffersTable.vue** : affiche list[OfferRow]
  - Tri, filtres
  - Clics → modal detail

- **OfferDetail.vue** : offre complète
  - extracted_facts, techs_matched/missing
  - Actions verdict + category-review
  - Bouton voir traces

- **FiltersPanel.vue** : filtres dynamiques
  - category, hors_perimetre, etat_review, q, sort, order, etc.

- **ExportPopover.vue** : export contextuel offres → Markdown pour LLM

- **VerdictBadge.vue** : badge verdict

---

## Fichiers support

### Archivage & Décisions

- **STATE.md** : ``.claude/state/STATE.md`` — Dernière action, prochaine action
- **IMPLEMENTATION.md** : ``.claude/state/IMPLEMENTATION.md`` — Chantiers, checklist
- **DECISIONS.md** : ``.claude/state/DECISIONS.md`` — Décisions architecturales (dates, rationales)

### Profils YAML (mutables)

- **gregoire.yaml** : `profiles/gregoire.yaml`
  - profile_id: gregoire
  - role_ceiling: ic
  - skills : {tech: {level, desire}}
  - search_criteria : {domains, locations, contract_types}

- **alias.yaml** : `profiles/alias.yaml`
  - Canonicalisation technos (externe, mutable)

### Cache

- **profile_cache.json** : `data/profile_cache.json`
  - {hash, embedding} — ré-embed si hash change

---

## Fichiers périphériques (cartographiés par nom/sig, non lus intégralement)

- `orchestrator/job_search/view.py:42` — CLI vue offres (lecture DB)
- `orchestrator/job_search/verdict.py:53` — CLI verdict (interaction humaine)
- `orchestrator/job_search/rescore.py:15` — CLI rescore (recompute scores, 0 LLM)
- `orchestrator/job_search/sources/_clean.py` — html_to_markdown()
- `orchestrator/job_search/storage/purge.py` — purge offres (out_of_reach + peu désirables)
- `orchestrator/job_search/storage/reviews.py` — helpers human_reviews
- `orchestrator/job_search/matching/profile.py:44` — DEPRECATED MasteryLevel enum (v1, compat)
- `orchestrator/job_search/scoring/tracing.py` — LLMTrace struct + writer
- `api/traces_reader.py` — lecteur traces depuis disk
- `api/db.py:9` — get_conn()
- `web/app/app.vue` — layout Nuxt
- `web/app/components/ExportPopover.vue` — export popover
- `web/app/components/VerdictBadge.vue` — badge verdict

---

## Invariants détectés

- **Sources pluggables** (architecture.md §1) — Toute source → JobOffer. Mapping interne adapter. Pipeline aval 0-connaissance source natif. ✓ FranceTravailSource, RemotiveSource, IndeedFileSource.

- **Profil mutable** (architecture.md §2) — YAML chargé, hash calculé. Ré-embed profil uniquement si hash change. Multiples profils possibles. ✓ load_profile() + profile_cache.json.

- **Scoring explicable** (architecture.md §3) — LLM note faits atomiques (ExtractedFacts). Score global Python (désirabilité × atteignabilité). Critères + justifs persistés (extracted_facts_json). 0 score "en bloc". Parsing défensif (fallback parse_failed). ✓ extract_facts() + fallback ; compute_desirability() ; compute_attainability().

- **0 LLM au recalcul** (architecture.md §4) — LLM 1× à l'ingestion. Scoring Python recalculable à volonté (profil change → 0 appel LLM). ✓ Separation extractor vs scoring ; scoring functions pures.

- **Separation offers/verdicts/human_reviews** — 3 tables distinctes. Verdicts et reviews ne sont PAS intrants de recalcul (signal apprentissage). ✓ 3 tables séparées ; orchestrator jamais ne lit verdicts pour rescorer.

- **Dédup cross-source** — Fingerprint universel = hash SHA256[:16](titre norm | entreprise | lieu). Détecte doublons France Travail ↔ Remotive ↔ Indeed. ✓ fingerprint() partagée ; used by all sources + check-known.

- **Description double** — description=Markdown dérivé (viewer+LLM), description_raw=brut immuable (traçabilité). ✓ Chaque adapter appelle html_to_markdown() + stocke raw.

- **Alias centralisée** — Table YAML externe (mutable), chargée au run. Canonicalize appliquée attainability + desirability pour unified matching. Exclu (alias=None) écartés. ✓ aliases.py ; appelée attainability.py:138, desirability.py:72.
