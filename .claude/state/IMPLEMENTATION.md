# IMPLEMENTATION — TCK-162 Vue candidat — filtre géographique profil de vue

## Vue d'ensemble

Restreindre les 4 onglets de la vue candidat (Cibles, Gaps, Filet, Retenues) aux offres des
zones Belgique et Strasbourg, sans toucher la collecte, la base, ni la vue opérateur. Un nouveau
fichier `profiles/vue_candidat.yaml` désigne les deux zones par leur nom défini dans
`gregoire.yaml` ; l'API traduit cette liste en clauses SQL LIKE appliquées uniquement quand
`view_profile=true` est envoyé ; deux commandes dans `index.vue` (toggle + case remote) pilotent
ces params ; la fuite des filtres candidat vers `/operateur` est fermée.

Première chose à attaquer : le filtre SQL côté API — le front en dépend.

Refs : `rules/architecture.md` §1 (sources pluggables), `rules/pipeline.md` étage 3 (hard
filters), `rules/frontend.md` (VIEW_PRESETS, stores API-driven).

**Écarts constatés en Phase 0 :**
- `belgique_area` a 15 mots-clés dans `gregoire.yaml` (pas 13 comme mentionné dans la recon) —
  aucun impact sur le plan.
- `apply_hard_filters` est déjà une fonction publique à `filters.py:44`. Le plan ne la modifie
  pas : la logique de matching de zone est traduite en SQL dans `api/view_profile.py` (nouveau
  module), garantissant que `filters.py` reste intact et que l'invariant 1 est satisfait par
  construction (git diff vide).
- `scripts/check_zone_invariant.py` va dans `scripts/` (répertoire existant, contient déjà
  `migrate_seen.py`).

---

## Schémas cibles

### `profiles/vue_candidat.yaml`
```yaml
# Profil de vue candidat — désigne des zones de gregoire.yaml sans les redéfinir
zones:
  - belgique_area
  - strasbourg_area
```

### API — nouveaux query params sur `GET /offers` (`api/offers.py`)
```
view_profile: bool | None  # True = appliquer le filtre géo profil de vue
include_remote: bool | None  # True = inclure remote dans le filtre (ignoré si view_profile absent)
```

### Store Pinia — nouvel état dans `useOffersStore` (`stores/offers.ts`)
```typescript
viewProfileActive: Ref<boolean>  // true par défaut, réinitialisé à chaque onMounted de index.vue
includeRemote: Ref<boolean>       // false par défaut, idem
```

Base de travail, pas contrat figé — à affiner au livrable correspondant.

---

## Phases

---

### Phase 1 — Back : profil de vue + filtre SQL

**Objectif** : `GET /offers` accepte `view_profile` et `include_remote` ; le filtre SQL est
construit depuis `vue_candidat.yaml` × zones de `gregoire.yaml` ; `apply_hard_filters` est
inchangé.

- [x] **L0 — `scripts/snapshot_presets.py`** (créer, exécuter AVANT toute modification) :
  appelle `GET /offers` pour chacun des 4 presets candidat (cibles, gaps, filet, retenues) avec
  les params exacts de `VIEW_PRESETS` (sans `view_profile`). Enregistre les sets d'ids dans
  `data/snapshot_presets.json` (hors git : ajouter à `.gitignore`), format
  `{"cibles": [id, ...], "gaps": [...], "filet": [...], "retenues": [...]}`. Done = fichier
  présent, 4 clés, pas d'exception. À exécuter une seule fois avant L1 ; le fichier est le
  référentiel des ✋ "profil inactif = mêmes ids". **XS**

- [x] **L1 — `profiles/vue_candidat.yaml`** (créer) : clé `zones: [belgique_area,
  strasbourg_area]`. Ne recopie aucune définition de zone. Done = fichier présent, `yaml.safe_load`
  sans exception. **XS**

- [x] **L2 — `orchestrator/job_search/paths.py`** : ajouter après la ligne 13
  (`PROFILE_PATH = ...`) la ligne `VUE_CANDIDAT_PATH = REPO_ROOT / "profiles" /
  "vue_candidat.yaml"`. Done = `from orchestrator.job_search.paths import VUE_CANDIDAT_PATH`
  résout sans erreur. **XS**

