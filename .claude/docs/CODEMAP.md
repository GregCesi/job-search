# CODEMAP — job-search
> Carte de retrieval. Générée 2026-06-26.
> Pointeurs vers le code réel. Ne pas recopier le code. Régénérable — ne pas éditer à la main.

## Architecture générale

Pipeline d'ingestion et de scoring d'offres d'emploi : fetch (France Travail + Remotive + Indeed) → dédup → LLM extraction (faits intrinsèques) → scoring Python (atteignabilité + désirabilité) → persistance SQLite + ChromaDB → digest + API REST → interface web Nuxt 4.

Trois briques autour d'une base partagée `data/job_search.sqlite` :
- **Orchestrator** (CLI matinale) : `orchestrator/job_search/`
- **API** (FastAPI, lecture/verdicts) : `api/`
- **Web** (Nuxt 4, pilotage) : `web/`

## Orchestrator — pipeline d'ingestion

### Entry point
- `orchestrator/job_search/run.py:14` — `main()` — orchestrateur principal (fetch → dédup → extract → score → persist → digest)
  - Commande : `python -m orchestrator.job_search.run [--profile profiles/gregoire.yaml] [--max 150] [--since-hours 24] [--no-remotive] [--no-indeed]`
  - Charge profil + alias table, init DB, lance Embedder, itère offres, génère digest
  - Autres entry points : `view.py:42`, `verdict.py:53`, `rescore.py:15` (outils auxiliaires)

### Sources pluggables — abstraction `Source`
- `orchestrator/job_search/sources/base.py:49` — `class JobOffer(BaseModel)` — schéma neutre offres
  - Champs pivots : `source`, `source_id`, `fingerprint`, `title`, `description` (Markdown), `extracted_facts` (LLM)
  - Compatibilité v1 : `techs_required` initialement `list[str]` → coerced en `list[TechRequirement]` via validateur `_coerce_techs_v1`
  - Description : `description` (Markdown dérivé), `description_raw` (source brut immuable)
- `orchestrator/job_search/sources/base.py:72` — `class Source(ABC)` — interface pour sources
  - Méthode : `fetch() -> list[JobOffer]`
  - Implémentations : `FranceTravailSource`, `RemotiveSource`, `IndeedFileSource`

#### France Travail (Offres v2)
- `orchestrator/job_search/sources/france_travail.py:31` — `class FranceTravailSource(Source)`
  - OAuth2 : `_get_token()` (ligne 62) — refresh si expiré, scope `api_offresdemploiv2 o2dsoffre`
  - `fetch()` (ligne ~143) — commune Strasbourg (INSEE 67482) + rayon 30 km, mots-clés ["python", "data engineer", "machine learning", "développeur"]
  - Detection remote : `_detect_remote()` (ligne 22) — regex sur titre + description + lieu
  - Fingerprint : `_fingerprint()` (ligne 36) — hash(titre normalisé | entreprise | lieu) pour dédup cross-source

#### Remotive
- `orchestrator/job_search/sources/remotive.py:14` — `class RemotiveSource(Source)`
  - API : `https://remotive.com/api/remote-jobs` (category=software-dev)
  - Description HTML → Markdown via `html_to_markdown()` (ligne 54), stockée dans `description_raw`
  - Tout Remotive = full-remote implicite

#### Indeed (fichier)
- `orchestrator/job_search/sources/indeed_file.py:20` — `class IndeedFileSource(Source)` — lit JSONL du inbox Indeed
  - Inbox directory : `data/indeed_inbox/` (par défaut)
  - Chaque ligne = offre brute JSON, mappée vers `JobOffer`
  - `_map()` (ligne 50) : HTML → Markdown, fingerprint universel, source_id fallback sur hash si absent
  - 0 appel réseau, 0 LLM — source de données orkestrée par MCP (architecture.md §4)

### Dédup
- `orchestrator/job_search/storage/dedup.py:11` — `filter_new()` — compare fingerprint contre base existante
- `orchestrator/job_search/sources/fingerprint.py:10` — `fingerprint(title, company, location)` — hash SHA256[:16] universel pour cross-source

### Dédup amont (API)
- `api/offers.py:170` — `POST /offers/check-known` — endpoint read-only dédup avant ingestion
  - Accepte list[{title, company, location}], retourne new_indices + counts
  - Utilisé par skill /ingest-indeed pour throttle 2-3s + fallback gracieux (architecture.md §1)

