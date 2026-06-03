# IMPLEMENTATION — Refonte scoring double-axe

> Cycle de travail dédié. L'IMPLEMENTATION.md de la Zone A (sourcing → dédup → scoring → SQLite → digest, livrée) est archivé dans `.claude/state/_archive/`. Ce document ne couvre QUE la refonte de l'étage scoring.

## Vue d'ensemble

Remplacer le score unique de la Zone A par **deux scores orthogonaux** : désirabilité (l'offre m'intéresse-t-elle ?) et atteignabilité (puis-je la décrocher maintenant ?). Le LLM extrait une fois par offre des faits intrinsèques ; désirabilité et atteignabilité sont des calculs Python par-dessus ces faits, recalculables sans coût LLM (cf. `rules/architecture.md` §4). On attaque par la fondation data : figer ce que l'API expose nativement avant d'écrire le moindre prompt d'extraction.

## Schémas cibles

> À affiner au moment du livrable correspondant — base de travail, pas contrat figé.

### `JobOffer` étendu (faits intrinsèques)

```python
# schéma neutre — les faits enrichissent JobOffer, jamais de champ brut France Travail (architecture.md §1)
class SeniorityLevel(str, Enum):
    junior = "junior"
    intermediate = "intermediate"
    senior = "senior"
    lead = "lead"

class ExtractedFacts(BaseModel):
    seniority_required: SeniorityLevel
    techs_required: list[str]          # y compris implicites ("RAG en prod" -> "RAG")
    domain: str                         # domaine métier réel, désambiguïsé par LLM
    parse_failed: bool = False          # flag si extraction LLM dégradée (architecture.md §3)

# Champs potentiellement déjà natifs (à confirmer au Livrable 2) :
# location, contract_type, company_size -> mappés depuis le payload France Travail si présents,
# extraits par LLM en fallback seulement.
```

### `profile.yaml` (3 niveaux de maîtrise)

```yaml
# déclaratif — le loader (gregoire.py) le charge/valide/hash (architecture.md §2)
# V0 rempli à la main. 3 paliers de maîtrise par techno.
seniority: intermediate
techs:
  python: confirmed       # notions | working | confirmed
  fastapi: confirmed
  langgraph: working
  kubernetes: notions
search_criteria:
  domains: [ai_engineering, automation, backend]
  locations: [strasbourg_area, remote]
  contract_types: [cdi, freelance]
```

### Scores dérivés (calculés Python, persistés sur `offers`)

```python
class Desirability(BaseModel):
    score: float                        # agrégé côté code
    detail: dict                        # quel critère pèse — observable

class ReachLevel(str, Enum):
    at_level = "at_level"
    one_step_up = "one_step_up"
    out_of_reach = "out_of_reach"

class Attainability(BaseModel):
    level: ReachLevel
    techs_matched: list[str]
    techs_missing: list[str]            # observable par construction
    seniority_gap: int                  # écart de palier
```

## Phases

### Phase 1 — Fondations data (schémas)
Objectif : figer ce qu'on extrait vs ce qui est gratuit, avant tout prompt.
- [x] L2 — Vérification du payload natif France Travail (note écrite des champs structurés dispo)
- [x] L1 — Schéma `JobOffer` étendu (faits intrinsèques) en Pydantic
- [x] L4 — Schéma `profile.yaml` à 3 niveaux + `gregoire.yaml` rempli à la main

✋ Verify before continuing:
- [ ] La liste des faits à extraire est figée (séniorité / technos / domaine + ce qui vient du natif)
- [ ] `JobOffer` étendu ne contient aucun champ brut spécifique France Travail
- [ ] `gregoire.yaml` valide et chargeable

Si tout est OK : "go". Sinon dis ce qui cloche.

### Phase 2 — Extraction LLM (le pari central)
Objectif : produire les faits intrinsèques de façon fiable, en un appel par offre.
- [x] L3 — Prompt + étage d'extraction LLM (séniorité, technos implicites, domaine), structured output, température basse, parsing défensif

✋ Verify before continuing:
- [ ] Extraction lancée sur 5-10 offres réelles
- [ ] Séniorité exigée correcte sur l'échantillon
- [ ] Technos implicites captées (ex : "architectures RAG en prod" → RAG)

Si l'extraction techno est pauvre : STOP, retravailler le prompt avant la Phase 3. Tout l'aval en dépend.

### Phase 3 — Matching Python (cœur observable)
Objectif : les deux scores, calculés en Python, inspectables.
- [x] L5 — Loader/validateur profil à interface stable (`gregoire.py`, hash, requête niveau par techno)
- [x] L6 — Calcul désirabilité (fonction pure `(faits, critères) -> Desirability`)
- [x] L7 — Calcul atteignabilité (fonction pure `(faits, profil) -> Attainability`)

