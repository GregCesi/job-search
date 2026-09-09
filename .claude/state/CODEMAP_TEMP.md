# CODEMAP — job-search

> Carte de retrieval. Générée le 2026-08-25.
> **À copier dans `.claude/docs/CODEMAP.md`.**
> Pointeurs vers le code réel. Ne pas recopier le code. Régénérable — ne pas éditer à la main.

---

## Structure d'ensemble

Le projet implémente un pipeline matinal (orchestrator) + API d'exposition (FastAPI) + frontend (Nuxt 4). Trois briques autour d'une base SQLite partagée (`data/job_search.sqlite`).

**Flux principal** : Fetch multiples sources → Dédup → Filtre dur → LLM extraction (1×) → Scoring Python pur → Persistance UPSERT → Digest (orchestrator). API expose les offres + verdicts. Frontend lit l'API.

---

## Orchester & orchestration

- **Point d'entrée principal** : `orchestrator/job_search/run.py:15()` — CLI matinale (fetch → dédup → score → digest)
- **Chemins canoniques** : `orchestrator/job_search/paths.py` — `REPO_ROOT`, `DB_PATH`, `TRACES_PATH`, `PROFILE_PATH`, `ALIAS_PATH` résolus depuis `__file__`
- **Re-scoring** : `orchestrator/job_search/rescore.py:16()` — relance scoring Python pur sur offres sans catégorie (flags `--force`, `--dry-run`, `--re-extract`)

---

## Schémas & modèles centraux

### Sources & offres neutres
- **Interface Source** : `orchestrator/job_search/sources/base.py:73` — ABC abstraite, méthode `fetch() -> list[JobOffer]`
- **Modèle JobOffer** : `orchestrator/job_search/sources/base.py:50` — schéma unique en sortie d'adapter, jamais le schéma natif source
- **Faits extraits** : `orchestrator/job_search/sources/base.py:27` — `ExtractedFacts` (seniority_required, techs_required, domain, role_level, langues_requises, parse_failed)
- **Énums extraits** : `SeniorityLevel` (junior/intermediate/senior/lead) `orchestrator/job_search/sources/base.py:9`, `RoleLevel` (ic/lead/manager) `orchestrator/job_search/sources/base.py:16`, `TechRequirement` `orchestrator/job_search/sources/base.py:22` (name, importance ∈ {core, required, nice_to_have})

### Profil & matching
- **Profile YAML** : `orchestrator/job_search/matching/profile.py:36` — source unique de pilotage (role_ceiling, seniority_ceiling, skills[nom → {level, desire}], zones, search_criteria)
- **SearchCriteria** : `orchestrator/job_search/matching/profile.py:29` — keywords, domains, locations, contract_types
- **Loader + hash** : `orchestrator/job_search/matching/profile.py:56()` — charge & valide profil YAML, retourne (Profile, sha256_hex)
- **RoleCeiling enum** : `orchestrator/job_search/matching/profile.py:12` — ic/lead/manager

### Alias & canonicalisation
- **AliasTable** : `orchestrator/job_search/scoring/aliases.py:18` — index variante→canonique + set d'exclusions (frozen dataclass)
- **Loader alias** : `orchestrator/job_search/scoring/aliases.py:24()` — charge alias.yaml, détecte doublons via `DuplicateAliasError`
- **Canonicalize** : `orchestrator/job_search/scoring/aliases.py:56()` — variante→canonique, excluded→None, unknown→lowercase auto-canonique

---

## Étage 1 — Fetch (sources pluggables)

### France Travail
- **Adapter FT** : `orchestrator/job_search/sources/france_travail.py:30` — OAuth2 token + pagination + réseau robuste (retry 429)
- **Auth** : `orchestrator/job_search/sources/france_travail.py:51()` — `_get_token()` caching + refresh automatique
- **Pagination** : `orchestrator/job_search/sources/france_travail.py:75()` → `_fetch_all()` `orchestrator/job_search/sources/france_travail.py:99` — par 100s, range-based, gère 429 + 400/500 silent
- **Mapping FT→JobOffer** : `orchestrator/job_search/sources/france_travail.py:117()` — `_map()` interne, accumule description+description_raw, détecte remote via keywords
- **Fetch public** : `orchestrator/job_search/sources/france_travail.py:154()` — par mot-clé (resolve `per_kw` depuis max_results), dédup intra-batch par source_id