### Extraction LLM (faits intrinsèques, une seule fois par offre)
- `orchestrator/job_search/scoring/extractor.py:102` — `extract_facts(offer, model, host, retries=2)`
  - Client Ollama : température 0.1, few-shot 3 exemples, parsing défensif JSON
  - Retourne `ExtractedFacts` ou fallback avec `parse_failed=True` (jamais crash)
  - Champs extraits : `seniority_required`, `techs_required` (+ importance), `domain`, `role_level`
  - Prompt système : ligne 29, few-shot : ligne 57
  - Domaines valides : ai_engineering, data_engineering, data_science, backend, devops, fullstack, embedded, other
  - Implicites : "RAG en prod" → "rag" (cité ligne 45)
  - Tracing : appel LLM écrit dans `data/traces/` via `_write_trace()` (ligne 15)

### Scoring — deux axes (0-100 chacun)
Jamais produit par LLM. Aucun appel LLM en phase de scoring.

#### Atteignabilité — puis-je décrocher ?
- `orchestrator/job_search/scoring/attainability.py:138` — `compute_attainability(facts, profile, table)`
  - Matching = recouvrement de listes : `techs_required ∩ profile.skills` (canonicalisées)
  - Pondération par importance : core=3.0, required=2.0, nice_to_have=0.5 (ligne 31)
  - Moyenne pondérée des niveaux profil : `Σ(level_i × weight_i) / Σ(weight_i) × 10` → 0-100
  - Techno inconnue : level=0 (neutre, dilue le score)
  - Techno exclue (alias=None) : écartée du calcul
  - Retour : `Attainability` struct avec score, techs_matched_json, techs_missing_json (persistés)
- Séniorité : vérification simple `profile_seniority >= facts.seniority_required` (cf. `_SENIORITY_ORDER`)
- Role : vérification `profile.role_ceiling >= facts.role_level`

#### Désirabilité — m'intéresse-t-elle ?
- `orchestrator/job_search/scoring/desirability.py:72` — `compute_desirability(facts, criteria, profile, table)`
  - Gradient de domaine : `_DOMAIN_GRADIENT` (ligne 20) — ai_engineering=1.0 → other=0.0
  - Facteur envie-techno : `_desire_factor()` (ligne 41) — moyenne des desire du profil sur techs de l'offre
    - Neutre si aucune techno connue
    - Floor à 0.5 si desire=0 sur toutes
  - Score = `domain_gradient × desire_factor × 100`
  - Retour : `Desirability` struct avec score + detail observable par critère

#### Catégorisation
- `orchestrator/job_search/scoring/categorize.py` — table (désirabilité, atteignabilité) → catégorie
  - Catégories : parfait | reve | atteignable | hors

#### Gates (hors-périmètre)
- `orchestrator/job_search/scoring/hors_perimetre.py` — `derive_hors_perimetre(facts)` — court-circuite scoring
- `orchestrator/job_search/scoring/filters.py` — `apply_hard_filters(offer, criteria)` — filtre dur amont (contrat, lieu, CDI)

#### Aliasing / Canonicalisation
- `orchestrator/job_search/scoring/aliases.py` — `canonicalize(tech_name, table)` → forme canonique ou None (exclu)
  - Table d'alias chargée depuis `profiles/alias.yaml` (externe, mutable)
  - Exemples : "langchain" → "langgraph", "kubernetes" → exclu (None)
  - Appliqué dans attainability + desirability pour unified matching

### Persistance — SQLite

#### DB initialisation
- `orchestrator/job_search/storage/db.py:14` — `init_db(conn)` + `migrate_offers_schema(conn)` — idempotent
  - Tables : `offers`, `verdicts`, `human_reviews`
  - Chemin : `data/job_search.sqlite`

#### Table `offers` (schéma complet)
- `orchestrator/job_search/storage/db.py:16` — DDL CREATE TABLE
  - Champs neutres : source, source_id, fingerprint, title, company, location, remote, contract_type, alternance, full_time, company_size, experience_required, rome_code, rome_label, url, fetched_at, description, description_raw
  - LLM : extracted_facts_json (TEXT)
  - Scoring dérivé : category, hors_perimetre_reason
  - Matching techs : techs_matched_json, techs_missing_json (persistés au score, cf. L7 divergence-front)
  - Interaction humaine : seen, verdict (via table séparée), categorie_suggeree, categorie_corrigee, remarque, reviewed_at
  - Filtrage : filtered_out, filter_reason
  - PK : id (INTEGER PRIMARY KEY), UNIQUE(source, source_id)
  - INDEX : idx_offers_fingerprint