✋ Verify before continuing:
- [ ] Sur les 5-10 offres, le palier `one_step_up` se distingue nettement de `out_of_reach`
- [ ] Le détail technos matchées/manquantes est lisible
- [ ] Règle de gradation calibrée sur données réelles (pas dans l'abstrait)

Si tout est OK : "go". Sinon dis ce qui cloche.

### Phase 4 — Persistance & cycle de vie
Objectif : brancher les nouveaux scores dans la donnée et le pipeline, `verdicts` intact.
- [x] L8 — Extension `offers` (faits + 2 scores + détails), suppression de l'ancien `score`/`criteria_json`, migration de schéma
- [x] L9 — Politique de purge à deux conditions (purge ssi `out_of_reach` ET peu désirable ; conservation hors-digest pour désirable-mais-au-dessus)
- [x] L10 — Intégration dans `run.py` (extraction → calculs → persistance → purge), sourcing/dédup/digest amont-aval inchangés

✋ Verify before continuing:
- [ ] Un run end-to-end écrit correctement les nouveaux champs sur `offers`
- [ ] `verdicts` strictement intact
- [ ] Aucune offre désirable purgée à tort

Si tout est OK : "go". Sinon dis ce qui cloche.

### Phase 5 — Migration & restitution
Objectif : rejouer les 63, pouvoir vivre les deux axes dans le cockpit.
- [x] L11 — Relance complète des 63 offres sur le pipeline refondu (base propre côté scoring)
- [x] L12 — Raccord cockpit minimal (API read-only + tableau affichent les 2 scores bruts)
- [x] L13 — Adaptation du digest matinal (tri sur cadran principal atteignable+désirable)

✋ Verify before continuing:
- [ ] Les 63 offres ré-scorées sont consultables dans le cockpit avec les 2 axes
- [ ] Le cockpit ne plante pas (frontière offers/verdicts respectée)
- [ ] Point de sortie = entrée de l'observation pour le futur PROSIT UI complet

Si tout est OK : "go". Sinon dis ce qui cloche.

## Livrables détaillés

1. **L1 — `JobOffer` étendu** — faits intrinsèques en Pydantic dans le schéma neutre. `S`
2. **L2 — Vérif payload France Travail** — note des champs natifs structurés dispo. `S`
3. **L3 — Étage extraction LLM** — un appel/offre produit séniorité + technos (implicites incluses) + domaine, parsing défensif. `M`
4. **L4 — `profile.yaml` 3 niveaux** — format déclaratif, `gregoire.yaml` V0 à la main. `S`
5. **L5 — Loader profil à interface stable** — `gregoire.py` charge/valide/hash + requête niveau par techno, découplé du format de stockage. `M`
6. **L6 — Calcul désirabilité** — fonction pure observable, croisement domaine/lieu/contrat/taille. `M`
7. **L7 — Calcul atteignabilité** — fonction pure, palier + technos matchées/manquantes, règle calibrable. `M`
8. **L8 — Extension `offers`** — faits + 2 scores + détails, suppression ancien score unique, `verdicts` intouché. `M`
9. **L9 — Purge à deux conditions** — purgeable ssi out_of_reach ET peu désirable, seuils paramétrés. `S`
10. **L10 — Intégration `run.py`** — nouvel étage scoring à la place de l'ancien, amont/aval inchangés. `M`
11. **L11 — Relance des 63** — pipeline refondu, base propre. `S`
12. **L12 — Raccord cockpit minimal** — 2 scores bruts affichés, pas de cadrans/vues. `M`
13. **L13 — Digest sur cadran principal** — tri atteignable+désirable. `S`

## Dépendances critiques

- L2 bloque L1 et L3 (on n'extrait que ce qui n'est pas natif).
- L3 (extraction) bloque L6 et L7 (le matching consomme les faits).
- L5 (loader) bloque L7 (atteignabilité interroge le profil).
- L8 (schéma) bloque L9, L10, L11.
- L11 (relance) bloque la validation finale L12/L13.

## Garde-fous

- Phase 2 (extraction) est la vraie porte : si les technos implicites ne sortent pas fiables, NE PAS enchaîner sur le matching. Retravailler le prompt, baisser température, renforcer few-shot, réduire le nombre de critères (cf. `rules/stack.md`).
- Toute évolution d'un schéma `shared`/cible ou de `rules/architecture.md` = validation humaine explicite avant d'écrire le code (cf. `rules/workflow.md`).
