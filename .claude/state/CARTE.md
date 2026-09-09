# CARTE FACTUELLE V2 — job-search

> Produite le 2026-07-15 par lecture exhaustive du code.
> Chaque ligne est un fait vérifiable (fichier:ligne). Aucun jugement, aucune référence normative.
> Remplace la CARTE V1 du 2026-07-13. Intègre les nettoyages post-CARTE-V1 (chantier S).

---

## 1. Points d'entrée (8)

| # | Nom | Fichier | Invocation |
|---|-----|---------|------------|
| E1 | FastAPI app | `api/main.py` | `uvicorn api.main:app` |
| E2 | Orchestrator run | `orchestrator/job_search/run.py` | `python -m orchestrator.job_search.run [--profile] [--max] [--since-hours] [--no-remotive] [--no-indeed]` |
| E3 | Rescore | `orchestrator/job_search/rescore.py` | `python -m orchestrator.job_search.rescore [--profile] [--dry-run] [--force] [--re-extract]` |
| E4 | Verdict CLI | `orchestrator/job_search/verdict.py` | `python -m orchestrator.job_search.verdict [--offer-id N --status S]` ou interactif |
| E5 | Audit profil | `audit_profil.py` | `python audit_profil.py` |
| E6 | Backfill description_raw | `backfill_description_raw.py` | `python backfill_description_raw.py [--dry-run]` |
| E7 | Replay traces | `replay_traces.py` | `python replay_traces.py [--n N] [--seed S]` |
| E8 | Migrate seen | `scripts/migrate_seen.py` | `python scripts/migrate_seen.py` |

---

## 2. Traces par entrée

### E1 — FastAPI app (`api/main.py`)

**Startup** : `_migrate_db()` ouvre SQLite (`paths.DB_PATH`), ajoute colonne `rescored_at TEXT` si absente. Import de `api/traces.py` déclenche `_ensure_trace_notes_table()` (crée table `trace_notes` + colonnes `cause`, `severite` si absentes). CORS autorisé pour `http://localhost:3000`.

**Routers montés** : `offers_router` (`api/offers.py`), `export_router` (`api/export.py`), `traces_router` (`api/traces.py`).

#### E1a — `GET /health`
- Lit : rien
- Écrit : rien
- Retourne : `{"status": "ok"}`

#### E1b — `GET /offers`
- Lit : `offers` LEFT JOIN `verdicts` (SQLite). Params dynamiques : `remote`, `source`, `verdict`, `seen_candidat`, `filtered_out`, `category`, `exclude_category`, `hors_perimetre`, `hp_cause`, `etat_review`, `q` (recherche texte title+company). Tri composite `sort`+`order`.
- Calcule : par ligne, `_derive_review_fields(row)` dérive `categorie_finale` (corrigee ou suggeree), `etat_review` (non_relue/a_revoir/corrigee/validee), `review_stale` (rescored_at > reviewed_at), `suggestion_actuelle` (hors_perimetre ou category). En mémoire, jamais persisté.
- Écrit : rien
- Retourne : liste JSON `OfferRow`

#### E1c — `POST /offers/check-known`
- Lit : body (liste `{title, company, location}`). Calcule `fingerprint()` par item. SELECT fingerprint FROM offers WHERE fingerprint IN (...).
- Écrit : rien
- Retourne : `{"new_indices": [...], "known_count": N, "new_count": N}`

#### E1d — `GET /offers/{offer_id}`
- Lit : SELECT `offers.*`, `verdicts.status` WHERE id=?. Parse `extracted_facts_json`. Charge contexte scoring (lazy, caché module-level) : `profiles/gregoire.yaml` + `profiles/alias.yaml`.
- Calcule : `_parse_facts()` → ExtractedFactsSchema. `_derive_review_fields()`. `_derive_score_breakdown()` : si catégorie connue + facts valides, appelle `compute_desirability()` + `compute_attainability()` pour explication lisible des bloqueurs par axe.
- Écrit : `UPDATE offers SET seen_candidat = 1 WHERE id = ?` (effet de bord de la lecture)
- Retourne : JSON `OfferDetail`

#### E1e — `PUT /offers/{offer_id}/verdict`
- Lit : body `VerdictIn` (status: retenu|rejete|candidate|masque|hors_perimetre_ok|hors_perimetre_faux_pos). SELECT offers.id (existence). SELECT verdicts.id (existant ?).
- Écrit : INSERT ou UPDATE `verdicts` (offer_id, status, created_at)
- Retourne : 204

#### E1f — `DELETE /offers/{offer_id}/verdict`
- Lit : SELECT offers.id (existence)
- Écrit : DELETE FROM verdicts WHERE offer_id = ?
- Retourne : 204

#### E1g — `PUT /offers/{offer_id}/category-review`
- Lit : body `CategoryReviewIn` (categorie_corrigee, remarque). Valide contre {parfait, reve, atteignable, hors, hors_perimetre}. SELECT id, category, hors_perimetre_reason FROM offers.
- Calcule : `suggeree` = "hors_perimetre" si hors_perimetre_reason non null, sinon category
- Écrit : UPDATE offers SET categorie_suggeree, categorie_corrigee, remarque, reviewed_at WHERE id=?
- Retourne : 204

