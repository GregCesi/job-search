# IMPLEMENTATION — Chantier 2 : refonte du profil + catégorisation

> Mode **augment**. Remplace l'IMPLEMENTATION du rituel de calibration comme document de travail courant.
> L'ancien (`IMPLEMENTATION-calibration.md`) est archivé dans `.claude/state/_archive/`, NON écrasé en place.
> Le `.claude/` structurel (rules, commands, settings) n'est PAS régénéré.
> Invariants `architecture.md` à respecter : §2 frontière `profile.yaml`, §3 scoring explicable, §4 0 LLM au recalcul, §Persistance (offers/verdicts/human_reviews jamais fusionnées).

## Vue d'ensemble

Le scoring double-axe (2 juin) et le refacto chantier 1 (filtres durs + désirabilité graduée) tournent, mais sur un **profil grossier** : 3 paliers `notions/working/confirmed` auto-déclarés, et une atteignabilité (`ReachLevel`) pilotée par la **séniorité seule** (`at_level` = `seniority_gap == 0`, défaut 6 gravé hors-scope au chantier 1). Ce chantier refait le profil par le bas et change la **sortie** du scoring de scalaire vers catégorielle.

Trois mutations, toutes derrière la frontière `profile.yaml` (le loader `gregoire.py` reste l'interface stable, son contenu et le schéma data changent) :

1. **Profil** : chaque techno porte `level: 1-10` (compréhension / capacité à en parler — PAS autonomie de code) + `desire: 0-10` (envie de bosser dessus). Techno absente = inconnue = neutre. Plafond de rôle déclaré (IC).
2. **Atteignabilité** : `attain_tech` = moyenne des niveaux pondérée par l'`importance` de chaque techno dans l'offre (core > required > nice_to_have) ; `attain_role` = portail gradué (IC/lead/manager vs plafond profil) ; **`attainability = min(tech, rôle)`** (non-compensation). Remplace le `ReachLevel` séniorité-seule.
3. **Sortie** : croisement désirabilité × atteignabilité → **catégorie** (4 cases : parfait / rêvé / atteignable / hors) + **score intra-case** qui trie DANS une case, jamais entre cases. Tue le classement scalaire global.

Côté offre : l'extraction LLM existante (`extractor.py`, faits intrinsèques) est **enrichie** d'un champ `importance` par techno + un `role_level`. Une **ré-extraction LLM unique** des 68 offres peuple les nouveaux champs — c'est de l'ingestion, pas un recalcul profil (§4 respecté).

La désirabilité gagne une modulation par l'envie-techno (gradient domaine du chantier 1 × envie sur les technos connues de l'offre, inconnu neutre).

**Première phase à attaquer : Phase 1 (schéma profil v2 + barème).** Tout l'aval lit le profil — rien ne se calcule avant qu'il soit figé et chargé sans casse.

---

## Calage sur l'existant (lu dans le repo — NON négociable)

Trois faits du repo modifient le plan brut du PROSIT. À respecter :

- **L'atteignabilité existe déjà** (`attainability.py`, `ReachLevel`, `techs_matched/missing`, `seniority_gap`, `_TECH_ALIASES`). Ce chantier la **réécrit**, ne la crée pas. Le `seniority_gap` reste utile comme intrant du `attain_role`, pas comme sortie.
- **Le défaut 6 est explicitement à résoudre ici** (`_archive/IMPLEMENTATION-chantier-1.md` §HORS-SCOPE) : `at_level` ne doit plus être gobé par la séniorité affichée — c'est le passage à `min(tech, rôle)`.
- **Contrat `criteria_json` ↔ calibration** : le normaliseur API `_build_criteria` (DECISIONS 2026-06-03) expose 3 critères `domain / seniority / tech_coverage`, forme `[{nom, note, justif, axe}]`, consommée par le cockpit, le snapshot `ai_snapshot_json` et la distance par axe. **Si ce chantier change la _structure_ des critères (pas juste les valeurs), le garde-fou C-2 de la calibration saute.** → voir Phase 5 + garde-fou dédié.

---

## Schémas cibles

> À affiner au moment du livrable correspondant — base de travail, pas contrat figé.
> Toute évolution d'un schéma cible ou de `architecture.md` = validation humaine explicite avant code (`rules/workflow.md`).

