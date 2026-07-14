# IMPLEMENTATION — Unification zones (source unique profil YAML)

## Vue d'ensemble

Deux référentiels de zones divergents — `AREA_COMMUNES` (france_travail.py, 6 zones, codes INSEE) et `AREA_RULES` (filters.py, 5 zones, dept + keywords) — causent une déperdition active : nancy fetchée puis rejetée au gate. Unification en une source unique dans le profil YAML, consommée par le fetch ET le hard filter. Gate contrat basculé sur `search_criteria.contract_types` (déjà déclaré, actuellement ignoré). Première chose à attaquer : le schéma zones dans le profil + modèle Pydantic.

Invariants : cf. `rules/architecture.md` §1 (sources pluggables), §4 (0 LLM au rescore). Ce chantier ne touche ni l'extraction ni le scoring — uniquement fetch, hard filter localisation, gate contrat.

## Schémas cibles

Base de travail, à affiner au livrable correspondant.

```python
# matching/profile.py
class Zone(BaseModel):
    insee: list[str]     # min 1 — codes commune pour l'API France Travail
    dept: list[str]      # min 1 — préfixes dept pour le hard filter location
    keywords: list[str]  # mots-clés matchés dans le champ location (uppercase)

class Profile(BaseModel):
    # ... existant ...
    zones: dict[str, Zone]           # référentiel complet
    search_criteria: SearchCriteria  # .locations sélectionne les zones actives
```

```yaml
# profiles/gregoire.yaml
zones:
  strasbourg_area:
    insee: ["67482"]
    dept: ["67"]
    keywords: ["strasbourg", "bas-rhin"]
  reims_area:
    insee: ["51454"]
    dept: ["51"]
    keywords: ["reims", "marne"]
  nancy_area:
    insee: ["54395"]
    dept: ["54"]
    keywords: ["nancy"]
  paris_area:
    insee: ["75101"]
    dept: ["75", "92", "93", "94"]
    keywords: ["paris", "ile-de-france"]
  lyon_area:
    insee: ["69123"]
    dept: ["69"]
    keywords: ["lyon", "rhone", "rhône"]
  toulouse_area:
    insee: ["31555"]
    dept: ["31"]
    keywords: ["toulouse", "haute-garonne"]

search_criteria:
  locations:
    - strasbourg_area
    - reims_area
    - nancy_area
    - paris_area
    - remote
  contract_types:
    - cdi
    - freelance
```

## Phase 1 — Schéma zones + gate contrat (profil + Pydantic + YAML)

- [x] **L1** — Modèle `Zone` dans `matching/profile.py` (`insee: list[str]` min 1, `dept: list[str]` min 1, `keywords: list[str]`). Champ `zones: dict[str, Zone]` sur `Profile`. ValidationError si `insee` ou `dept` vide. — *done* : `Zone` importable, profil charge sans erreur. XS.
- [x] **L2** — Section `zones:` dans `profiles/gregoire.yaml` : reporter fidèlement les 6 zones de `AREA_COMMUNES` + les 5 règles de `AREA_RULES`, compléter nancy (dept `["54"]`, keywords `["nancy"]`). — *done* : `load_profile("profiles/gregoire.yaml")` valide, 6 zones, nancy a ses 3 faces. XS.
- [x] **L3** — Gate contrat dans `filters.py` : lire `criteria.contract_types` au lieu des patterns hardcodés. Reporter les exclusions actuelles (alternance/stage/apprentissage/MIS) dans la logique : si `contract_types` est renseigné, n'accepter que les types listés (CDI/freelance=LIB) + rejeter les stages/alternances systématiquement. Comportement identique à config identique. — *done* : offre alternance toujours rejetée, offre CDI passe, offre MIS rejetée si MIS absent de contract_types. S.

✋ Verify before continuing:
- [x] `python -c "from orchestrator.job_search.matching.profile import load_profile; p,_=load_profile('profiles/gregoire.yaml'); print(len(p.zones), list(p.zones))"` → 6 zones, nancy présente
- [x] zone sans `dept` dans un YAML test → ValidationError
- [x] grep `AREA_COMMUNES\|AREA_RULES` hors `_archive/` : occurrences encore présentes (attendu — suppression Phase 2)