#### E1h — `GET /offers/{offer_id}/review`
- Lit : SELECT * FROM human_reviews WHERE offer_id = ?. Parse ratings_json, ai_snapshot_json.
- Écrit : rien
- Retourne : JSON `ReviewOut`, ou 404

#### E1i — `GET /export/offers`
- Lit : `offers` LEFT JOIN `verdicts` (mêmes filtres que GET /offers). Parse `extracted_facts_json`. Si `include` contient "scores", charge contexte scoring (lazy).
- Calcule : format Markdown. Si "scores" demandé, appelle `compute_desirability()` + `compute_attainability()` à la volée.
- Écrit : rien
- Retourne : PlainText Markdown

#### E1j — `GET /export/calibration`
- Lit : SELECT FROM human_reviews LEFT JOIN offers. Construit `HumanReview` (dataclass `storage/reviews.py`). Appelle `disagreement()` (`calibration/disagreement.py`).
- Calcule : `disagreement()` = fonction pure : parse ratings_json + ai_snapshot_json, calcule abs(human-ai) par critère, moyenne par axe, `distance_total`. Tri par distance décroissante. Optionnellement calcule d/a à la volée. Format Markdown paginé (15/page).
- Écrit : rien
- Retourne : PlainText Markdown

#### E1k — `GET /traces/counts`
- Lit : fichier `data/traces/extract_facts.jsonl` via `read_traces_raw()` (parse JSONL, skip lignes corrompues). Groupe par offer_id.
- Retourne : `{source_id: count}`

#### E1l — `GET /traces`
- Lit : fichier `data/traces/extract_facts.jsonl`. Batch SELECT source_id, title, company FROM offers (enrichissement). SELECT trace_notes (annotations).
- Calcule : `build_traces_out()` construit `TraceOut` avec enrichissement offre + merge annotations. Tri par (offer_id, timestamp).
- Retourne : liste JSON `TraceOut`

#### E1m — `PUT /traces/{trace_key}/note`
- Lit : body `TraceNoteIn` (note, cause, severite). Valide cause ∈ {troncature, bug_llm, ok}, severite ∈ {mineure, majeure, critique}. Lit JSONL pour trouver la trace correspondante.
- Écrit : UPSERT `trace_notes` (INSERT ... ON CONFLICT DO UPDATE)
- Retourne : `{trace_key, note, cause, severite}`

#### E1n — `GET /traces/export`
- Lit : fichier `data/traces/extract_facts.jsonl` + table `trace_notes`.
- Calcule : merge trace + annotation par ligne
- Retourne : streaming JSONL (`traces_annotated.jsonl`)

---

### E2 — Orchestrator run (`orchestrator/job_search/run.py`)

**Lit :**
- `.env` (dotenv), env vars : `OLLAMA_MODEL` (défaut "llama3"), `OLLAMA_HOST` (défaut "http://localhost:11434"), `FRANCE_TRAVAIL_CLIENT_ID`, `FRANCE_TRAVAIL_CLIENT_SECRET`
- Profile YAML (défaut `profiles/gregoire.yaml`) → modèle `Profile`
- Alias YAML (`profiles/alias.yaml`) → `AliasTable`
- SQLite `offers` (pour dédup : SELECT source, source_id, fingerprint)
- Indeed JSONL : `data/indeed_inbox/*.jsonl`
- API France Travail (OAuth2 token + GET offres)
- API Remotive (GET remote-jobs)

**Chaîne d'appels :**

1. `load_profile(args.profile)` — lit YAML, valide Pydantic `Profile`, retourne (Profile, sha256)
2. `load_alias_table(ALIAS_PATH)` — lit alias.yaml, construit index inverse, détecte doublons
3. `get_connection()` + `init_db(conn)` — ouvre SQLite, crée tables si absentes, migrations (~20 colonnes ajoutées, colonnes legacy droppées)
4. **Résolution zones** — `active_zones = {name: profile.zones[name] for name in profile.search_criteria.locations if name != "remote"}`. Extrait `ft_codes = [(zone, code) for zone in active_zones.values() for code in zone.insee]`.
5. **Build sources :**
   - 1 `FranceTravailSource(keywords=profile.search_criteria.keywords, commune=code)` par code INSEE extrait à l'étape 4
   - `RemotiveSource()` (sauf `--no-remotive`)
   - `IndeedFileSource()` (sauf `--no-indeed`)
6. **Fetch** — par source : `source.fetch()` → `list[JobOffer]`
   - France Travail : OAuth2 POST token → GET paginé `api.francetravail.io`. Mapping `_map()` → `JobOffer`. `_detect_remote()` par scan mots-clés. Fingerprint calculé.
   - Remotive : GET `remotive.com/api/remote-jobs?category=software-dev&limit=100`. HTML→Markdown via `html_to_markdown()`. `remote=True` forcé. Fingerprint.
   - Indeed : lit `data/indeed_inbox/*.jsonl`. Parse, map → `JobOffer`. HTML→Markdown. Fingerprint.