### Remotive
- **Adapter Remotive** : `orchestrator/job_search/sources/remotive.py:14` — requête publique https://remotive.com/api/remote-jobs, category=software-dev
- **Mapping** : `orchestrator/job_search/sources/remotive.py:18()` — description HTML→Markdown via `html_to_markdown()`, description_raw = brut HTML source

### Indeed (fichier)
- **Adapter fichier** : `orchestrator/job_search/sources/indeed_file.py:20` — lecture JSONL depuis `data/indeed_inbox/*.jsonl`

### Utils sources
- **Fingerprint** : `orchestrator/job_search/sources/fingerprint.py:10()` — sha256(normalize(title)|normalize(company)|normalize(location))[:16], crochet cross-source
- **HTML→Markdown** : `orchestrator/job_search/sources/_clean.py:11()` — conversion HTML brut Remotive

### Orchestration fetch (run.py)
- **Zones actives** : `orchestrator/job_search/run.py:60` — résolues depuis profil (search_criteria.locations ∩ zones.keys)
- **FT multi-zone** : `orchestrator/job_search/run.py:66` — 1 FranceTravailSource par (zone active × code INSEE), répartition `per_source = max(30, max_results // len(ft_codes))`
- **Sources pluggables** : `orchestrator/job_search/run.py:68` — liste construite selon flags (--no-remotive, --no-indeed)

---

## Étage 2 — Dédup

- **Filtre nouveau** : `orchestrator/job_search/storage/dedup.py:6()` — double clé `(source, source_id)` + fingerprint cross-source, garde en-mémoire intra-batch
- **Base de comparaison** : SELECT sur table `offers` existante

---

## Étage 3 — Filtres durs (localisation + contrat)

- **Apply hard filters** : `orchestrator/job_search/scoring/filters.py:31()` → `(filtered_out, reason)`
- **Règle alternance** : alternance=True → "contract:alternance" (lignes 41-42)
- **Règle codes stage** : _STAGE_CODES = {STA, STG, APP, PRO} → "contract:{code_lower}" (lignes 44-46)
- **Règle keywords stage** : nature_contract contient (stage/apprentissage/alternance) → "contract:stage" (lignes 48-50)
- **Règle types contrat** : si `criteria.contract_types` renseigné, seuls les types mappés (via _CONTRACT_MAP) passent → "contract:{mapped}" (lignes 52-55)
- **Règle localisation** : remote OK si `offer.remote=True` ET `"remote" ∈ criteria.locations` (ligne 58) ; sinon match zone via dept (préfixe) ou keywords (substring) (lignes 60-73) ; sinon → "location:hors_zone" (lignes 75-76)

---

## Étage 4 — Extraction LLM (faits intrinsèques)