## Phase 2 — Câblage fetch + hard filter sur le profil

- [x] **L4** — `france_travail.py` : `FranceTravailSource` prend le profil (ou les zones résolues) au lieu de `commune: str`. `run.py` construit les sources depuis `profile.zones` filtré par `profile.search_criteria.locations`. `AREA_COMMUNES` supprimé. — *done* : `run.py` ne référence plus `AREA_COMMUNES`, fetch piloté par le profil. S.
- [x] **L5** — `filters.py` : `apply_hard_filters` consomme `profile.zones` (passé via `criteria` ou en paramètre direct) pour la localisation, au lieu de `AREA_RULES`. `AREA_RULES` supprimé. Comportement remote inchangé (`offer.remote AND "remote" in locations`). — *done* : `grep -rn AREA_RULES` (hors archive) = 0. S.
- [x] **L6** — `rescore.py` : vérifier que le rescore passe les zones au hard filter (même chemin que `run.py`). — *done* : `python -m orchestrator.job_search.rescore --dry-run --force` sans erreur. XS.

✋ Verify before continuing:
- [x] `grep -rn "AREA_COMMUNES\|AREA_RULES" orchestrator/ api/ tests/` : 0 occurrence
- [x] `python -m orchestrator.job_search.run --max 5` : run réel sans erreur (4 zones FT, gate contract:mis OK)
- [x] `python -m orchestrator.job_search.rescore --dry-run --force` : 301 offres, 0 crash, gate contract:cdd OK
- [x] 0 LLM appelé par ce chantier (invariant §4)

## Phase 3 — Tests unitaires + démo zone pluggable

- [x] **L7** — Test : zone sans `dept` → ValidationError Pydantic. XS.
- [x] **L8** — Test : offre location "54 - Nancy" avec nancy active → PASSE le hard filter. XS.
- [x] **L9** — Test : offre alternance avec `contract_types=["cdi", "freelance"]` → `filtered_out=True`. XS.
- [x] **L10** — Démo zone pluggable : ajouter une zone test (ex. `lyon_area` dans locations si absent des actives), relancer, constater fetch + filtre cohérents SANS modification de code. — *done* : démontré dans le terminal. XS.

✋ Verify before continuing:
- [x] `pytest` complet vert (anciens + nouveaux tests) — 146/147 passent, 1 échec pré-existant (test_aliases copilot)
- [x] Démo zone pluggable documentée (output terminal)

## Livrables détaillés

| # | Livrable | Done | Taille |
|---|----------|------|--------|
| L1 | Modèle `Zone` Pydantic + champ `zones` sur `Profile` | zone importable, profil valide | XS |
| L2 | Section `zones:` dans `gregoire.yaml` (6 zones, nancy complète) | load_profile valide, 6 zones | XS |
| L3 | Gate contrat depuis `contract_types` profil | comportement identique, configurable | S |
| L4 | Fetch depuis `profile.zones` + suppression `AREA_COMMUNES` | run.py piloté par profil | S |
| L5 | Hard filter depuis `profile.zones` + suppression `AREA_RULES` | 0 occurrence grep | S |
| L6 | Vérification rescore compatible | dry-run sans erreur | XS |
| L7 | Test zone sans dept → ValidationError | pytest vert | XS |
| L8 | Test nancy passe le hard filter | pytest vert | XS |
| L9 | Test alternance rejetée par contract_types | pytest vert | XS |
| L10 | Démo zone pluggable (lyon ajouté sans code) | output terminal | XS |

## Dépendances critiques

- L1+L2 bloquent L4 et L5 (le schéma doit exister avant d'être consommé)
- L4+L5 bloquent L6 (rescore dépend du même chemin)
- L4+L5 bloquent L8 (test nancy a besoin du nouveau hard filter)

## Garde-fous

- Si `rescore --dry-run --force` montre des catégories qui changent → investiguer AVANT de conclure (ce chantier ne touche pas le scoring, toute dérive est un bug)
- Si le run réel échoue sur l'API France Travail → vérifier que les codes INSEE reportés sont corrects (source : `AREA_COMMUNES` actuel, valeurs vérifiées en Phase 0)