7. `filter_new(conn, all_offers)` — SELECT tous (source, source_id, fingerprint). Filtre offres dont (source, source_id) ou fingerprint existe déjà. Guard intra-batch.
8. **Par offre nouvelle :**
   - `apply_hard_filters(offer, criteria, zones)` → si filtrée : `save_offer(filtered_out=True, filter_reason=...)`, passe à la suivante
   - `extract_facts(offer, model, host)` — appel LLM Ollama (POST `{host}/api/chat`). Prompt système + 3 few-shot + title + description[:8000]. Retries ×2. Trace JSONL en append. Retourne `ExtractedFacts`.
   - `compute_desirability(facts, criteria, profile, alias_table)` — Python pur : domain_gradient × desire_factor × 100
   - `compute_attainability(facts, profile, alias_table)` — Python pur : max(0, min(attain_tech, attain_role) − seniority_malus)
   - `derive_hors_perimetre(facts, title, description, ...)` — si causes : `save_offer(perimetre_causes=...)`, passe à la suivante
   - `categorize(d.score, a.score)` — seuils d>50, a>40
   - `save_offer(category, techs_matched, techs_missing)` — UPSERT `offers`
9. **Digest** : `get_offers_since(conn, since)` → `generate_digest(scored, run_at)` → fichier + stdout

**Écrit :**
- SQLite `offers` : UPSERT par offre
- Fichier `data/traces/extract_facts.jsonl` : 1 ligne JSONL par appel LLM
- Fichier `data/digest_{YYYYMMDD_HHMM}.txt`
- stdout : logs

---

### E3 — Rescore (`orchestrator/job_search/rescore.py`)

**Lit :**
- `.env`, env vars (OLLAMA_MODEL, OLLAMA_HOST)
- Profile YAML, alias YAML
- SQLite `offers` : SELECT 19 colonnes WHERE filtered_out=0. Sans `--force` : seulement rows sans category ni hors_perimetre_reason. Avec `--force` : tous non-filtrés. Lit `extracted_facts_json`.

**Chaîne :**
1. `load_profile()`, `load_alias_table()`, `get_connection()`, `init_db()`
2. SELECT offres selon condition
3. Construit clés canoniques profil (pour rapport unmatched)
4. **Par offre :**
   - Reconstruit `JobOffer` depuis row DB
   - `apply_hard_filters()` — si filtrée : `save_offer(filtered_out=True)` (sauf --dry-run)
   - Réutilise `extracted_facts_json` caché si disponible et pas `--re-extract`. Sinon `extract_facts()` (appel LLM) + trace JSONL.
   - Pour chaque tech : canonicalize, track unmatched dans Counter
   - `compute_desirability()`, `compute_attainability()`, `derive_hors_perimetre()`, `categorize()`
   - `save_offer(category, techs_matched, techs_missing)` (sauf --dry-run)

**Écrit :**
- SQLite `offers` : UPSERT par offre (sauf --dry-run)
- Fichier `data/traces/extract_facts.jsonl` : si `--re-extract` ou pas de facts cachés
- Fichier `data/unmatched_techs.txt` : rapport fréquence techs non reconnues (toujours écrit)
- stdout

---

### E4 — Verdict CLI (`orchestrator/job_search/verdict.py`)

- Mode non-interactif (--offer-id + --status) : SELECT id, title FROM offers WHERE id=?. INSERT INTO verdicts.
- Mode interactif : SELECT id, title, company, category LIMIT 30. Lecture stdin. INSERT INTO verdicts.
- Statuts CLI : {retenu, rejete, candidate} (sous-ensemble des statuts API)

---

### E5 — Audit profil (`audit_profil.py`)

- Lit : Profile YAML (raw skills keys via yaml.safe_load). Alias YAML. SQLite `offers` (extracted_facts_json, category).
- Par offre : parse facts, itère techs_required. Canonicalise (excluded→skip). Agrège stats par tech canonique. Classifie : couverte / alias_suspect (Levenshtein ≤ 2) / absente. Impact = core×3 + required×2 + nice_to_have×1.
- Écrit : `audit-profil.md`, `audit-profil.csv`, stdout.

---

### E6 — Backfill description_raw (`backfill_description_raw.py`)

- Lit : SQLite `offers` WHERE description_raw IS NULL.
- Par offre : raw = description, md = html_to_markdown(raw).
- Écrit : UPDATE offers SET description_raw=raw, description=md. stdout.

---

### E7 — Replay traces (`replay_traces.py`)

- Lit : `.env`, env vars. SQLite `offers` WHERE filtered_out=0 AND description IS NOT NULL.
- Échantillon aléatoire de n offres (défaut 20). Par offre : reconstruit JobOffer, `extract_facts()` (appel LLM).
- Écrit : `data/traces/extract_facts.jsonl` (append). stdout. Ne modifie PAS la table offers.

