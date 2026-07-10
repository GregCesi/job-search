# IMPLEMENTATION — Lot G : Gates éliminatoires hors_perimetre (langue + contrat)

## Vue d'ensemble

Ajouter deux gates déterministes (langue tierce, contrat stage/alternance) au module `hors_perimetre`, rendre les causes existantes (no_tech, mgmt_role) traçables dans un champ multi-causes, et déplacer le gate APRÈS le calcul d/a pour conserver les scores en base. Première chose à attaquer : migration du modèle de données (scalaire → liste de causes).

Invariants : cf. `rules/architecture.md` §4 (0 LLM au rescore), §5 (verdicts non-intrants). Le gate ne modifie jamais les scores, ne touche jamais `hors` (verdict marché). `hors_perimetre` = gate qualité/éligibilité, orthogonal aux verdicts.

## Schémas cibles

_Base de travail, pas contrat figé — à affiner au livrable correspondant._

### `hors_perimetre.py` — retour multi-causes

```python
class HorsPerimetreCause(str, Enum):
    no_tech   = "no_tech"       # techs_required == []
    mgmt_role = "mgmt_role"     # role_level == manager
    langue    = "langue"        # langue tierce détectée (keyword scan)
    contrat   = "contrat"       # stage/alternance/MIS

def derive_hors_perimetre(
    facts: ExtractedFacts,
    title: str,
    description: str,
    contract_type: str | None,
    nature_contract: str | None,
    alternance: bool,
) -> list[HorsPerimetreCause]:
    """Retourne liste vide si l'offre est dans le périmètre."""
```

### SQLite — nouvelle colonne

```sql
ALTER TABLE offers ADD COLUMN perimetre_causes TEXT;
-- JSON list : '["no_tech","langue"]' ou NULL (aucune cause)
```

`hors_perimetre_reason` reste en place pour compat lecture (API/front). Valeur = `causes[0]` si causes non vides, sinon `NULL`. Migration rétro : les 44 offres existantes reçoivent `perimetre_causes` calculé depuis les règles réappliquées.

### `ExtractedFacts` — champ flux futur

```python
class ExtractedFacts(BaseModel):
    ...
    langues_requises: list[str] = []  # NOUVEAU — stocké, non branché sur le gate
```

## Phases

### Phase 1 — Modèle de données + migration (L1–L3)

- [x] **L1** — `hors_perimetre.py` : refactorer `HorsPerimetreReason` → `HorsPerimetreCause` (enum étendu à 4 valeurs). `derive_hors_perimetre()` retourne `list[HorsPerimetreCause]` (pas un scalaire). Ajouter les deux nouvelles règles :
  - `langue` : scan keyword insensible à la casse sur `title + description`, liste fermée constante `LANGUES_TIERCES`
  - `contrat` : `contract_type ∈ {Internship, MIS}` OU `nature_contract ∈ {Cont. professionnalisation, Contrat apprentissage}` OU `alternance=True` OU `title =~ /alternance|stage|apprentissage|intern/i`
- [x] **L2** — `db.py` : migration colonne `perimetre_causes TEXT` (JSON list). Ajout dans `migrate_offers_schema()`.
- [x] **L3** — `storage/offers.py` : `save_offer()` accepte `perimetre_causes: list[str] | None`, persiste en JSON. `hors_perimetre_reason` reste synchronisé (`causes[0]` ou `NULL`).

✋ Verify before continuing:
- [ ] `derive_hors_perimetre()` retourne une liste (test unitaire : cumul langue+contrat sur une offre fictive)
- [ ] `perimetre_causes` colonne existe après `init_db()`
- [ ] `save_offer()` écrit `perimetre_causes` en JSON et `hors_perimetre_reason` reste cohérent
- [ ] 0 LLM dans tout le chemin (grep `ollama` dans `scoring/`)

Si tout est OK : "go". Sinon dis ce qui cloche.

### Phase 2 — Intégration pipeline + repositionnement gate (L4–L5)

- [x] **L4** — `run.py` : déplacer l'appel `derive_hors_perimetre()` APRÈS `compute_desirability()`/`compute_attainability()`. Si causes non vides → `save_offer()` avec `category=None`, `perimetre_causes=causes`, scores d/a calculés mais non stockés en catégorie. Passer `title`, `description`, `contract_type`, `nature_contract`, `alternance` au gate.
- [x] **L5** — `rescore.py` : même repositionnement. Le rescore exclut déjà les offres `hors_perimetre_reason IS NOT NULL` — adapter le filtre pour ré-évaluer les offres existantes (flag `--force` existant suffit, vérifier).