### `profile.yaml` v2 (remplace les 3 paliers)

```yaml
# déclaratif — gregoire.py (loader stable) charge / valide / hash (architecture.md §2)
# V1 rempli à la main (notes provisoires en attendant le chantier Rodin frère).
profile_id: gregoire
role_ceiling: ic              # ic | lead | manager — plafond de rôle assumé (never fabricate)
skills:
  # level 1-10 = compréhension / capacité à en parler (barème : doc paliers)
  # desire 0-10 = envie de bosser dessus. Absence d'une techno = inconnue = neutre.
  python:    { level: 8, desire: 8 }
  fastapi:   { level: 8, desire: 7 }
  langgraph: { level: 5, desire: 9 }
  rag:       { level: 6, desire: 9 }
  llm:       { level: 6, desire: 9 }
  vue:       { level: 9, desire: 8 }
  java:      { level: 8, desire: 4 }
  docker:    { level: 7, desire: 5 }
  # cobol absent  -> inconnu, neutre (ni pénalité de niveau, ni envie comptée)
search_criteria:
  domains: [ai_engineering, automation, backend]   # inchangé (chantier 1)
  locations: [strasbourg_area, remote]
  contract_types: [cdi, freelance]
```

### Faits extraits — enrichis (`ExtractedFacts`)

```python
class TechRequirement(BaseModel):
    name: str
    importance: Literal["core", "required", "nice_to_have"]

class RoleLevel(str, Enum):
    ic = "ic"
    lead = "lead"
    manager = "manager"

class ExtractedFacts(BaseModel):
    seniority_required: SeniorityLevel          # inchangé
    techs_required: list[TechRequirement]        # CHANGÉ : list[str] -> list[TechRequirement]
    domain: str                                  # inchangé
    role_level: RoleLevel = RoleLevel.ic         # NOUVEAU — rôle non-technique extrait
    parse_failed: bool = False
```

> Migration de données : les anciens `techs_required: list[str]` se relisent en `importance="required"` par défaut au moment de la ré-extraction (Phase 2), ou via un fallback de lecture. À trancher au L3.

### Atteignabilité — refondue

```python
class Attainability(BaseModel):
    score: float                  # NOUVEAU — atteignabilité continue 0-100 = min(tech, role)
    attain_tech: float            # moyenne pondérée par importance
    attain_role: float            # portail gradué IC/lead/manager
    techs_matched: list[str]      # observable (conservé)
    techs_missing: list[str]      # observable (conservé)
    blocked_by: Literal["tech", "role", None]  # quel axe gouverne le min — lisibilité
```

Poids importance (constante, calibrable) : `core=3, required=2, nice_to_have=0.5`.
`attain_tech = Σ(level_i × poids_i) / Σ(poids_i)` × 10  (level 0 pour techno absente du profil).
`attain_role` : `role_level <= role_ceiling` → 100 ; un cran au-dessus → ~40 ; deux crans → 0 (gradient, pas binaire).

### Catégorie + score intra-case

```python
class Category(str, Enum):
    parfait = "parfait"        # désirable ET atteignable
    reve = "reve"              # désirable, PAS atteignable (cible de progression)
    atteignable = "atteignable" # atteignable, PEU désirable (filet de sécurité)
    hors = "hors"              # ni l'un ni l'autre

class ScoredOffer(BaseModel):
    category: Category
    score_in_category: float   # tri DANS la case — jamais comparé entre cases
    desirability: float        # axe brut conservé (observabilité)
    attainability: float       # axe brut conservé
```