---

### E8 — Migrate seen (`scripts/migrate_seen.py`)

- Lit : PRAGMA table_info(offers).
- Écrit : ALTER TABLE offers ADD COLUMN seen (idempotent). stdout.

---

## 3. Lignage de la donnée offre

```
Source externe (FT API / Remotive API / Indeed JSONL)
    │
    ▼
[Étage 1 — Fetch]  adapter.fetch() → list[JobOffer]
    │  Chaque adapter mappe payload natif → JobOffer
    │  description + description_raw remplis
    │  fingerprint = sha256(normalize(title)|normalize(company)|normalize(location))[:16]
    │
    ▼
[Étage 2 — Dédup]  filter_new(conn, offers) → list[JobOffer] filtrée
    │  Double clé : (source, source_id) en base + fingerprint cross-source
    │  Guard intra-batch inclus
    │
    ▼
[Étage 3 — Hard filters]  apply_hard_filters(offer, criteria, zones)
    │  Contrat : alternance/stage/codes exclus + whitelist contract_types
    │  Localisation : remote∩locations OU dept prefix OU zone keywords
    │  Si filtrée → save_offer(filtered_out=True, filter_reason=...) → FIN
    │
    ▼
[Étage 4 — Extraction LLM]  extract_facts(offer, model, host) → ExtractedFacts
    │  1 appel Ollama par offre. Prompt + 3 few-shot. Retries ×2.
    │  Produit : seniority_required, techs_required (avec importance),
    │           domain, role_level, langues_requises, parse_failed
    │  Trace JSONL → data/traces/extract_facts.jsonl (append-only)
    │
    ▼
[Étage 5 — Scoring Python pur]
    │  compute_desirability(facts, criteria, profile, alias_table)
    │    → domain_gradient × desire_factor × 100
    │  compute_attainability(facts, profile, alias_table)
    │    → max(0, min(attain_tech, attain_role) − seniority_malus)
    │  derive_hors_perimetre(facts, title, desc, ...)
    │    → list[HorsPerimetreCause]  (no_tech | mgmt_role | langue | contrat)
    │  categorize(d.score, a.score)
    │    → parfait (d>50 ∧ a>40) | reve | atteignable | hors
    │
    ▼
[Étage 6 — Persistance]  save_offer(conn, offer, ...)
    │  UPSERT dans offers ON CONFLICT(source, source_id)
    │  Colonnes : extracted_facts_json, category, techs_matched_json,
    │            techs_missing_json, hors_perimetre_reason, perimetre_causes,
    │            filtered_out, filter_reason, rescored_at
    │
    ▼
[API — Lecture]  GET /offers, GET /offers/{id}
    │  Lit colonnes depuis DB. Dérive en mémoire :
    │    categorie_finale, etat_review, review_stale, suggestion_actuelle
    │  GET /offers/{id} recalcule score_breakdown (d + a) à la volée
    │    depuis extracted_facts_json + profil + alias (0 LLM)
    │
    ▼
[Front — Affichage]  Nuxt 4 (localhost:3000)
    │  /           → vue candidat (cibles, gaps, filet, retenues)
    │  /operateur  → vue opérateur (a_traiter, hors_perimetre, tout)
    │  /traces     → viewer traces LLM
```

### Flux d'interaction humaine (sens retour)

```
Front (PUT /offers/{id}/verdict)          → INSERT/UPDATE verdicts
Front (PUT /offers/{id}/category-review)  → UPDATE offers (suggeree, corrigee, remarque, reviewed_at)
Front (PUT /traces/{key}/note)            → UPSERT trace_notes
CLI   (verdict.py)                        → INSERT verdicts
```

### Mapping front → API

| Page front | Endpoint API | Méthode | Usage |
|------------|-------------|---------|-------|
| `/`, `/operateur` | `/offers` | GET | Liste filtrée |
| `/`, `/operateur` | `/offers/{id}` | GET | Détail (marque seen) |
| `/`, `/operateur` | `/offers/{id}/verdict` | PUT | Poser verdict |
| `/`, `/operateur` | `/offers/{id}/verdict` | DELETE | Retirer verdict |
| `/`, `/operateur` | `/traces/counts` | GET | Badge "a des traces" |
| `/operateur` | `/offers/{id}/category-review` | PUT | Review humaine |
| `/operateur` | `/export/calibration` | GET | Ouvre export calibration (nouvel onglet) |
| `/`, `/operateur` | `/export/offers` | GET | Copie Markdown presse-papier |
| `/traces` | `/traces` | GET | Charge toutes les traces |
| `/traces` | `/traces/{key}/note` | PUT | Sauvegarde annotation |
| `/traces` | `/traces/export` | GET | Télécharge JSONL annoté |

### Endpoints sans consommateur front

| Endpoint | Constat |
|----------|---------|
| `GET /health` | Endpoint infra, pas de consommateur front |
| `POST /offers/check-known` | Aucun appel front trouvé (conçu pour le skill MCP Indeed) |
| `GET /offers/{id}/review` | Aucun appel front trouvé |