✋ Verify before continuing:
- [ ] Un rescore `--force --dry-run` termine sans erreur
- [ ] Les offres gatées conservent leurs scores d/a en base (ou au minimum leurs `extracted_facts_json` intacts)
- [ ] Le gate ne modifie aucune valeur dans `category` pour les offres non gatées (assertion avant/après)

Si tout est OK : "go". Sinon dis ce qui cloche.

### Phase 3 — Rétro-attribution + script de mesure + rapport (L6–L8)

- [x] **L6** — Script de rétro-attribution : réappliquer `derive_hors_perimetre()` sur TOUTES les offres (y compris déjà gatées). Écrire `perimetre_causes` pour chacune. Les 44 offres existantes doivent recevoir leur(s) cause(s) réelles. Log si une offre anciennement `hors_perimetre` ne matche plus aucune règle → `inconnu` + warning.
- [x] **L7** — Snapshot + diff : avant/après distribution des catégories. Liste nominative des offres ayant changé de catégorie, avec cause(s). Les 10 cas corpus du brief doivent y figurer.
- [x] **L8** — `gate-report.md` : livrer le rapport dans `.claude/state/`. Format : tableau nominatif (titre, entreprise, ancienne catégorie, nouvelle catégorie, causes).

✋ Verify before continuing:
- [ ] Les 4 cas corpus langue (QuadCode AI Skills, QuadCode Python, Lightcast, TELUS) sont gatés avec cause `langue`
- [ ] Les 6 cas corpus contrat (Alternance Achenheim, Alternance Nexa ×2, Socomec, Helci, Sightengine) sont gatés avec cause `contrat`
- [ ] Aucune offre CDI/Freelance/Full-time fr/en n'est gatée par erreur (spot check top 10 parfait/rêve)
- [ ] Le gate n'a modifié aucun score (diff `extracted_facts_json` = vide)

Si tout est OK : "go". Sinon dis ce qui cloche.

### Phase 4 — Flux futur extraction + tests (L9–L10)

- [x] **L9** — `extractor.py` : ajouter `langues_requises` (liste de strings) au prompt système + au parsing + à `ExtractedFacts`. Stocké, NON branché sur le gate. Pas de backfill.
- [x] **L10** — Tests unitaires du module gate : chaque règle isolée, cumul de causes, non-régression (offre CDI fr sans langue tierce → `[]`), assertion que les scores ne changent pas.

✋ Verify before continuing:
- [ ] `ExtractedFacts` a le champ `langues_requises: list[str]`
- [ ] Le prompt LLM mentionne `langues_requises` dans le JSON schema attendu
- [ ] Tests passent (`pytest tests/ -k hors_perimetre`)
- [ ] `hors_perimetre_reason` reste non-null pour les 44 offres historiques (pas de régression)

Si tout est OK : "go". Sinon dis ce qui cloche.

## Livrables détaillés

1. **L1** — Module gate 4 règles — done : `derive_hors_perimetre()` retourne `list[HorsPerimetreCause]` avec les 4 règles — **S**
2. **L2** — Migration `perimetre_causes` — done : colonne ajoutée, `init_db()` la crée — **XS**
3. **L3** — `save_offer()` multi-causes — done : persiste JSON list + compat `hors_perimetre_reason` — **XS**
4. **L4** — `run.py` repositionnement gate — done : gate après d/a, scores conservés — **S**
5. **L5** — `rescore.py` repositionnement gate — done : même logique, `--force` couvre le re-gate — **S**
6. **L6** — Script rétro-attribution — **done** : 215 offres traitées, `perimetre_causes` rempli pour toutes — **S**
7. **L7** — Snapshot + diff nominatif — **done** : 25 offres changent de bucket (+25 hors_perimetre) — **S**
8. **L8** — `gate-report.md` — **done** : `.claude/state/gate-report.md` livré — **XS**
9. **L9** — Champ `langues_requises` extraction — **done** : champ ajouté à ExtractedFacts + prompt + parsing + few-shot — **S**
10. **L10** — Tests unitaires gate — **done** : 47 tests (4 règles isolées + cumul + non-régression + facts intacts) — **M**

## Dépendances critiques

- L1 (module gate) bloque L4/L5 (intégration pipeline) et L6 (rétro-attribution)
- L2 (migration colonne) bloque L3 (save_offer)
- L3 (save_offer) bloque L4/L5/L6
- L6 (rétro-attribution) bloque L7/L8 (mesure + rapport)

## Garde-fous

- Si une offre historiquement `hors_perimetre` ne matche plus aucune règle lors de la rétro-attribution → cause `inconnu` + log warning (ne pas silencieusement perdre le statut)
- Le script de re-score NE passe PAS par l'API (bug connu `seen_candidat=1` sur GET /offers) → accès direct SQLite
- Si le scan keyword langue produit des faux positifs manifestes sur les top offres → acceptable, repêchage opérateur avec cause visible
