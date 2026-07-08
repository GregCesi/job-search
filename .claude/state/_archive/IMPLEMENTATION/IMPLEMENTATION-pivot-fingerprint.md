# IMPLEMENTATION — Dédup amont Indeed (anti rate-limit MCP)

> Invariants `architecture.md` à respecter : §1 (sources pluggables, schéma neutre JobOffer), §4 (0 LLM au scoring/recalcul), §"Persistance séparée".
> Garde-fou structurant : la dédup ici est une **optimisation d'appels MCP**, jamais une décision de stockage — celle-ci reste dans `filter_new()` de `run.py` (cf. `storage/dedup.py`).

## Vue d'ensemble

Rate limit MCP Indeed causé par le volume d'appels Job Detail (1 appel par offre, ~30-50 par session). Solution : ne faire le Detail que sur les offres absentes de la base, via dédup par **fingerprint** avant appel Detail.

**Découverte Phase 0** : `indeed_id` MCP est un compteur séquentiel (`JOBSEARCH_N`), pas un identifiant Indeed stable — dédup par `source_id` impossible avant Detail. Le **fingerprint** (hash titre+entreprise+localisation) est calculable dès les résultats Job Search et cross-source par construction (une offre Indeed identique à une offre France Travail est aussi sautée).

Première chose à attaquer : l'extraction de `_fingerprint()` en module partagé (L0) puis l'endpoint API (L1) — c'est le composant qui débloque le filtrage dans le skill.

---

## Ancrage sur le code (Phase 0 — relecture faite)

| Point | Constat (chemin:ligne) | Conséquence |
|---|---|---|
| indeed_id instable | JSONL existants : `JOBSEARCH_1..30` (fichier 1), `JOBSEARCH_31..60` (fichier 2) — 0 recouvrement | Pivot sur fingerprint obligatoire |
| Champs Job Search | `_raw` keys : `job_id`, `title`, `company`, `location`, `posted_on`, `job_type`, `compensation`, `view_job_url` | title+company+location disponibles dès Job Search |
| `_fingerprint()` | `sources/indeed_file.py:49-53` — NFD + remove Mn + lower + SHA256[:16] sur `title\|company\|location` | Même algo que FT/Remotive, réutilisable côté API |
| `filter_new()` | `storage/dedup.py:6-26` — dédup `(source, source_id)` + `fingerprint` | Pipeline aval = filet final. La dédup amont est un complément |
| `GET /offers` | `api/offers.py:57-63` — filtre `source` supporté, mais ne retourne ni `source_id` ni `fingerprint` | Endpoint insuffisant, besoin d'un endpoint dédié |
| DB `fingerprint` | `storage/db.py:19,38` — `fingerprint TEXT NOT NULL` sur `offers` | Colonne requêtable pour l'endpoint |
| `_fingerprint` portabilité | Défini inline dans chaque source (`indeed_file.py`, `france_travail.py`, `remotive.py`) — même algo, pas de module partagé | Réimplémenter = 4ᵉ copie → interdit. Extraire dans un module partagé ou importer depuis une source existante |

---

## Phase unique — Endpoint + mise à jour skill

Objectif : le skill `/ingest-indeed` ne fait de Job Detail que sur les offres nouvelles, le tout sans toucher à la frontière de stockage ni au pipeline d'ingestion.