---

## 4. Sondes

### Sonde A — Localisation : chaque endroit où elle est lue pour inclure/exclure

| # | Fichier:fonction | Champ lu | Logique | Effet |
|---|-----------------|----------|---------|-------|
| A1 | `run.py:main` L59-71 | `profile.zones[name].insee` (tous codes par zone) | Résout zones actives depuis `search_criteria.locations`. Crée 1 `FranceTravailSource` par code INSEE. | Inclusion serveur — filtre géo à la requête API FT (`commune=code, distance=30`) |
| A2 | `france_travail.py:_detect_remote` L20 | `lieuTravail.libelle` + `intitule` + `description` | Scan mots-clés {teletravail, remote, full remote, full-remote} | Positionne `offer.remote = True` |
| A3 | `france_travail.py:_map` L105 | `raw["lieuTravail"]["libelle"]` | Mapping direct | Peuple `offer.location` |
| A4 | `remotive.py:fetch` L18 | `item["candidate_required_location"]` | Mapping direct. `remote=True` forcé pour toutes offres Remotive. | Peuple `offer.location`, `offer.remote` |
| A5 | `indeed_file.py:_map` L50 | `data["location"]`, `data["remote"]` | Mapping direct | Peuple `offer.location`, `offer.remote` |
| A6 | `filters.py:apply_hard_filters` L57-76 | `offer.remote`, `offer.location`, `criteria.locations`, `zones[name].dept`, `zones[name].keywords` | `remote_ok = remote ∧ "remote" ∈ locations`. Sinon : match dept prefix (upper) OU keyword substring (upper). Ni l'un ni l'autre → `(True, "location:hors_zone")` | Exclusion post-fetch (offer marquée filtered_out) |
| A7 | `fingerprint.py:fingerprint` L10 | `location` | Normalisé + hashé avec title+company | Dédup cross-source (pas filtrage) |
| A8 | `api/offers.py:list_offers` L190 | `o.remote` (colonne DB) | Param query `remote` → WHERE | Filtre API (affichage) |
| A9 | `api/offers.py:check_known` L333 | `location` dans body | Calcul fingerprint pour dédup amont | Pas de filtrage |

**Synthèse localisation** : 2 étages de filtrage. (1) Serveur FT : param `commune` + `distance` à la requête, un appel par code INSEE depuis `profile.zones`. (2) Client `apply_hard_filters` : dept prefix + keywords depuis `profile.zones`. Source unique de vérité = `profile.zones` + `search_criteria.locations` dans le profil YAML.

---

### Sonde B — Alias / canonicalisation : chaque endroit où elle est appliquée

**Source de vérité** : `profiles/alias.yaml` (28 formes canoniques + 8 exclusions). Chargé par `scoring/aliases.py:load_alias_table()`.

**Fonction `canonicalize(tech, table)`** (`scoring/aliases.py:56`) : normalized → exclude=None, index=canonical, inconnu=self.

| # | Fichier:fonction | Donnée source | Transformation | Sortie |
|---|-----------------|---------------|----------------|--------|
| B1 | `attainability.py:_canonical_profile_skills` L38 | `profile.skills` items | `canonicalize(name)` par skill | `{canonical: level}` |
| B2 | `attainability.py:_canonical_profile_desires` L50 | `profile.skills` items | `canonicalize(name)` par skill | `{canonical: desire}` |
| B3 | `attainability.py:_compute_attain_tech` L62 | `facts.techs_required` | `canonicalize(tech.name)` par tech. None→skip. Dédup canonical. Lookup profil. | (score, matched, missing) |
| B4 | `desirability.py:_desire_factor` L41 | `facts.techs_required` + desires | `canonicalize(t.name)` par tech. None→skip. Lookup desire. | float [0.5, 1.0] |
| B5 | `rescore.py:main` L70-74 | `profile.skills` keys | `canonicalize(k)` pour construire `canonical_profile_keys` | set pour rapport unmatched |
| B6 | `rescore.py:main` L127-131 | `facts.techs_required` par offre | `canonicalize(t.name)`. Si non dans index ni profil → count unmatched | Counter → `data/unmatched_techs.txt` |
| B7 | `api/offers.py:_load_scoring_context` L30 | `profiles/alias.yaml` | `load_alias_table()`, caché module-level | Contexte pour score_breakdown |
| B8 | `api/export.py:_compute_scores_line` L208 | idem B7 | Via `compute_desirability` + `compute_attainability` | Scores dans export Markdown |
| B9 | `audit_profil.py:main` L84 | `facts.techs_required` | `canonicalize(raw, alias_table)`. None→skip. | Stats agrégées par tech canonique |

**`load_alias_table()` appelé depuis** : run.py, rescore.py, api/offers.py (caché), audit_profil.py, tests/test_aliases.py.

**Synthèse canonicalisation** : appliquée au scoring (étage 5) et à l'affichage (API score_breakdown, export). Jamais à l'ingestion ni à la trace JSONL. Techs inconnues auto-canonicalisées, surfacées dans `unmatched_techs.txt` au rescore.