Catégorie = croisement de 2 seuils (un par axe), valeurs à calibrer sur les 68.
`score_in_category` : logique de tri propre à chaque case (ex. `parfait`/`atteignable` triés par désirabilité ; `reve` trié par désirabilité aussi mais c'est une pile distincte). **Le score ne fuit jamais hors de sa case.**

---

## Phases

### Phase 1 — Schéma profil v2 + barème (fondation, 0 calcul aval)
Objectif : le nouveau `profile.yaml` se charge par le loader stable sans rien casser de l'aval existant.

- [x] L1 — Schéma profil v2 Pydantic (`skills: {techno: {level, desire}}` + `role_ceiling`) dans le loader `gregoire.py`. Validation : `level` ∈ 1-10, `desire` ∈ 0-10, `role_ceiling` ∈ enum.
- [x] L2 — `gregoire.yaml` rempli à la main (technos réelles + niveaux provisoires + envies + role_ceiling=ic).
- [x] L3 — Doc barème des 10 paliers (`docs/bareme-niveau.md`) : grille théorique/local/prod × discours, aide à la saisie + futur brief Rodin. Hors donnée.

```
✋ Verify before continuing:
- [ ] gregoire.yaml v2 charge et valide via gregoire.py (hash recalculé)
- [ ] L'interface stable du loader (requête niveau par techno) répond au nouveau format
- [ ] L'aval existant (desirability/attainability) ne plante pas encore — il lit l'ancien format OU on accepte qu'il soit cassé jusqu'à Phase 3 (à acter ici)
- [ ] Aucune écriture hors profiles/ et docs/

Si tout OK : "go". Sinon dis ce qui cloche.
```

### Phase 2 — Extraction enrichie (l'UNIQUE passage LLM du chantier)
Objectif : produire `importance` par techno + `role_level`, en un appel par offre. Observer la stabilité 7B/8B AVANT le batch.

- [x] L4 — Migration `ExtractedFacts` : `techs_required: list[TechRequirement]` + `role_level`. Schéma Pydantic + colonnes/format SQLite (`extracted_facts_json`).
- [x] L5 — Prompt d'extraction enrichi (`extractor.py`) : sort l'importance (core/required/nice_to_have) par techno + le role_level. Structured output, température basse, parsing défensif (§3).

```
✋ Verify before continuing — GO/NO-GO d'hypothèse risquée :
- [ ] Extraction lancée sur 5-10 offres réelles
- [ ] L'importance discrimine vraiment (un core sort différent d'un nice_to_have sur des offres où c'est lisible)
- [ ] role_level correct sur une offre IC, une offre lead, une offre manager du dataset
- [ ] Si l'importance est instable (recopie, hallucine) : STOP — baisser température / renforcer few-shot / réduire avant de lancer le batch (rules/stack.md)

Si tout OK : "go". Sinon dis ce qui cloche.
```

- [x] L6 — Ré-extraction LLM one-shot des 68 offres → peuple `importance` + `role_level`. **Point de bascule : après L6, plus aucun LLM jusqu'à la fin du chantier.**

```
✋ Verify before continuing:
- [ ] Les 68 offres ont leurs faits enrichis persistés
- [ ] Aucune offre perdue / corrompue pendant le batch
- [ ] verdicts / human_reviews / criteria_json strictement intacts

Si tout OK : "go". Sinon dis ce qui cloche.
```

### Phase 3 — Atteignabilité refondue (Python pur, 0 LLM)
Objectif : remplacer le `ReachLevel` séniorité-seule par `min(attain_tech, attain_role)`. Résout le défaut 6.

- [x] L7 — `attain_tech` : moyenne des niveaux pondérée par importance (`_IMPORTANCE_WEIGHTS`), level 0 pour techno absente, `_TECH_ALIASES` réutilisés. Fonction pure.
- [x] L8 — `attain_role` : portail gradué role_level vs role_ceiling. Fonction pure.
- [x] L9 — `attainability = min(tech, role)` + `blocked_by`. Remplace le calcul `ReachLevel` dans `attainability.py`.

```
✋ Verify before continuing:
- [ ] Contre-exemple C# : une offre {RAG:9, LLM:9, LangGraph:9, Docker:7, git:10, C#(nice):0} N'est PAS plombée par le 0 sur C#
- [ ] Une offre lead/manager techniquement dans les cordes ressort bloquée par le rôle (blocked_by="role"), pas rachetée par la technique
- [ ] Le défaut 6 est mort : offre 3109248 n'est plus "un cran au-dessus" pour une mauvaise raison de séniorité
- [ ] 0 appel LLM (Python pur — §4)

Si tout OK : "go". Sinon dis ce qui cloche.
```

### Phase 4 — Désirabilité modulée + catégorisation (Python pur)
Objectif : nuancer la désirabilité par l'envie-techno, puis produire catégorie + score intra-case.

- [x] L10 — Désirabilité : gradient domaine (chantier 1, `_DOMAIN_GRADIENT` conservé) modulé par l'envie moyenne sur les technos connues de l'offre. Inconnu neutre (n'abaisse pas). Composition à calibrer.
- [x] L11 — Catégorisation : 2 seuils (un par axe) → `Category`. Fonction pure `(desirability, attainability) -> Category`.
- [x] L12 — `score_in_category` : logique de tri par case. Le score ne sort jamais de sa case.

```
✋ Verify before continuing:
- [ ] Hiérarchie d'envie reproduite : IA > Vue > Java > WordPress > inconnu sur des offres réelles
- [ ] Sur la distribution des 68 : les 4 cases sont peuplées et sensées (pas 67 dans une seule)
- [ ] Le job de rêve (3109248) tombe en "parfait" ou "reve" selon son atteignabilité réelle
- [ ] Le score ne compare jamais deux cases (vérifier : un "reve à 78" et un "parfait à 72" ne se classent pas l'un contre l'autre)

Si tout OK : "go". Sinon dis ce qui cloche.
```

### Phase 5 — Migration, contrat aval & rescore
Objectif : rejouer les 68 sur le pipeline refondu, ne pas casser le cockpit / digest / calibration.

- [x] L13 — Migration SQLite : colonnes `category`, `score_in_category`, `attain_tech`, `attain_role`, `blocked_by`, `desirability`, `attainability`. Suppression/dépréciation de l'ancien `ReachLevel` persisté.
- [x] L14 — **Contrat `criteria_json` préservé** : adapter `_build_criteria` (API) pour que la forme `[{nom, note, justif, axe}]` survive. Si la structure des critères change → réaligner le parse de la calibration (C-2) AVANT de continuer. Vérifier `ai_snapshot_json` toujours cohérent.
- [x] L15 — `rescore.py --force` sur les 68 (0 LLM, faits déjà ré-extraits en L6) : nouveaux `category` + `score_in_category` + axes.
- [x] L16 — Adaptation minimale cockpit/digest : afficher la catégorie + score intra-case sans format mixte. Affichage riche (piles colorées) = chantier 3, hors-scope.

```
✋ Verify before continuing:
- [ ] rescore --force des 68 produit les catégories sans LLM
- [ ] Le cockpit ouvre sans format mixte (pas d'offre moitié ancien/moitié nouveau)
- [ ] La calibration tient : ouvrir une offre notée recharge la review, criteria_json toujours parsable, snapshot intact
- [ ] verdicts / human_reviews strictement intacts (vérifier en DB)
- [ ] Le digest tourne (tri sur cadran principal parfait/atteignable)

Si tout OK : "go". Sinon dis ce qui cloche.
```

### Phase 6 — Tests & clôture
Objectif : non-régression + fermeture propre.

- [ ] L17 — Tests unitaires : agrégation pondérée (dont contre-exemple C#), `min` rôle + `blocked_by`, catégorisation aux seuils, modulation désirabilité par envie. Non-régression rescore sur les 68. _(différé — à faire en chantier 3 ou session dédiée)_
- [x] L18 — `/handoff` : IMPLEMENTATION coché, STATE/JOURNAL/DECISIONS à jour, ancien IMPLEMENTATION-calibration.md archivé.

```
✋ Verify before continuing:
- [ ] pytest au vert
- [ ] DECISIONS.md : poids importance, min(tech,role), catégorie≠score, role_ceiling tracés
- [ ] IMPLEMENTATION-calibration.md déplacé dans _archive/

Si tout OK : "go". Sinon dis ce qui cloche.
```

---

## Livrables détaillés

1. **L1 — Schéma profil v2 (loader)** — `gregoire.py` valide `{level, desire}` + `role_ceiling`. `S`
2. **L2 — `gregoire.yaml` v2 rempli main** — technos + niveaux provisoires + envies + IC. `S`
3. **L3 — Doc barème 10 paliers** — grille théorique/local/prod × discours, hors donnée. `XS`
4. **L4 — Migration `ExtractedFacts`** — `TechRequirement` + `role_level`, Pydantic + SQLite. `S`
5. **L5 — Prompt extraction enrichi** — importance/techno + role_level, structured output défensif. `M`
6. **L6 — Ré-extraction one-shot 68** — peuple les nouveaux champs, point de bascule no-LLM. `S`
7. **L7 — `attain_tech`** — moyenne pondérée par importance, aliases réutilisés. `M`
8. **L8 — `attain_role`** — portail gradué IC/lead/manager. `S`
9. **L9 — `min` + `blocked_by`** — atteignabilité finale, remplace ReachLevel. `S`
10. **L10 — Désirabilité modulée** — domaine × envie-techno, inconnu neutre. `M`
11. **L11 — Catégorisation 4 cases** — 2 seuils, fonction pure. `M`
12. **L12 — Score intra-case** — tri par case, jamais inter-case. `S`
13. **L13 — Migration SQLite scores** — colonnes catégorie + axes. `M`
14. **L14 — Contrat `criteria_json` préservé** — `_build_criteria` adapté, calibration non cassée. `M`
15. **L15 — `rescore.py --force` 68** — 0 LLM, nouvelles catégories. `S`
16. **L16 — Adaptation cockpit/digest** — catégorie affichée, pas de format mixte. `S`
17. **L17 — Tests** — agrégation, min rôle, seuils, non-régression 68. `M`
18. **L18 — Handoff & archivage** — state à jour, ancien IMPLEMENTATION archivé. `XS`

---

## Points de calibration laissés ouverts (régler sur les 68, hors séquence bloquante)

- Poids exacts `_IMPORTANCE_WEIGHTS` (core/required/nice_to_have)
- Garde-fou "trou sur une core" (cap dur si une core sous seuil) — différé sauf si la dilution se voit sur les 68
- Composition exacte domaine × envie-techno (additive ? plafonnée ?)
- Placement des 2 seuils de catégorisation
- Logique de tri `score_in_category` par case
- Gradient `attain_role` (valeurs un-cran / deux-crans)

---

## Dépendances critiques

- L1 bloque tout l'aval (le schéma profil conditionne désirabilité + atteignabilité).
- L4 bloque L5 (le prompt produit le nouveau schéma de faits).
- L5 validé bloque L6 (pas de batch avant que l'extraction soit jugée stable — GO/NO-GO).
- L6 bloque L7→L12 (le matching consomme les faits enrichis) ET marque le point no-LLM.
- L7+L8 bloquent L9 ; L9+L10 bloquent L11 ; L11 bloque L12.
- L13 bloque L15 ; L14 conditionne la survie de la calibration ; L15 bloque la validation terrain L16.

Chemin critique : `L1 → L4 → L5 → L6 → L7/L8 → L9 → L11 → L13 → L15 → L16`.

---

## Garde-fous

- **§4 sacré** : aucun appel LLM après L6. Si on se surprend à vouloir rappeler le modèle au recalcul d'un score profil-dépendant → frontière mal placée, stop.
- **Calibration (C-2 du chantier précédent)** : si le chantier 2 change la *structure* de `criteria_json` (pas juste les valeurs), le formulaire d'avis généré dynamiquement + `ai_snapshot_json` cassent. L14 réaligne le parse AVANT de continuer. Vérifier à chaque livrable touchant la DB que `human_reviews` est intact.
- **Profil approximatif** : les notes V1 sont saisies à la main, donc fausses à la marge. Ne PAS sur-calibrer les seuils sur un profil qu'on sait provisoire — le chantier Rodin frère fiabilisera les notes ensuite. Calibrer "assez", pas "parfaitement".
- **Non-compensation** : si on se surprend à vouloir qu'un bon axe rachète un axe disqualifiant (moyenne tech qui ravale le rôle, score qui compare deux cases) → c'est le bug qu'on tue, stop.
- **Si la modulation désirabilité par envie (L10) ne change quasi rien** sur les 68 → ne pas empiler : acter que l'envie-techno a peu d'effet sur ce dataset et avancer (signal, pas échec).
- **Schéma cible / architecture.md** : toute évolution = validation humaine explicite avant code (`rules/workflow.md`).