- [x] **L3 — `api/view_profile.py`** (créer) : module chargé paresseusement avec cache
  module-level `_clauses_cache`. Fonction `build_view_clauses() -> tuple[list[str], list]` :
  charge `VUE_CANDIDAT_PATH`, appelle `load_profile(PROFILE_PATH)` pour obtenir les zones,
  itère sur les noms désignés et construit les conditions SQL — `dept → UPPER(o.location) LIKE
  '67%'` (un `?` par dept) ; `keyword → UPPER(o.location) LIKE '%STRASBOURG%'` (un `?` par
  keyword). Retourne `(conditions, params)` — les conditions sont des OR entre elles (assemblage
  côté appelant). Si `VUE_CANDIDAT_PATH` illisible : lève `FileNotFoundError` avec le chemin. Si
  un nom de zone est absent de `gregoire.yaml` : lève `ValueError(f"zone inconnue : {name}")`.
  Done = `build_view_clauses()` retourne au moins 17 conditions (2 depts strasbourg + 2 keywords
  strasbourg + 15 keywords belgique) et autant de params ; config cassée → exception nommée. **S**

- [x] **L4 — `api/offers.py:list_offers`** : ajouter `view_profile: bool | None = Query(None)`
  et `include_remote: bool | None = Query(None)` à la signature. Dans le bloc de construction des
  conditions (après le bloc `filtered_out`, lignes ~208-214), si `view_profile is True` : appeler
  `from api.view_profile import build_view_clauses; zone_conds, zone_params = build_view_clauses()`.
  Si `include_remote is True` : ajouter `zone_conds.append("o.remote = 1")`. Si `zone_conds` non
  vide : `conditions.append(f"({' OR '.join(zone_conds)})"); params.extend(zone_params)`. Done = 
  `GET /offers?view_profile=true` renvoie uniquement des offres dans les zones ou remote (si
  include_remote=true) ; `GET /offers` (sans view_profile) renvoie le même résultat qu'avant. **S**

- [x] **L5 — `scripts/check_zone_invariant.py`** : script lecture seule DB. Cible uniquement les
  offres `filtered_out = 0` (périmètre des ✋). Calcule deux ensembles d'ids indépendants :
  - **SQL** : exécute `SELECT id FROM offers o WHERE o.filtered_out = 0 AND (<conditions de
    build_view_clauses() jointes par OR>)` avec ses params directement sur `data/job_search.sqlite`.
  - **Python** : pour chaque offre de `filtered_out = 0`, applique la logique de `filters.py`
    l. 71-89 sur les zones `belgique_area` et `strasbourg_area` de `gregoire.yaml`
    (`loc.startswith(dept)` + `kw.upper() in loc`).
  Compare les deux ensembles dans les deux sens : "SQL oui / Python non" et "SQL non / Python oui".
  Attendu : 0 dans chaque sens.

  **Note non-ASCII obligatoire** : `sqlite3` UPPER() ne couvre pas les caractères hors ASCII —
  `UPPER('Liège') = 'LIèGE'`. Une location « Liège » ne contient donc pas « LIEGE » et le
  mot-clé `liège` de `belgique_area` ne matchera jamais côté SQL. Consigner séparément dans le
  rapport : nombre d'offres dont la location contient "liège" (insensible à la casse Python),
  non matchées par SQL mais matchées par Python. Compte à relevé du 2026-09-22 : 0. Ce cas doit
  apparaître dans le rapport pour décision explicite.

  Affiche : nb offres `filtered_out=0` testées, écarts "SQL oui/Python non", écarts "SQL
  non/Python oui", nb cas liège non-ASCII. Done = script s'exécute sans exception, rapport
  affiché. **S**

✋ Verify before continuing:
- [x] `git diff orchestrator/job_search/scoring/filters.py` → vide
- [x] `python scripts/check_zone_invariant.py` → 0 écart, 0 cas liège (2026-09-22)
- [x] Profil de vue actif — 0 offre hors-zone sur les 4 presets
- [x] Profil de vue inactif — delta=0 sur les 4 presets vs snapshot
- [x] `wc -l data/traces/extract_facts.jsonl` = 2985 avant Phase 1 = 2985 après Phase 1

---

### Phase 2 — Front : commandes candidat + fermeture fuite

**Objectif** : toggle et case dans `index.vue` ; `/operateur` émet ses propres filtres propres
dès le montage ; aucun param du profil de vue ne fuite vers les vues opérateur.

- [x] **L6 — `web/app/stores/offers.ts`** : ajouter `const viewProfileActive = ref(true)` et
  `const includeRemote = ref(false)` après la ligne `const loading = ref(false)` (~l. 99). Dans
  `fetchOffers()`, après la construction de `params` (sort/order), ajouter : si
  `['cibles', 'gaps', 'filet', 'retenues'].includes(activeView.value)` → ajouter
  `params.view_profile = viewProfileActive.value` ; si `includeRemote.value` → ajouter
  `params.include_remote = true`. Exposer `viewProfileActive` et `includeRemote` dans le `return`.
  Done = `viewProfileActive` et `includeRemote` accessibles depuis les composants ; le premier
  `GET /offers` émis par un onglet candidat porte `view_profile=true`. **S**