---

### Sonde C — Frontières réelles entre modules (graphe d'imports cross-groupe)

```
sources/          ← leaf (0 dépendance cross-groupe)
    ▲
    │
matching/         ← dépend de sources/ (SeniorityLevel type)
    ▲
    │
scoring/          ← dépend de sources/ (types), matching/ (Profile, SearchCriteria, Zone)
    ▲               import interne : desirability → attainability (_canonical_profile_desires)
    │
storage/          ← dépend de sources/ (JobOffer), scoring/ (Category enum), paths
    ▲
    │
calibration/      ← dépend de storage/ (HumanReview)
    ▲
    │
api/              ← dépend de tout : paths, matching, scoring, sources, storage, calibration
```

**`paths.py`** importé par : scoring/tracing, storage/db, api/db, api/traces_reader, api/offers, run.py, rescore.py, audit_profil.py. Point d'entrée unique des chemins fichier (DB_PATH, TRACES_PATH, ALIAS_PATH, PROFILE_PATH).

**api/ → orchestrator/ (imports cross-boundary)** :
- `api/offers.py` : `load_profile`, `load_alias_table`, `compute_desirability`, `compute_attainability`, `canonicalize`, `fingerprint`, `ExtractedFacts`
- `api/export.py` : `HumanReview`, `disagreement`, `DisagreementScore`, `ExtractedFacts`, `compute_desirability`, `compute_attainability`
- `api/traces_reader.py` : `TRACES_PATH`