- **Extract facts** : `orchestrator/job_search/scoring/extractor.py:106()` — 1 appel Ollama par offre, never raises, retourne fallback `parse_failed=True` sur erreur
- **Ollama config** : host/model depuis env variables `OLLAMA_HOST` (default http://localhost:11434), `OLLAMA_MODEL` (default llama3)
- **System prompt** : `orchestrator/job_search/scoring/extractor.py:29` — instructions strict, JSON seul output, 8 domaines fermés, 4 séniorités, 3 rôles
- **Few-shot** : `orchestrator/job_search/scoring/extractor.py:61` — 3 exemples (IC mixed importance, tech lead + equipe, backend Java)
- **User prompt** : title + description[:8000] + hints optionnels (experience_required, rome_label, alternance)
- **Validation** : coerce v1 (techs_required était list[str] → list[TechRequirement] avec importance="required") `orchestrator/job_search/sources/base.py:36`
- **Tracing** : append JSONL `data/traces/extract_facts.jsonl` (LLMTrace avec prompt+response+facts+timestamp) `orchestrator/job_search/scoring/tracing.py:30()`, jamais modifié après écriture

---

## Étage 5 — Scoring Python pur

### Désirabilité
- **Compute desirability** : `orchestrator/job_search/scoring/desirability.py:72()` → `Desirability(score, detail)`
- **Formule** : `domain_gradient × desire_factor × 100` (ligne 86)
- **Gradient domaine** : _DOMAIN_GRADIENT dict (lines 20-29) — ai_engineering (1.0), data_science (0.4), data_engineering (0.5), backend (0.5), fullstack (0.25), devops (0.2), embedded (0.1), other (0.0)
- **Desire factor** : `_desire_factor()` `orchestrator/job_search/scoring/desirability.py:41` — moyenne envie sur techs connues du profil (inconnu=1.0, avec plancher _DESIRE_FLOOR=0.5)

### Atteignabilité
- **Compute attainability** : `orchestrator/job_search/scoring/attainability.py:171()` → `Attainability(score, attain_tech, attain_role, seniority_malus, techs_matched, techs_missing, blocked_by)`
- **Score final** : `max(0, min(attain_tech, attain_role) − seniority_malus)` (ligne 144)
- **Attain tech** : `_compute_attain_tech()` `orchestrator/job_search/scoring/attainability.py:62` — moyenne pondérée (poids: core=3.0, required=2.0, nice_to_have=0.5) × 10 (0-100)
  - Dedup canonique : si N tokens bruts → même canonical, compte 1× avec importance=max
  - Techno exclue → retirée du calcul
  - Techno inconnue → level=0 (neutre, dilue le score)
- **Attain role** : `_compute_attain_role()` `orchestrator/job_search/scoring/attainability.py:129` — portail gradué (ic→100, lead→40, manager→0 si ceiling=ic ; gap=1→40, gap≥2→0)
- **Seniority malus** : `_compute_seniority_malus()` `orchestrator/job_search/scoring/attainability.py:153` — par cran au-dessus ceiling (SENIORITY_MALUS_PER_STEP=20, lines 22-23)
- **Weights & seuils** : _IMPORTANCE_WEIGHTS `orchestrator/job_search/scoring/attainability.py:31`, _ROLE_ORDER `orchestrator/job_search/scoring/attainability.py:123`, _ATTAIN_ROLE_SCORES `orchestrator/job_search/scoring/attainability.py:126`

### Catégorisation
- **Categorize** : `orchestrator/job_search/scoring/categorize.py:22()` → Category enum (parfait/reve/atteignable/hors)
- **Seuils** : DESIRABILITY_THRESHOLD=50.0, ATTAINABILITY_THRESHOLD=40.0 (lignes 17-19)
- **Matrice** : is_desired×is_attainable → (true,true)=parfait, (true,false)=reve, (false,true)=atteignable, (false,false)=hors

### Hors-périmètre
- **Derive hors perimetre** : `orchestrator/job_search/scoring/hors_perimetre.py:44()` → `list[HorsPerimetreCause]` (empty = in-bounds)
- **Cause no_tech** : techs_required == [] (ligne 56)
- **Cause mgmt_role** : role_level == manager (ligne 60)
- **Cause langue** : regex scan titre+description pour langues tierces (LANGUES_TIERCES, ligne 26) (ligne 64)
- **Cause contrat** : contract_type ∈ {Internship, MIS} OU nature_contract ∈ {Cont. professionnalisation, Contrat apprentissage} OU titre contient alternance/stage/apprentissage/intern (régex) (lignes 69-75)

---

## Étage 6 — Persistance

- **Save offer** : `orchestrator/job_search/storage/offers.py:27()` — UPSERT ON CONFLICT(source, source_id), jamais delete
- **Colonnes clés** : extracted_facts_json, category, filtered_out, filter_reason, perimetre_causes (JSON list), techs_matched_json, techs_missing_json, rescored_at (timestamp)
- **Sync hors_perimetre_reason** : premier élément de perimetre_causes si fourni (ligne 54)

### Schéma DB
- **Tabla offers** : `orchestrator/job_search/storage/db.py:15` — source + source_id unique, fingerprint indexed, extracted_facts_json TEXT, category, hors_perimetre_reason, perimetre_causes (JSON), techs_matched_json, techs_missing_json, rescored_at, + anciens champs dropped (score, criteria_json, desirability*, attainability*, etc.)
- **Table verdicts** : offer_id FK, status, created_at — avis humain global (favori/candidaté/rejeté ou autre)
- **Table human_reviews** : offer_id PK, ratings_json (notation par-critère), ai_snapshot_json (copie figée du criteria_json), global_audit_text, global_score, seen_at_review, created_at
- **Table trace_notes** : trace_key PK, offer_id, note, cause, severite, updated_at — annotations sur traces LLM
- **Init idempotent** : `init_db()` `orchestrator/job_search/storage/db.py:13` crée si absent, `migrate_offers_schema()` `orchestrator/job_search/storage/db.py:62` ajoute colonnes manquantes + renomme (seen→seen_candidat) + drop anciens champs

---

## Digest
- **Generate digest** : `orchestrator/job_search/digest/formatter.py:24()` — texte markdown lisible, offres triées par catégorie
- **Format offre** : `orchestrator/job_search/digest/formatter.py:10()` — rank + title + company + category + techs
- **Persistence** : écrit `data/digest_YYYYMMDD_HHMM.txt` depuis orchestrator

---

## API FastAPI

### Démarrage & middleware
- **App** : `api/main.py:34` — FastAPI(title="job-search-api", lifespan avec migration DB)
- **CORS** : allow_origins=["http://localhost:3000"] (ligne 38)
- **Health** : GET /health `api/main.py:51()`
- **Routers** : offers_router (lignes 45), export_router (ligne 46), traces_router (ligne 47)

### Offres (GET/POST/PUT/DELETE)
- **List offers** : GET /offers `api/offers.py:189()` — filtres query (remote, source, verdict, category, filtered_out, hors_perimetre, hp_cause, etat_review, q) + tri + pagination
- **Get detail** : GET /offers/{id} `api/offers.py:393()` — OfferDetail avec score_breakdown et review_fields dérivés
- **Upsert verdict** : PUT /offers/{id}/verdict `api/offers.py:471()` — VerdictIn(status) → INSERT/UPDATE verdicts
- **Upsert category review** : PUT /offers/{id}/category-review `api/offers.py:505()` — CategoryReviewIn(categorie_corrigee, remarque) → UPDATE offers (categorie_suggeree/corrigee/reviewed_at)
- **Get review** : GET /offers/{id}/review `api/offers.py:546()` — ReviewOut depuis human_reviews (legacy, read-only)
- **Delete verdict** : DELETE /offers/{id}/verdict `api/offers.py:569()` — supprime row verdicts
- **Check known** : POST /offers/check-known `api/offers.py:364()` — batch query (source, source_id, fingerprint) pour dédup front

### Score breakdown (dérivé, jamais persisté)
- **_derive_score_breakdown** : `api/offers.py:49()` — ligne unique expliquant catégorie (blockers attainabilité + domaine)
- **_load_scoring_context** : `api/offers.py:30()` — charge profil + alias table une fois (cache module-level)

### Review fields (dérivés, jamais persistés)
- **_derive_review_fields** : `api/offers.py:141()` — categorie_finale (corrigee OR suggeree), etat_review (non_relue/a_revoir/corrigee/validee), review_stale (rescored_at > reviewed_at)

### Export
- **Export offers** : GET /export/offers `api/export.py:32()` — markdown filtré, include fields à la carte (description, techs, role, domain, category, location, contract, url, company, scores, remarque, verdict)
- **Export calibration** : GET /export/calibration `api/export.py:291()` — human_reviews + disagreement score, trié par désaccord décroissant, lots de 15

### Traces
- **List traces** : GET /traces `api/traces.py:96()` — TraceOut enrichies avec offer_title/offer_company + annotations (note, cause, severite)
- **Traces counts** : GET /traces/counts `api/traces.py:90()` — dict offer_id→count (JSONL reader, 0 LLM)
- **Upsert trace note** : PUT /traces/{key} `api/traces.py:118()` — TraceNoteIn(note, cause, severite) → trace_notes
- **Export traces JSONL** : GET /export/traces.jsonl `api/traces.py:154()` — streaming raw

---

## Schémas API
- **OfferRow** : `api/schemas.py:6` — id, source, title, company, location, remote, category, verdict, seen_candidat, hors_perimetre_reason, filtered_out
- **OfferDetail** : `api/schemas.py:45` — extends OfferRow + description, techs (TechSchema), extracted_facts (ExtractedFactsSchema), score_breakdown, review_fields
- **VerdictIn** : `api/schemas.py:56` — {status: str}
- **CategoryReviewIn** : `api/schemas.py:60` — {categorie_corrigee?: str, remarque?: str}
- **TraceOut** : `api/schemas.py:87` — offer_id, offer_title, offer_company, timestamp, user_prompt, response_raw, parsed_facts, annotation (note/cause/severite)

---

## Frontend Nuxt 4

### Config
- **Nuxt config** : `web/nuxt.config.ts` — Pinia v3 + @nuxtjs/tailwindcss, apiBase=http://localhost:8000

### Pages
- **Index** : `web/app/pages/index.vue` — vue candidat (offres scorées, filtres preset)
- **Operateur** : `web/app/pages/operateur.vue` — vue opérateur (config/review/admin)
- **Traces** : `web/app/pages/traces.vue` — LLM extraction viewer (annotation)

### Stores Pinia
- **Offers store** : `web/app/stores/offers.ts` — fetch + filtrage, VIEW_PRESETS (6 vues préconfigurées)
- **Traces store** : `web/app/stores/traces.ts` — fetch traces JSONL + annotation

### Composants
- **OffersTable** : `web/app/components/OffersTable.vue` — affichage table
- **OfferDetail** : `web/app/components/OfferDetail.vue` — modal détail
- **FiltersPanel** : `web/app/components/FiltersPanel.vue` — filtres contrôlés par store
- **ExportPopover** : `web/app/components/ExportPopover.vue` — export markdown
- **VerdictBadge** : `web/app/components/VerdictBadge.vue` — badge statut

---

## Calibration & désaccord
- **Disagreement score** : `orchestrator/job_search/calibration/disagreement.py:27()` → DisagreementScore (delta techs, delta seniority, delta domain, total) depuis review humaine vs ai_snapshot
- **Distance métrique** : Jaccard sur techs, delta ordinal sur seniority/role, 0/1 sur domain

---

## Invariants détectés

1. **Profil YAML = source unique pilotage** → toute variable d'ingestion (zones, keywords, contrats, seuils de seniority) vit dans profil, code la consomme uniquement
2. **Zéro LLM au rescore** → extraction 1×, réutilisé via extracted_facts_json, rescore est Python pur sur extended_facts ou profile change
3. **Trace brute sacrée** → vocabulary LLM jamais modifié après écriture JSONL, canonicalisation appliquée au scoring seulement
4. **Scoring explicable par construction** → critères atomiques notés séparément, agrégation par code (min non-compensatoire), details persistés
5. **Zéro compensation d'axes** → attainability = max(0, min(attain_tech, attain_role) − malus) — bon tech score ne rachète jamais rôle bloquant
6. **Statuts verdict ≠ review** → verdicts (favori/candidaté/rejeté) et category_review (correction human) sont données d'interaction, jamais intrants de recalcul
7. **Offers jamais supprimées** → filtered_out=True, hors_perimetre_reason NOT NULL, mais row reste en DB
8. **API-driven front** → Pinia stores fetch uniquement, zéro logique métier côté client (matching techs supprimé, catégorie suggestion vient du back)

---

## Points de configuration localisés

- **Seuils scoring** : DESIRABILITY_THRESHOLD=50, ATTAINABILITY_THRESHOLD=40 `orchestrator/job_search/scoring/categorize.py:17-19`
- **Poids importance techs** : core=3.0, required=2.0, nice_to_have=0.5 `orchestrator/job_search/scoring/attainability.py:31-35`
- **Gradient domaine** : _DOMAIN_GRADIENT dict `orchestrator/job_search/scoring/desirability.py:20-29`
- **Malus seniority/step** : SENIORITY_MALUS_PER_STEP=20 `orchestrator/job_search/scoring/attainability.py:23`
- **Portail rôle** : _ATTAIN_ROLE_SCORES=[100, 40, 0] `orchestrator/job_search/scoring/attainability.py:126`
- **Desire floor** : _DESIRE_FLOOR=0.5 `orchestrator/job_search/scoring/desirability.py:38`
- **Domains fermés** : {ai_engineering, data_engineering, data_science, backend, devops, fullstack, embedded, other} `orchestrator/job_search/scoring/extractor.py:89-92`
- **Langues tierces** : LANGUES_TIERCES regex `orchestrator/job_search/scoring/hors_perimetre.py:26-31`
- **Contract codes gate** : _STAGE_CODES={STA, STG, APP, PRO}, _CONTRAT_TYPES_GATE={Internship, MIS} `orchestrator/job_search/scoring/filters.py:17,35`

---

## Points d'entrée exécution

- `python -m orchestrator.job_search.run [--profile PATH] [--max N] [--since-hours H] [--no-remotive] [--no-indeed]`
- `python -m orchestrator.job_search.rescore [--profile PATH] [--dry-run] [--force] [--re-extract]`
- `python -m api.main` (lancé via `uvicorn api.main:app --reload`, port 8000)
- `cd web && npm run dev` (Nuxt dev server, port 3000)

---

## Liens externes

- **France Travail OAuth2** : https://entreprise.francetravail.fr/connexion/oauth2/access_token (token), https://api.francetravail.io/partenaire/offresdemploi/v2/offres/search (search)
- **Remotive API** : https://remotive.com/api/remote-jobs (public, category=software-dev)
- **Ollama local** : http://localhost:11434 (configurable OLLAMA_HOST), modèle via OLLAMA_MODEL