- [x] **L7 — `web/app/pages/index.vue`** : dans `onMounted` (l. 65-68), ajouter avant
  `store.setView('cibles')` : `store.viewProfileActive = true; store.includeRemote = false` (reset
  à chaque montage = "sans persistance"). Dans le header, à droite du compteur d'offres et avant
  le lien "Traces LLM", ajouter :
  - Toggle "Profil de vue" : `<button>` ou `<label><input type="checkbox">` lié à
    `store.viewProfileActive`, `@change="store.fetchOffers()"` ;
  - Case "Inclure le remote" : `<label><input type="checkbox">` liée à `store.includeRemote`,
    `@change="store.fetchOffers()"`.
  Done = les deux commandes visibles dans le header, état initial correct, refetch déclenché sur
  changement. **S**

- [x] **L8 — `web/app/pages/operateur.vue:73`** : remplacer `store.fetchOffers()` par
  `store.setView('a_traiter')` dans le bloc `onMounted`. Done = `git diff
  web/app/pages/operateur.vue` montre exactement ce remplacement, une ligne changée. **XS**

✋ Verify before continuing:
- [x] État initial `/` : viewProfileActive=true, includeRemote=false, premier fetch porte view_profile=true (vérification statique code)
- [x] Navigation `/operateur` : setView('a_traiter') → pas de view_profile/include_remote/category/exclude_ad_language (vérification statique code)
- [x] `wc -l data/traces/extract_facts.jsonl` = 2985 (inchangé)

---

## Livrables détaillés

0. **L0 — `scripts/snapshot_presets.py`** (créer, exécuter avant L1) — ids de référence pour les
   4 presets candidat dans `data/snapshot_presets.json`. Done = fichier présent, 4 clés. **XS**
1. **L1 — `profiles/vue_candidat.yaml`** (créer) — zones : belgique_area, strasbourg_area. Done =
   fichier présent, YAML valide. **XS**
2. **L2 — `orchestrator/job_search/paths.py:14`** — ajout `VUE_CANDIDAT_PATH`. Done = import
   résout. **XS**
3. **L3 — `api/view_profile.py`** (créer) — loader zones + constructeur SQL avec cache
   module-level. Si config cassée : lève exception → 500 explicite. Done = ≥17 conditions ;
   config cassée → exception nommée. **S**
4. **L4 — `api/offers.py:list_offers`** — 2 params + bloc SQL conditionnel. Done = comportement
   filtré / non filtré correct ; `view_profile=true` avec config cassée → 500. **S**
5. **L5 — `scripts/check_zone_invariant.py`** (créer) — compare verdict SQL vs Python sur
   `filtered_out=0`, deux sens, rapport cas liège non-ASCII. Done = 0 écart dans les deux sens,
   cas liège consigné. **S**
6. **L6 — `web/app/stores/offers.ts`** — `viewProfileActive`, `includeRemote`, params injectés
   pour vues candidat seulement. Done = état initial correct, aucun param de vue dans les fetches
   opérateur. **S**
7. **L7 — `web/app/pages/index.vue`** — reset dans `onMounted` + toggle + case dans le header.
   Done = état initial correct, commandes visibles. **S**
8. **L8 — `web/app/pages/operateur.vue:73`** — `setView('a_traiter')` au lieu de
   `fetchOffers()`. Done = diff d'une ligne. **XS**

## Dépendances critiques

- L0 ne bloque rien — exécuter en premier, avant toute modification.
- L2 bloque L3 (VUE_CANDIDAT_PATH requis dans `view_profile.py`).
- L3 bloque L4 et L5 (build_view_clauses requis dans offers.py et check_zone_invariant.py).
- L4 bloque L6 (les params API doivent exister avant que le store les envoie).
- L8 est indépendant de L6-L7.

## Garde-fous

- Si `vue_candidat.yaml` est illisible ou désigne une zone absente de `gregoire.yaml` :
  `build_view_clauses()` lève une exception Python nommant la cause (`FileNotFoundError`,
  `ValueError("zone inconnue : {name}")`, etc.). `GET /offers?view_profile=true` renvoie HTTP 500
  avec le message d'erreur — jamais une liste non filtrée silencieuse.
- Blocage ou imprévu à l'exécution : trancher, continuer, consigner l'écart au handoff.
  L'exécution ne s'arrête jamais.