**Import interne scoring/** : `desirability.py` importe `_canonical_profile_desires` depuis `attainability.py`. Fonction utilitaire partagée.

---

### Sonde D — Chaque score affiché, remonté au lieu de calcul, présence/absence LLM

| Donnée affichée | Lieu de calcul | Persistée ? | LLM dans la chaîne ? |
|----------------|----------------|-------------|----------------------|
| `category` | `scoring/categorize.py:categorize()` | Oui (`offers.category`) | Non. Consomme d et a qui consomment ExtractedFacts (LLM à l'ingestion). |
| `desirability` (score) | `scoring/desirability.py:compute_desirability()` | Non (colonnes droppées) | Non. Recalculé à la volée en API. |
| `attainability` (score) | `scoring/attainability.py:compute_attainability()` | Non (colonnes droppées) | Non. Recalculé à la volée en API. |
| `techs_matched` | `scoring/attainability.py:_compute_attain_tech()` | Oui (`offers.techs_matched_json`) | Non |
| `techs_missing` | idem | Oui (`offers.techs_missing_json`) | Non |
| `hors_perimetre_reason` | `scoring/hors_perimetre.py:derive_hors_perimetre()` | Oui (`offers.hors_perimetre_reason`) | Non |
| `perimetre_causes` | idem | Oui (`offers.perimetre_causes`) | Non |
| `score_breakdown` | `api/offers.py:_derive_score_breakdown()` | Non (dérivé à la volée) | Non |
| `extracted_facts` | `scoring/extractor.py:extract_facts()` | Oui (`offers.extracted_facts_json`) | **Oui** — unique appel LLM (Ollama, 1×/offre, ingestion) |
| `categorie_finale` | `api/offers.py:_derive_review_fields()` | Non (dérivé en mémoire) | Non |
| `etat_review` | idem | Non | Non |
| `suggestion_actuelle` | idem | Non | Non |
| `review_stale` | idem | Non | Non |

**Synthèse** : un seul appel LLM dans tout le pipeline (`extract_facts`, Ollama, à l'ingestion). Tout le scoring aval est Python pur. Au rescore, les facts sont réutilisés depuis la DB (sauf `--re-extract`). L'API recalcule d et a à la volée depuis les facts persistés.

---

## 5. Duplications et sources de vérité de facto

### 5.1 Écritures dans `offers` — 2 écrivains principaux + 4 secondaires

| Écrivain | Colonnes touchées | Déclencheur |
|----------|-------------------|-------------|
| `run.py` via `save_offer()` | Toutes colonnes offre + scoring | Ingestion quotidienne |
| `rescore.py` via `save_offer()` | Mêmes colonnes (UPSERT) | Rescore manuel |
| `api/offers.py:get_offer` | `seen_candidat` | Effet de bord de la lecture détail |
| `api/offers.py:upsert_category_review` | `categorie_suggeree, categorie_corrigee, remarque, reviewed_at` | Review humaine |
| `backfill_description_raw.py` | `description, description_raw` | Migration one-shot |
| API startup `_migrate_db()` | Schéma (ADD COLUMN rescored_at) | Démarrage API |

### 5.2 Écritures dans `verdicts` — 2 écrivains, ensembles de statuts différents

| Écrivain | Opération | Statuts possibles |
|----------|-----------|-------------------|
| `api/offers.py:upsert_verdict` | INSERT/UPDATE | {retenu, rejete, candidate, masque, hors_perimetre_ok, hors_perimetre_faux_pos} |
| `verdict.py:_record_verdict` | INSERT seulement | {retenu, rejete, candidate} |

### 5.3 Scoring recalculé en 3 endroits (même fonction importée)

1. `run.py` L103-106 (ingestion)
2. `rescore.py` L133-134 (rescore)
3. `api/offers.py` L77-85 + `api/export.py` L228-238 (à la volée pour score_breakdown et export)

Pas de duplication de logique (c'est le même import), mais recalcul effectif à chaque appel API détail/export.

### 5.4 Profil et alias : chargés indépendamment en 4 endroits

`load_profile()` : run.py, rescore.py, api/offers.py (caché module-level).
`load_alias_table()` : run.py, rescore.py, api/offers.py (caché), audit_profil.py.

Chaque process a sa propre copie en mémoire. Pas de cache partagé inter-process.

### 5.5 categorie_suggeree : snapshot tardif

`categorie_suggeree` est écrite dans `offers` uniquement lors de la review humaine (api/offers.py `upsert_category_review`). Elle snapshot `hors_perimetre_reason` ou `category` au moment de l'appel. Elle n'est PAS écrite par `save_offer` à l'ingestion/rescore.

### 5.6 Champs dérivés : calculés à chaque réponse API, jamais persistés

`categorie_finale`, `etat_review`, `review_stale`, `suggestion_actuelle` sont dérivés dans `_derive_review_fields()` à chaque GET /offers et GET /offers/{id}. Ils n'existent pas comme colonnes SQLite.

### 5.7 Init DB et migrations — 3 chemins

| Chemin | Fonction | Quand |
|--------|----------|-------|
| `storage/db.py:init_db()` | CREATE TABLE + `migrate_offers_schema()` (~20 colonnes, drop legacy) | run.py, rescore.py, verdict.py, backfill |
| `api/main.py:_migrate_db()` | ADD COLUMN rescored_at | Démarrage API (lifespan) |
| `api/traces.py:_ensure_trace_notes_table()` | CREATE TABLE trace_notes + ADD COLUMN cause, severite | Import module traces |

---

## 6. Zones mortes / non-couvert

### 6.1 Modules et fonctions non appelés en production

| Item | Fichier | Constat |
|------|---------|---------|
| `verdict.py` (module entier) | `orchestrator/job_search/verdict.py` | Standalone CLI uniquement. Zéro import depuis un autre module. L'API a ses propres endpoints verdict. |
| `storage/reviews.py:upsert_review()` | `orchestrator/job_search/storage/reviews.py` | Appelé seulement par tests. Aucun code de production ne l'appelle. |
| `storage/reviews.py:get_review()` | idem | Appelé seulement par tests. L'API `GET /offers/{id}/review` fait son propre SELECT. |
| `Profile.tech_level()` | `matching/profile.py` | Défini, jamais appelé. Le scoring accède `profile.skills[name].level` via `_canonical_profile_skills()`. |
| `Profile.tech_desire()` | `matching/profile.py` | Défini, jamais appelé. Le scoring accède via `_canonical_profile_desires()`. |
| `HorsPerimetreReason` | `scoring/hors_perimetre.py` | Alias de compat (`= HorsPerimetreCause`). Aucun import trouvé dans le code. |

### 6.2 Endpoints API sans consommateur front

| Endpoint | Constat |
|----------|---------|
| `GET /health` | Endpoint infra, pas de consommateur front |
| `POST /offers/check-known` | Aucun appel front (conçu pour skill MCP Indeed) |
| `GET /offers/{id}/review` | Aucun appel front |

### 6.3 Fichiers écrits jamais relus par le code

| Fichier | Écrivain | Lecteur code |
|---------|----------|-------------|
| `data/unmatched_techs.txt` | `rescore.py` | Aucun (consultation humaine) |
| `data/digest_*.txt` | `run.py` | Aucun (consultation humaine) |
| `audit-profil.md` | `audit_profil.py` | Aucun (consultation humaine) |
| `audit-profil.csv` | `audit_profil.py` | Aucun (consultation humaine) |

### 6.4 Colonne DB écrite jamais lue explicitement

| Colonne | Écrivain | Lecteur |
|---------|----------|---------|
| `offers.description_raw` | `save_offer()`, `backfill_description_raw.py` | Aucune requête SELECT ne lit cette colonne |

---

## 7. État des 3 fermetures

### 7.1 Fermeture Invocation

8 points d'entrée identifiés, 8 tracés jusqu'aux feuilles.

**Statut : FERMÉE.**

### 7.2 Fermeture Atteignabilité

Tous les fichiers Python du projet sont atteints par au moins un point d'entrée :

- Fichiers applicatifs : couverts par les traces E1-E8
- `__init__.py` : package markers vides
- `api/schemas.py`, `sources/base.py`, `scoring/tracing.py` : couverts comme dépendances
- `tests/` : consommateurs, pas des entrées pipeline

**Résidu non élucidé : 0.**

**Statut : FERMÉE.**

### 7.3 Fermeture Données

4 tables SQLite, 2 fichiers YAML source, 4 fichiers data/ réguliers.

| Point de persistance | Écrivain(s) tracé(s) | Lecteur(s) tracé(s) |
|---------------------|---------------------|---------------------|
| offers (34 cols) | save_offer (E2,E3), api R4 (seen), api R7 (review), backfill (E6) | api (R2-R10), rescore (E3), digest (E2), audit (E5), replay (E7), dedup (E2) |
| verdicts | api R5, verdict.py (E4) | api R2,R4,R9 (LEFT JOIN) |
| human_reviews | ? (voir résidu) | api R8, R10 |
| trace_notes | api R13 | api R12, R14 |
| extract_facts.jsonl | scoring/tracing.py (E2, E3, E7) | api R11-R14 |
| digest_*.txt | run.py (E2) | Humain (pas de lecteur code) |
| unmatched_techs.txt | rescore.py (E3) | Humain (pas de lecteur code) |
| indeed_inbox/*.jsonl | Externe (MCP skill) | IndeedFileSource (E2) |
| profiles/gregoire.yaml | Humain | load_profile (E2, E3, API) |
| profiles/alias.yaml | Humain | load_alias_table (E2, E3, API, E5) |

**Résidus ouverts :**

1. **`offers.description_raw`** : écrite par `save_offer()` et `backfill_description_raw.py`, jamais lue par aucune requête SELECT. Donnée écrite sans lecteur.

2. **`verdicts.created_at`** : écrite par les 2 écrivains, jamais incluse dans aucun SELECT (pas dans les projections).

3. **`trace_notes.updated_at`** : écrite à chaque UPSERT, jamais lue dans les requêtes SELECT.

4. **`human_reviews` — écrivain manquant** : le seul écrivain en code est `storage/reviews.py:upsert_review()`, qui n'est appelé que par les tests. Aucune route API ni CLI n'écrit dans cette table. La route R8 (`GET /offers/{id}/review`) la lit ; R7 (`PUT /offers/{id}/category-review`) écrit `categorie_corrigee` dans `offers` mais ne crée pas de row `human_reviews`. L'écrivain effectif de `human_reviews` est hors du code tracé.

**Statut : OUVERTE — 4 résidus listés.**

---

## Annexe — Schéma DB complet

### Table `offers` (34 colonnes)

| Colonne | Type | Notes |
|---------|------|-------|
| id | INTEGER PK | auto |
| source | TEXT NOT NULL | |
| source_id | TEXT NOT NULL | |
| fingerprint | TEXT NOT NULL | |
| title | TEXT | |
| company | TEXT | |
| location | TEXT | |
| remote | INTEGER | bool |
| contract_type | TEXT | |
| nature_contract | TEXT | migration |
| alternance | INTEGER NOT NULL DEFAULT 0 | bool |
| full_time | INTEGER | nullable bool |
| company_size | TEXT | |
| experience_required | TEXT | |
| rome_code | TEXT | |
| rome_label | TEXT | |
| url | TEXT | |
| fetched_at | TEXT | ISO8601 |
| description | TEXT | Markdown |
| description_raw | TEXT | migration, HTML/texte brut |
| seen_candidat | INTEGER NOT NULL DEFAULT 0 | bool |
| extracted_facts_json | TEXT | JSON blob |
| filtered_out | INTEGER NOT NULL DEFAULT 0 | migration, bool |
| filter_reason | TEXT | migration |
| category | TEXT | migration |
| hors_perimetre_reason | TEXT | migration |
| perimetre_causes | TEXT | migration, JSON list |
| categorie_suggeree | TEXT | migration |
| categorie_corrigee | TEXT | migration |
| remarque | TEXT | migration |
| reviewed_at | TEXT | migration |
| techs_matched_json | TEXT | migration, JSON list |
| techs_missing_json | TEXT | migration, JSON list |
| rescored_at | TEXT | migration |

Contraintes : `UNIQUE(source, source_id)`. Index : `idx_offers_fingerprint`.

### Table `verdicts`

| Colonne | Type |
|---------|------|
| id | INTEGER PK |
| offer_id | INTEGER FK offers(id) |
| status | TEXT |
| created_at | TEXT |

### Table `human_reviews`

| Colonne | Type |
|---------|------|
| offer_id | TEXT PK |
| ratings_json | TEXT NOT NULL |
| ai_snapshot_json | TEXT NOT NULL |
| global_audit_text | TEXT |
| global_score | INTEGER |
| seen_at_review | INTEGER NOT NULL DEFAULT 0 |
| created_at | TEXT NOT NULL |

### Table `trace_notes` (créée à l'import `api/traces.py`)

| Colonne | Type |
|---------|------|
| trace_key | TEXT PK |
| offer_id | TEXT NOT NULL |
| note | TEXT NOT NULL DEFAULT '' |
| cause | TEXT | 
| severite | TEXT |
| updated_at | TEXT NOT NULL |

---

*Carte V2 générée le 2026-07-15. Read-only, aucun jugement, aucune correction.*
