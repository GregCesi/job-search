# CODEMAP — job-search

> Carte de retrieval. Générée le 2026-07-15.
> Pointeurs vers le code réel. Ne pas recopier le code. Régénérable — ne pas éditer à la main.

## Architecture générale

Pipeline matinal : fetch (3 sources) → dédup (fingerprint) → hard filters → LLM-extract (faits intrinsèques) → score Python pur → hors-périmètre gates → digest + API REST → web Nuxt 4.

Trois briques autour d'une base partagée `data/job_search.sqlite` :
- **Orchestrator** (CLI matinale) : `orchestrator/job_search/` — sourcing, scoring, digestion
- **API** (FastAPI, port 8000) : `api/` — endpoints offers, export, traces
- **Web** (Nuxt 4, port 3000) : `web/` — interface de pilotage candidat + opérateur

---

## Points d'entrée

### Orchestrator

- **CLI run** : `orchestrator/job_search/run.py:15-main()` 
  - Usage : `python -m orchestrator.job_search.run [--profile] [--max] [--since-hours] [--no-remotive] [--no-indeed]`
  - Étapes : profil load → db init → fetch 3 sources → dédup → foreach(filter → extract → score → persist) → digest

- **CLI rescore** : `orchestrator/job_search/rescore.py:16-main()` 
  - 0 LLM — recalcule d/a/categorie/hors sur extracted_facts_json persistent

- **CLI verdict** : `orchestrator/job_search/verdict.py:53-main()`
  - Interaction verdict humain

### API