- [x] L0 — **Extraction `_fingerprint()` en module partagé** (`orchestrator/job_search/storage/fingerprint.py` ou `sources/fingerprint.py`). Extraire `_normalize()` + `_fingerprint()` depuis une des 3 sources. Les 3 adapters (`indeed_file.py`, `france_travail.py`, `remotive.py`) importent depuis ce module au lieu de définir inline. L'endpoint L1 importe aussi depuis ce module = source de vérité unique, pas de 4ᵉ copie. Done : les 4 importateurs (3 sources + endpoint) utilisent la même fonction, aucune copie inline ne subsiste.
- [x] L1 — **Endpoint `POST /offers/check-known`** dans `api/offers.py`. Reçoit un JSON array de `{"title": "...", "company": "...", "location": "..."}` (les résultats Job Search). Pour chaque entrée, calcule le fingerprint via le module partagé (L0) et vérifie sa présence dans la table `offers`. Retourne `{"new_indices": [0, 3, 5], "known_count": 27, "new_count": 3}`. Read-only (SELECT uniquement). Done : `curl -X POST .../offers/check-known -d '[...]'` retourne les indices des offres inconnues.
- [x] L2 — **Mise à jour de `.claude/commands/ingest-indeed.md`** : entre Job Search et Job Detail, ajouter l'étape de filtrage. Le skill écrit les résultats Job Search dans un fichier temporaire, appelle `curl POST /offers/check-known`, et n'appelle Job Detail que pour les offres dont l'index est dans `new_indices`. Ajouter le throttle de **2-3 secondes entre chaque appel Job Detail — inconditionnellement**, que la dédup amont ait filtré ou non (y compris en fallback API down). Si l'API n'est pas accessible (connection refused), le skill fait le Detail de toutes les offres **avec throttle** (fallback gracieux, log d'avertissement). Done : le skill saute le Detail des offres connues et throttle les appels restants. Le throttle est le dernier rempart anti rate-limit — il ne saute jamais.

```
✋ Verify before continuing:
- [ ] POST /offers/check-known retourne les bons indices pour un jeu de test (offre connue → absente de new_indices, offre inconnue → présente)
- [ ] `_fingerprint()` importé depuis le module partagé (L0) dans les 3 sources + l'endpoint — 0 copie inline
- [ ] Le skill saute effectivement le Detail pour les offres connues (visible dans le log Claude)
- [ ] L'ordre des résultats Job Search est strictement préservé entre l'appel check-known et la boucle Job Detail (`new_indices` = positions, pas ids — tout réordonnancement casse la correspondance)
- [ ] Le JSONL produit ne contient que des offres nouvelles (delta)
- [ ] Throttle 2-3s visible entre les appels Job Detail
- [ ] Fallback : si API down, le skill fait le Detail de toutes les offres **avec throttle** sans crasher
- [ ] filter_new() dans run.py reste le filet final — 0 changement au pipeline d'ingestion
- [ ] Aucune écriture en base par le skill (lecture fingerprints uniquement)

Si tout OK : "go". Sinon dis ce qui cloche.
```

---

## Livrables détaillés

1. **L0 — Extraction fingerprint** — `_fingerprint()` + `_normalize()` dans un module partagé, importé par les 3 sources + l'endpoint. `XS`
2. **L1 — Endpoint check-known** — POST read-only, fingerprint via module partagé (L0), retourne indices des offres nouvelles. `S`
3. **L2 — Skill ingest-indeed v2** — filtrage par fingerprint + throttle 2-3s inconditionnel + fallback si API down. `S`

---

## Dépendances critiques

- L0 bloque L1 (l'endpoint importe le fingerprint partagé).
- L1 bloque L2 (le skill appelle l'endpoint).

Chemin critique : L0 → L1 → L2.

---

## Garde-fous

- **Frontière de stockage (S4)** : le skill lit la base en read-only (fingerprints via endpoint) et n'y écrit jamais. La décision d'ingestion reste dans `run.py` → `filter_new()`. Un doublon passé la dédup amont est attrapé en aval.
- **Source de vérité fingerprint** : `_fingerprint()` vit dans un module partagé unique (L0), importé par les 3 sources + l'endpoint. Réimplémenter (4ᵉ copie inline) est **interdit** — une dérive silencieuse casse la dédup cross-source.
- **Throttle inconditionnel** : le throttle 2-3s entre chaque Job Detail s'applique **toujours**, y compris en fallback (API down → Detail sur toutes les offres). Le throttle est le dernier rempart anti rate-limit — la dédup amont le complète, jamais ne le remplace.
- **Fallback gracieux** : si l'API n'est pas lancée, le skill fait le Detail de toutes les offres avec throttle. La dédup amont est une optimisation, pas un prérequis.
- **Stabilité des indices** : `new_indices` est un tableau de positions dans l'ordre du Job Search original. Le skill ne doit jamais trier, filtrer ou réordonner les résultats entre l'appel `check-known` et la boucle Job Detail.
- **indeed_id reste dans le JSONL** : même instable, le champ `indeed_id` est préservé dans le JSONL (donnée brute). `IndeedFileSource` le mappe en `source_id` avec fallback hash. Aucun changement à l'adapter.