#### Sauvegarde offre
- `orchestrator/job_search/storage/offers.py:27` — `save_offer(conn, offer, category=..., hors_perimetre_reason=..., techs_matched=..., techs_missing=..., ...)`
  - Upsert : INSERT OR REPLACE
  - Sérialisation : `extracted_facts_json` = JSON string, techs matched/missing = JSON list

#### Table `verdicts`
- `orchestrator/job_search/storage/db.py:41` — DDL
  - offer_id (FK), status (favori | rejeté | candidaté | masqué | hors_perimetre_ok | hors_perimetre_faux_pos), created_at
  - Interaction humaine, jamais source de recalcul

#### Table `human_reviews`
- `orchestrator/job_search/storage/db.py:50` — DDL
  - offer_id (PK), ratings_json (review par-critère), ai_snapshot_json (copie figée du criteria_json à l'instant T), global_audit_text, global_score
  - Auto-portante : snapshot = observabilité décision IA au moment de la review (survit à changements ultérieurs)

### Profil cible (mutable YAML)
- `orchestrator/job_search/matching/profile.py:27` — `load_profile(path)` → (Profile, sha256_hex)
  - Schema Pydantic : role_ceiling, skills (name → {level 1-10, desire 0-10}), search_criteria (domains, locations, contract_types)
  - Exemple : `profiles/gregoire.yaml`
  - Hash calculé sur contenu brut (détecte tout changement)

### Embeddings — ChromaDB
- `orchestrator/job_search/matching/embedder.py:36` — `class Embedder`
  - Chemin : `data/chroma` (PersistentClient)
  - Profil : ré-embedé seulement si hash change (cache dans `data/profile_cache.json`)
  - Offres : ajoutées incrémentalement via `add_offer()`
  - Collection : "job_offers", metric=cosine

### Digest
- `orchestrator/job_search/digest/formatter.py` — `generate_digest(scored_offers, run_at)` — text formaté
  - Contenu : offres par catégorie, stats, suggestions
  - Sauvegardé dans `data/digest_YYYYMMDD_HHMM.txt`

## API — FastAPI (port 8000)

### Main
- `api/main.py:10` — `app = FastAPI(title="job-search-api", version="0.1.0")`
  - CORS : allow_origins=["http://localhost:3000"]
  - Routers : offers, export, traces

### Health
- `api/main.py:25` — `GET /health` → {"status": "ok"}

### Offers & Verdicts
- `api/offers.py:53` — `GET /offers` — list avec filtres (remote, source, verdict, category, hors_perimetre, etat_review, q, sort)
- `api/offers.py:170` — `POST /offers/check-known` — dédup amont (read-only), accepte list[{title, company, location}]
- `api/offers.py:199` — `GET /offers/{offer_id}` — détail (OfferDetail + extracted_facts + techs_matched/missing)
- `api/offers.py:275` — `PUT /offers/{offer_id}/verdict` — upsert verdict (status)
- `api/offers.py:309` — `PUT /offers/{offer_id}/category-review` — review catégorie (categorie_corrigee, remarque)
- `api/offers.py:350` — `GET /offers/{offer_id}/review` — lecture review
- `api/offers.py:373` — `DELETE /offers/{offer_id}/verdict` — suppression verdict

#### Schémas
- `api/schemas.py:6` — `OfferRow` — list offers
- `api/schemas.py:42` — `OfferDetail` — detail + extracted_facts + techs_matched/missing
- `api/schemas.py:50` — `VerdictIn` — POST verdict
- `api/schemas.py:54` — `CategoryReviewIn` — PUT review
- Dérivés (jamais persistés) : categorie_finale, etat_review (calculés par `_derive_review_fields()` ligne 28)

### Traces Viewer
- `api/traces.py:89` — `GET /traces/counts` — stats par cause/sévérité
- `api/traces.py:95` — `GET /traces` — list traces LLM
- `api/traces.py:117` — `PUT /traces/{trace_key}/note` — upsert annotation
- `api/traces.py:153` — `GET /traces/export` — export JSONL

#### Schémas
- `api/schemas.py:81` — `TraceOut` — trace enrichie (offer_title, parsed_facts, note)
- `api/schemas.py:103` — `TraceNoteIn` — annotation

### DB access
- `api/db.py` — `get_conn()` — connexion SQLite partagée avec orchestrator

### Profile endpoint
- `api/profile.py` — expose profil chargé + alias table

### Export
- `api/export.py:22` — `GET /export/calibration` — export données (JSONL, CSV…)

## Web — Nuxt 4 + Tailwind + Pinia v3

### Lancé
- `cd web && npm run dev` (port 3000)
- `nuxt.config.ts:1` — config Nuxt, runtimeConfig.public.apiBase = "http://localhost:8000"

### Pages
- `web/app/pages/index.vue` — liste offres (filtres, sort, pagination, verdicts, review catégorie)
- `web/app/pages/traces.vue` — viewer traces LLM

### Components
- `web/app/components/OffersTable.vue` — table offres avec badges (techs matched, verdict, review state)
- `web/app/components/OfferDetail.vue` — modal détail offre + facts + techs matched/missing + bouton "voir traces"
- `web/app/components/FiltersPanel.vue` — panneau filtres
- `web/app/components/VerdictBadge.vue` — badge verdict

### Stores (Pinia v3)
- `web/app/stores/offers.ts:74` — list offres, load detail, upsert verdict, upsert review
  - Interface OfferDetail enrichie (ligne 39) : techs_matched + techs_missing (pour affichage front)
  - VIEW_PRESETS (ligne 64) : a_traiter, a_relire, favoris, hors_perimetre, tout
- `web/app/stores/traces.ts` — list traces, upsert note

## Profils YAML (mutable)

### Principal
- `profiles/gregoire.yaml` — profil cible (role_ceiling=ic, skills Python/FastAPI/LangGraph/RAG/Vue/Nuxt, search_criteria domains/locations/contract_types)

### Alias table
- `profiles/alias.yaml` — canonicalisation techs (langgraph ← langchain, kubernetes ← k8s, etc. + exclusions)

## Chantiers & statuts (voir STATE.md)

### Livrés ✓
- Zone A sourcing & tri (L0→L13, juin 2026)
- Refonte scoring double-axe : désirabilité + atteignabilité (L1→L13, juin 2026)
- Chantier traces viewer (L1→L11, juin 2026)
- Chantier hors-périmètre (L0→L8, juin 2026)
- Chantier review humaine (L1→L12, juin 2026)
- Adapter Remotive + multi-source (L1→L3, juin 2026)
- Chantier bouton trace (L1→L5, juin 2026)
- Chantier HTML→Markdown (L0→L9, juin 2026)
- Chantier canonicalisation techs : alias.yaml externe (L0→L8, juin 2026)
- Chantier divergence front : back source unique matching (L0→L7, juin 2026)
- Chantier source Indeed : adapter fichier + MCP (L2→L9, juin 2026)
- Chantier dédup amont Indeed : fingerprint partagé + endpoint check-known (L0→L2, juin 2026)

### En réflexion
- Aucun chantier en cours

## Invariants détectés

### Invariant 1 : 0 LLM en phase scoring
Extraction LLM ⟷ **une seule fois** à l'ingestion, résultats persistés (`extracted_facts_json`). Tout le scoring (attainability, desirability, categorization) est calcul Python pur, recalculable sans coût si le profil change. Jamais de recalcul LLM déclenché par change de `profile.yaml` → voir `orchestrator/job_search/run.py:108-110` (compute_desirability + compute_attainability)

### Invariant 2 : Sources pluggables, schéma neutre
Toute source implémente `Source.fetch() → list[JobOffer]`. Pipeline aval (dédup, embedding, scoring, persist, digest) ne connaît QUE `JobOffer`, jamais schéma natif. Mapping payload → `JobOffer` vit DANS l'adapter. Exemples : Remotive description HTML → `html_to_markdown()` côté RemotiveSource → `description` Markdown immuable, `description_raw` HTML conservé. Indeed JSONL → mapping `_map()` côté IndeedFileSource (architecture.md §1)

### Invariant 3 : Profil cible mutable, ré-embed seulement si hash change
Profil déclaratif YAML, jamais codé en dur. Loader calcule hash SHA256, ré-embed ChromaDB seulement si hash change. Plusieurs profils possibles (fichiers distincts). Cache dans `data/profile_cache.json` → voir `orchestrator/job_search/matching/embedder.py:36`

### Invariant 4 : Scoring explicable par construction
Critères atomiques (0-100 chacun) + mini-justification par critère → score global agrégé côté code (jamais bloc par LLM). Détail persistent via `extracted_facts_json` (structure observabilité de décision). Parsing défensif : retry + fallback si LLM dégradé → voir `orchestrator/job_search/scoring/extractor.py:102-180` (boucle retry, fallback)

### Invariant 5 : Séparation offers / verdicts / human_reviews
Trois tables distinctes, jamais fusionnées. `offers` = source de vérité scoring (extraction LLM). `verdicts` = interaction humaine globale. `human_reviews` = notation par-critère + snapshot IA à l'instant T. Jamais recalcul scoring depuis verdict/review → voir `orchestrator/job_search/storage/db.py:14-112` (DDL tables + migration)

### Invariant 6 : Alias/canonicalisation centralisée
Table d'alias YAML (externe, mutable) chargée au run. Canonicalize appliquée dans attainability + desirability pour unified matching. Exclu (alias=None) écartés du calcul → voir `orchestrator/job_search/scoring/aliases.py`, appelée en `attainability.py:138` et `desirability.py:72`

### Invariant 7 : Dédup cross-source via fingerprint universel
Fingerprint = hash SHA256[:16](titre normalisé | entreprise | lieu), stable cross-source. Détecte doublons France Travail ↔ Remotive ↔ Indeed. Fonction partagée `fingerprint()` (ligne 10) utilisée par toutes les sources et endpoint check-known (architecture.md §1)

### Invariant 8 : Description = dérivé Markdown, description_raw = source brut immuable
Offre stocke deux versions description. Markdown propre utilisée par viewer + LLM. Raw (HTML pour Remotive, brut pour Indeed) conservé pour traçabilité/reparse. Jamais récursion ou mutation de raw → voir `orchestrator/job_search/sources/base.py:54-55`, chaque adapter (RemotiveSource, IndeedFileSource) appelle `html_to_markdown()` et stocke raw

### Invariant 9 : Dédup amont par API read-only (avant ingestion)
Skill /ingest-indeed appelle endpoint `POST /offers/check-known` avant d'ajouter au inbox Indeed. Retour : new_indices + counts. Permet throttle 2-3s + fallback gracieux sans modifier la base. 0 mutation DB (architecture.md §4)

## Zones périphériques (cartographiées par nom/sig, non lues intégralement)

- `orchestrator/job_search/view.py` — CLI vue offres (lecture DB, affichage interactif)
- `orchestrator/job_search/verdict.py` — CLI verdict (interaction humaine, écriture verdict/review)
- `orchestrator/job_search/rescore.py` — CLI rescore offres (recompute scores sans re-extraction LLM)
- `orchestrator/job_search/sources/_clean.py` — `html_to_markdown()` (HTML → MD pour Remotive + Indeed)
- `orchestrator/job_search/storage/purge.py` — purge offres non pertinentes (out_of_reach + peu désirables)
- `orchestrator/job_search/storage/reviews.py` — helpers lecture/écriture human_reviews
- `orchestrator/job_search/matching/profile.py:44` — DEPRECATED `MasteryLevel` enum (v1, maintenu pour compat)
- `orchestrator/job_search/scoring/tracing.py` — LLMTrace struct + writer pour traces LLM
- `orchestrator/job_search/scoring/categorize.py` — table (désir, attain) → cat
- `api/traces_reader.py` — lecteur traces depuis disk
- `web/app/app.vue` — layout Nuxt

## Fichiers de config / meta

- `.claude/state/STATE.md` — état courant, dernière action, prochaine action
- `.claude/state/IMPLEMENTATION-*.md` — plans d'exécution par chantier
- `.claude/rules/` — rules modulaires (stack.md, architecture.md, workflow.md, update-protocol.md)
- `.claude/commands/` — /status, /handoff
- `CLAUDE.md` — instructions projet (contexte, stack, architecture, rules)
- `pyproject.toml` — dépendances Python
- `web/package.json` — dépendances Nuxt + node
- `.env` (non commité) — OLLAMA_MODEL, OLLAMA_HOST, FRANCE_TRAVAIL_CLIENT_ID/SECRET