- **app** : `api/main.py:34-app` — FastAPI port 8000
  - Middleware : CORS allow_origins=[http://localhost:3000]
  - Routers : offers, export, traces
  - Lifespan : _migrate_db() (lignes 13-25)

### Web

- **config** : `web/nuxt.config.ts` — apiBase=http://localhost:8000, Tailwind + Pinia v3

### Paths canoniques

`orchestrator/job_search/paths.py` — source unique
- REPO_ROOT → orchestrator/job_search/paths.py parent x3
- DB_PATH → data/job_search.sqlite
- TRACES_PATH → data/traces/extract_facts.jsonl
- PROFILE_PATH → profiles/gregoire.yaml
- ALIAS_PATH → profiles/alias.yaml

---

## Étage 1 — Fetch (sources pluggables)

### Interface Source

`orchestrator/job_search/sources/base.py:73-class Source(ABC)`
- Méthode unique : `fetch() -> list[JobOffer]`
- Contrat : chaque adapter mappe brut → JobOffer neutre

### Schémas

**SeniorityLevel** (base.py:9) : junior | intermediate | senior | lead

**RoleLevel** (base.py:16) : ic | lead | manager

**TechRequirement** (base.py:22) : {name: str, importance: core|required|nice_to_have}

**ExtractedFacts** (base.py:27-47)
- seniority_required: SeniorityLevel
- techs_required: list[TechRequirement]
- domain: str (8 valeurs fermées : ai_engineering, data_science, data_engineering, backend, fullstack, devops, embedded, other)
- role_level: RoleLevel (défaut ic)
- langues_requises: list[str]
- parse_failed: bool (flag LLM dégradation, fallback appliqué)
- Compat : model_validator coerce list[str]→list[TechRequirement] (v1)

**JobOffer** (base.py:50-71)
- Identifiants : source, source_id (natif stable), fingerprint (cross-source), title
- Description : description (Markdown propre, dérivé), description_raw (brut immuable)
- Métadonnées : company, location (libellé), remote, contract_type, nature_contract, alternance, full_time, company_size, experience_required, rome_code, rome_label, url, fetched_at
- Extraction : extracted_facts (rempli étage 4, persiste une seule fois)

### Adapters

**FranceTravailSource** : `orchestrator/job_search/sources/france_travail.py:30-class`
- Params : keywords (requis), commune (INSEE), radius_km (30), max_results (150)
- Auth : OAuth2 (client_id/secret env) + _get_token() cache 30s (lignes 51-69)
- Fetch : _search_page() paginated (75-85), _fetch_all() batches (87-99)
- Remote detect : _detect_remote() sur titre+description+lieu (20-26)

**RemotiveSource** : `orchestrator/job_search/sources/remotive.py:14-class`
- API public https://remotive.com/api/remote-jobs
- 0 auth, toutes offres remote=True

**IndeedFileSource** : `orchestrator/job_search/sources/indeed_file.py:20-class`
- Lit JSONL data/indeed_inbox/*.jsonl

### Fingerprinting

`orchestrator/job_search/sources/fingerprint.py:10-fingerprint(title, company, location) -> str`
- Hash : sha256(normalize(title) | normalize(company) | normalize(location))[:16]
- _normalize() (ligne 5) : NFD decomposition + remove accents (catégorie Mn) + lowercase
- Double clé dédup : (source, source_id) intra-source + fingerprint cross-source

### Description

- description (JobOffer.55) : Markdown dérivé via html_to_markdown() si HTML source
- description_raw (JobOffer.56) : brut immuable, source de vérité audit
- Nettoyage : _clean.py:11-html_to_markdown() spécifique adapter

---

## Étage 2 — Dédup

`orchestrator/job_search/storage/dedup.py:6-filter_new(conn, offers) -> list[JobOffer]`
- Consomme : sqlite connection + batch JobOffer
- Produit : offres absentes de DB uniquement
- Clé : (source, source_id) + fingerprint
- Invariant : pas de suppression — offres vues restent en base

---

## Étage 3 — Hard filters

`orchestrator/job_search/scoring/filters.py:31-apply_hard_filters(offer, search_criteria, zones) -> (bool, str|None)`
- Consomme : JobOffer, SearchCriteria (locations, contract_types), zones dict
- Produit : (filtered_out, filter_reason)
- Règles :
  - alternance=True → out
  - Stage codes (STA/STG/APP/PRO) in nature_contract → out
  - contract_type non-whiteliste → out
  - Localisation : remote=True+in(locations) OK, else zone match dept|keywords
- Filtrage : persisté avec filtered_out=True (jamais supprimé)

---

## Étage 4 — LLM Extract

`orchestrator/job_search/scoring/extractor.py:106-extract_facts(offer, model, host) -> ExtractedFacts`
- Consomme : JobOffer + Ollama model (env OLLAMA_MODEL, host)
- Produit : ExtractedFacts
- Appelé une seule fois par offre à l'ingestion
- Température : 0.1 (JSON stable)
- Few-shot : 3 exemples intégrés (lignes ~57-80)
- Parsing défensif : 2 retries (3 tentatives), fallback ExtractedFacts(parse_failed=True, techs=[], domain="other")
- Fallback jamais exception LLM non-catchée

**Traçabilité** : `orchestrator/job_search/scoring/tracing.py:18-class LLMTrace`
- Append JSONL data/traces/extract_facts.jsonl
- Sauvegarde : prompt complet, réponse brute, facts parsés, timestamp
- Immuable (audit, vocabulaire brut LLM préservé)
- Canonicalisation appliquée étage 5 seulement, jamais trace

---

## Étage 5 — Scoring Python pur (0 LLM)

### Profil YAML mutable

`orchestrator/job_search/matching/profile.py:56-load_profile(path) -> tuple[Profile, str]`
- Consomme : fichier YAML
- Produit : (Profile validé Pydantic, sha256_hex)

**Profile** (profile.py:36-43)
- profile_id: str
- role_ceiling: RoleCeiling (ic|lead|manager)
- seniority_ceiling: SeniorityLevel | None
- skills: dict[str, SkillEntry] où SkillEntry = {level: 1-10, desire: 0-10}
- zones: dict[str, Zone] où Zone = {insee: [code], dept: [prefix], keywords: [str]}
- search_criteria: SearchCriteria (keywords, domains, locations, contract_types)

**Exemple** : `profiles/gregoire.yaml`
- ~50 skills (python, fastapi, langgraph, rag, llm, vue, nuxt, java, docker, git, sql, langchain, chromadb, sqlite, kubernetes, typescript, javascript, react, html, css, spring, pydantic, ollama, n8n, langfuse, mcp, supabase, agents, nlp, ml, postgresql, mysql, …)

### Alias canonicalisation

`orchestrator/job_search/scoring/aliases.py:24-load_alias_table(path) -> AliasTable`
- Consomme : profiles/alias.yaml
- Produit : AliasTable (canonicalisations + exclusions)
- Application : étage 5 scoring seulement, jamais ingest/trace

`canonicalize(tech, table) -> str | None` (ligne 56)
- Variante → canonical ou None (exclu)

### Désirabilité (offre m'intéresse-t-elle ?)

`orchestrator/job_search/scoring/desirability.py:72-compute_desirability(facts, criteria, profile, table) -> Desirability`
- Formule : domain_gradient × desire_factor × 100
- _domain_score() (ligne 64) : gradient distance cœur-cible
  - _DOMAIN_GRADIENT (lignes 20-29) : ai_engineering 1.0, data_science 0.4, data_engineering 0.5, backend 0.5, fullstack 0.25, devops 0.2, embedded 0.1, other 0.0
- _desire_factor() (ligne 41) : moyenne desire profil sur techs offre
  - Inconnu=1.0 neutre, desire=0 tout connu→_DESIRE_FLOOR (0.5), desire=10→1.0
  - Techs exclues (alias) ignorées
- Retour : Desirability(score 0-100, detail dict)

### Atteignabilité (puis-je décrocher maintenant ?)

`orchestrator/job_search/scoring/attainability.py:171-compute_attainability(facts, profile, table) -> Attainability`
- Matching : recouvrement listes, architecture.md §4
- Poids importance (lignes 31-35) : core 3.0, required 2.0, nice_to_have 0.5 (calibrables → DECISIONS.md)
- _compute_attain_tech() (ligne 62) : moyenne pondérée niveaux-profil / poids
  - Absent=0 (neutre), exclu (alias)=retiré calcul
  - Dédup canon : N tokens bruts→1 canonical (max importance), tokens conservés matched/missing
  - Retour : (score 0-100, matched[], missing[])
- _compute_attain_role() (ligne 129) : ic/lead/manager vs role_ceiling profil → 100→0 linéaire
- _compute_seniority_malus() (ligne 153) : malus par cran au-dessus seniority_ceiling
  - SENIORITY_MALUS_PER_STEP = 20 (ligne 23)
- Score final : min(attain_tech, attain_role) − seniority_malus → 0-100 (min non-compensatoire)
- Retour : Attainability(score, attain_tech, attain_role, seniority_malus, techs_matched, techs_missing, blocked_by)

### Hors-périmètre (gates post-scoring)

`orchestrator/job_search/scoring/hors_perimetre.py:44-derive_hors_perimetre(facts, title, description, …) -> list[HorsPerimetreCause]`
- Retour : liste causes (pas booléen) → observable
- Causes (ligne 18) : no_tech, mgmt_role, langue, contrat, …
- Appliquée APRÈS d/a calcul → scores d/a persistés intacts (observabilité)
- Gatée ≠ supprimée : persistée perimetre_causes JSON

### Catégorisation

`orchestrator/job_search/scoring/categorize.py:22-categorize(desirability, attainability) -> Category`
- Seuils : DESIRABILITY_THRESHOLD 50, ATTAINABILITY_THRESHOLD 40
- Catégories (enum, ligne 10) : parfait, reve, atteignable, hors
- Règle : min(d>50, a>40) non-compensatoire

---

## Étage 6 — Persistance

### Schéma SQLite

`orchestrator/job_search/storage/db.py:13-init_db(conn)` crée 3 tables + indices

**Table offers** (lignes 15-38 + migrations 62-119)
- Clé : (source, source_id) UNIQUE → UPSERT
- Brutes : title, company, location, remote, contract_type, nature_contract, alternance, full_time, company_size, experience_required, rome_code, rome_label, url, fetched_at
- Contenu : description (MD), description_raw (brut)
- LLM : extracted_facts_json (ExtractedFacts, une fois à l'ingest)
- Scoring : category, techs_matched_json, techs_missing_json, perimetre_causes (JSON list)
- Interaction : seen_candidat, verdicts FK, human_reviews FK
- Filtrage : filtered_out, filter_reason
- Audit : rescored_at (timestamp rescore)
- Index : idx_offers_fingerprint

**Table verdicts** (lignes 40-45)
- FK : offer_id
- status : retenu|rejeté|candidaté|masqué|hors_perimetre_ok|hors_perimetre_faux_pos, created_at
- Statut humain global, ne recalcule pas offers.extracted_facts_json

**Table human_reviews** (lignes 49-57)
- PK : offer_id (TEXT)
- ratings_json : scores humains par-critère (optionnels)
- ai_snapshot_json : copie figée criteria_json moment review → auto-portante post-refonte
- global_audit_text, global_score, seen_at_review, created_at

**Migration schéma** : `migrate_offers_schema()` (ligne 62)
- ALTER TABLE additif (ALTER ADD/RENAME/DROP)
- Supprime anciens champs score, criteria_json Zone A v1
- Supprime anciens champs L5 desirability, attainability, score_in_category, …

### Sauvegarde

`orchestrator/job_search/storage/offers.py:27-save_offer(conn, offer, …)`
- UPSERT offers via (source, source_id)
- Params : JobOffer + filtered_out, filter_reason, extracted_facts, category, techs_matched/missing, perimetre_causes
- Transactionnel + commit + trace log si LLM
- Jamais suppression — offre ingérée = persistée

**StoredOffer** (ligne 10) : projection read depuis DB

---

## Rescore & retraitement

`orchestrator/job_search/rescore.py:16-main()`
- Relance scoring Python (0 LLM) sur offres DB
- Scénario : changement profil YAML, ajustement poids, gate formula
- Lit extracted_facts_json (LLM immuable), recalcule d/a/categorie/hors

`orchestrator/job_search/verdict.py:53-main()`
- Interaction verdict humain (_record_verdict() ligne 36, _list_recent() ligne 16)

---

## Digest

`orchestrator/job_search/digest/formatter.py:24-generate_digest(offers, run_at) -> str`
- Consomme : list[StoredOffer], timestamp optionnel
- Produit : texte Markdown → data/digest_YYYYMMDD_HHMM.txt
- _format_offer() (ligne 10) : rang + summary

---

## API — FastAPI (port 8000)

### Lifecycle & init

`api/main.py:13-_migrate_db()`
- Ajoute colonnes manquantes (idempotent)
- Appliquée lifespan (lignes 28-31)

### Routes offers.py

**Listes & filtres**

`@router.get("/offers")` (ligne 188) : list[OfferRow]
- Params : category, is_hors_perimetre, verdict, sort, order
- Contexte : charge profile/alias (ligne 30)

`@router.get("/offers/{offer_id}")` (ligne 366) : OfferDetail
- Détail complet + extracted_facts, techs_matched/missing

**Verdict humain**

`@router.put("/offers/{offer_id}/verdict")` (ligne 444) : status (204)

`@router.delete("/offers/{offer_id}/verdict")` (ligne 542) : reset (204)

**Calibration**

`@router.put("/offers/{offer_id}/category-review")` (ligne 478) : review (204)
- Écrit categorie_suggeree, categorie_corrigee, remarque, reviewed_at dans `offers` (pas dans human_reviews)

`@router.get("/offers/{offer_id}/review")` (ligne 519) : ReviewOut
- Fetch review + scores IA snapshot

**Dédup**

`@router.post("/offers/check-known")` (ligne 337) : fingerprint bulk check

### Routes traces.py

`@router.get("/traces")` (ligne 95) : list[TraceOut]
- read_traces_raw() (traces_reader.py:19), build_traces_out() (ligne 118)

`@router.get("/traces/counts")` (ligne 89) : dict[str, int]

`@router.put("/traces/{trace_key}/note")` (ligne 117) : annotation

`@router.get("/traces/export")` (ligne 153) : JSONL export

### Routes export.py

`@router.get("/export/offers")` (ligne 31) : Markdown filtré, scores détail, techs

`@router.get("/export/calibration")` (ligne 268) : human vs IA divergences

### Schémas API

**OfferRow** (schemas.py:6) : id, title, company, location, remote, contract_type, category, verdict, seen_candidat, filtered_out, hors_perimetre_reason, categorie_*, etat_review, reviewed_at

**OfferDetail** (schemas.py:45) : OfferRow + source_id, description, url, source, extracted_facts, techs_matched, techs_missing

**ExtractedFactsSchema** (schemas.py:37) : seniority_required, techs_required, domain, role_level, parse_failed

### Helpers

`_derive_review_fields()` (offers.py:141) : dérive categorie_finale, etat_review (non persistés)

---

## Web — Nuxt 4 + Pinia v3

`web/nuxt.config.ts` — apiBase=http://localhost:8000, Tailwind, Pinia v3

Structure : pages/, components/, stores/

---

## Invariants détectés

1. **Sources pluggables** — Toute source → JobOffer. Mapping intra-adapter. Pipeline aval agnostique source brute. Implémentations : FranceTravailSource, RemotiveSource, IndeedFileSource.

2. **Profil YAML source unique** — Pilotage sans code (zones, skills, criteria). load_profile() retourne hash SHA256. Plusieurs profils possibles.

3. **Fingerprint universel cross-source** — sha256[:16](title norm | company | location). Détecte doublons FT ↔ Remotive ↔ Indeed. Centralisée.

4. **LLM une seule fois** — ExtractedFacts persisté à l'ingest. Rescore 0 LLM sur extracted_facts_json. Séparation extractor vs scoring Python pur.

5. **Scoring explicable** — d/a calculés code (architecture.md §3), min() non-compensatoire. Critères + justifs observables.

6. **Trace immuable** — JSONL append-only, vocabulaire LLM brut. Canonicalisation appliquée étage 5 seulement.

7. **Canonicalisation post-extract** — alias.yaml appliquée scorer, jamais ingest/trace.

8. **Parsing défensif** — Fallback ExtractedFacts, jamais exception LLM non-catchée.

9. **Triple persistence** — offers (données IA), verdicts (statut humain), human_reviews (détail review + snapshot IA).

10. **Gate post-scoring** — d/a persistés même si gatée (observabilité). Causes listées (pas booléen).

---

## Tests

`tests/` — 5 fichiers, 147 tests (pytest)

- `test_aliases.py` — canonicalisation alias.yaml
- `test_hors_perimetre.py` — gates hors-périmètre
- `test_html_to_markdown.py` — nettoyage HTML→Markdown
- `test_human_reviews.py` — workflow review humaine
- `test_zones_filters.py` — hard filters localisation + contrat

---

## Fichiers config

- `profiles/gregoire.yaml` — profil cible (skills, zones, search_criteria)
- `profiles/alias.yaml` — alias canonicalisation technos
- `.env` — credentials FT, Ollama config
- `requirements.txt` — dépendances Python
