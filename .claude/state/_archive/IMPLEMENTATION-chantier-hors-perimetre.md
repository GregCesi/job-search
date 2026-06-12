# IMPLEMENTATION — Chantier hors-périmètre : bucket dérivé pour offres non-IC-techniques

> Mode **augment**. Devient le document de travail courant.
> L'ancien (`IMPLEMENTATION-chantier-traces-viewer.md`) est archivé dans `.claude/state/_archive/`, NON écrasé en place.
> Le `.claude/` structurel (rules, commands, settings) n'est PAS régénéré.
> Invariants `architecture.md` à respecter : §4 (0 LLM au recalcul — ce chantier est 100 % Python pur par-dessus des faits déjà extraits), §Persistance (offers/verdicts/human_reviews jamais fusionnées — le verdict de faux-positif passe par `verdicts`, jamais par `offers` ni `human_reviews`).

## Vue d'ensemble

Le pipeline classe chaque offre dans 4 cases (`parfait / reve / atteignable / hors`) croisant désirabilité × atteignabilité. Une classe d'offres pollue ce modèle : celles qui **ne sont pas des postes IC techniques** — soit parce qu'aucune techno n'est exigée (`techs_required == []`), soit parce que le rôle est managérial (`role_level == manager`). Une offre commerciale ou un « Directeur de Programme IA » se voit attribuer une désirabilité/atteignabilité qui n'a pas de sens : `tech_coverage` est dégénéré sur zéro techno, et le domaine peut être « cœur IA » alors que le poste n'a aucune valeur d'apprentissage.

Ce chantier dérive, **en Python pur par-dessus les faits déjà extraits**, un bucket `hors_perimetre` distinct des 4 cases. Une offre hors-périmètre est **gated avant le calcul de score** (pas de désirabilité/atteignabilité dégénérée), reste **visible et inspectable** (pas un filtre d'ingestion), et porte un `criteria_json` vide (rien à calibrer). Sa validation « l'IA a-t-elle eu raison de la sortir ? » passe par un **statut de verdict dédié**, pas par `human_reviews`.

**Raison d'être pédagogique (pas seulement produit) :** ce pipeline est un détecteur d'écart de compétences. Une offre qui répète des technos IA montre un gap mesurable ; piloter/coordonner/manager n'apprend rien sur les lacunes techno. Une offre sans techno est donc **inutile par nature** à l'objectif d'apprentissage, pas seulement indésirable — ce qui justifie un bucket séparé plutôt qu'une simple basse désirabilité.

**Première phase à attaquer : Phase 0 — lecture de l'état réel de `attainability.py`.** Le cadrage suppose que `blocked_by="role"` et `attain_role≈0` existent déjà pour `manager`. Si c'est vrai, `hors_perimetre` est une **promotion d'un état déjà calculé**, pas une logique neuve — et le chantier rétrécit. Rien ne se code avant cette lecture.

---

## Invariant du chantier (non négociable)

**LE BUCKET EST DÉRIVÉ, JAMAIS PERSISTÉ COMME ÉTAT FIGÉ.** `hors_perimetre` se recalcule à chaque (re)score à partir des faits extraits, exactement comme `category`. Conséquence voulue : si l'extracteur s'améliore plus tard et trouve des technos sur une offre auparavant vide, l'offre **sort automatiquement** du bucket au rescore suivant. Aucune colonne ne fige « cette offre est hors-périmètre pour toujours ».

- **La cause est conservée, jamais fusionnée.** Le `OU` (`techs_required == []` OU `role_level == manager`) est un raccourci de **routage** acceptable, mais les deux causes ne se regardent pas pareil et n'ont pas la même durée de vie d'observabilité. On stocke un `hors_perimetre_reason ∈ {no_tech, mgmt_role, null}`, pas un booléen. Fusionner l'information détruirait le diagnostic.
- **Gate AVANT scoring, pas bucket APRÈS.** Si `reason != null`, le calcul de désirabilité/atteignabilité est court-circuité. Raison : `techs_required == []` produit un `attain_tech` dégénéré qui polluerait le `min(attain_tech, attain_role)`. On ne laisse jamais un score aberrant se calculer puis se ranger.
- **`criteria_json` vide.** Une offre hors-périmètre n'a ni domaine à scorer ni `tech_coverage` qui ait du sens. `_build_criteria` retourne `[]` — pas 3 critères fictifs à zéro. `disagreement()` sur liste vide → distance `None`, déjà géré, zéro régression `human_reviews`.
- **0 LLM (§4).** Tout est dérivé de faits déjà extraits. Aucun appel modèle, nulle part.

---

## Décision de cadrage (prise en chat, gravée ici)

`hors_perimetre_reason` se déclenche sur **deux** causes, jamais fusionnées :

| `reason`     | condition                       | nature                                  | observabilité                                  |
|--------------|---------------------------------|-----------------------------------------|------------------------------------------------|
| `no_tech`    | `techs_required == []`           | incertaine (vrai-vide OU bug extraction) | **à inspecter** — c'est ici que vivent les faux positifs |
| `mgmt_role`  | `role_level == manager`          | décision déjà tranchée                   | **compteur** — rien à apprendre en la regardant |
| `null`       | sinon                            | offre IC technique normale               | scorée et catégorisée comme aujourd'hui         |

**Frontière de rôle — tranchée :** seul `role_level == manager` sort. `lead` **reste** dans le gradient `attain_role` existant (pénalisé ~un cran, pas exclu) — un lead technique montre encore des technos, donc garde une valeur d'apprentissage. L'enum `RoleLevel` est fermé à `{ic, lead, manager}` (chantier 2), donc cette frontière couvre tout l'espace : pas de `staff`/`principal`/`director` à gérer.

**Validation humaine du bucket — tranchée :** « cette offre méritait-elle mon intérêt / est-ce un faux positif ? » est un jugement humain **global** sans pendant IA par-critère → c'est un `verdict`, pas un `human_review`. On réutilise la table `verdicts` (déjà upsert, une ligne par offre) avec un statut dédié. **Aucune nouvelle table d'interaction.** `human_reviews` n'est pas touchée.

---

## Calage sur l'existant (à VÉRIFIER en Phase 0 — NON négociable)

Faits du cadrage à confirmer dans le repo réel avant d'écrire la moindre ligne :

- **`attain_role` gradue déjà `manager`** : chantier 2 (`IMPLEMENTATION-chantier-2.md`, L8) spécifie `role_level <= role_ceiling → 100`, un cran au-dessus → ~40, deux crans → 0. Avec `role_ceiling: ic`, `manager` est à deux crans → `attain_role ≈ 0`. **Confirmer la valeur réelle.** Si `manager` ressort déjà `blocked_by="role"` avec `attain_role≈0`, alors `mgmt_role` est une **lecture d'un état existant**, pas un calcul neuf.
- **`blocked_by` existe** : `Attainability.blocked_by ∈ {"tech", "role", None}` (chantier 2, L9). Confirmer qu'il est bien persisté et lisible au moment où le bucket se dérive.
- **`techs_required` est `list[TechRequirement]`** (chantier 2, L4), pas `list[str]`. Donc `techs_required == []` = liste vide d'objets. Confirmer que la liste vide est bien distinguable et qu'aucun fallback ne la remplit d'un objet fantôme (le défaut « fallback silencieux » repéré aux traces n'est PAS corrigé — une offre vide pourrait être un vrai-vide ou un artefact ; c'est exactement pourquoi `no_tech` est à inspecter, pas à compter).
- **`_build_criteria` vit côté API** (`api/`, décision 2026-06-03) et dérive 3 critères des champs scoring. Confirmer le point exact où il s'exécute pour y insérer la garde « offre hors-périmètre → `[]` ».
- **`category` / `score_in_category`** sont calculés où ? (`scoring/`, chantier 2 L11-L12). Confirmer le point d'entrée pour y insérer le gate `hors_perimetre` en amont.
- **Le cockpit attend un `score_in_category` float** : une offre hors-périmètre n'en a pas (pas de scoring). Confirmer comment le front réagit à `None` (cf. garde-fou tri).

> Note de méthode : la Phase 0 est ce qui distingue ce chantier `S` d'un chantier `M`. Si `mgmt_role` est une promotion de `blocked_by="role"` déjà calculé et que le gate s'insère proprement en amont de `category`, le code utile tient en ~3 livrables. Lire d'abord.

---

## Schémas cibles

> À affiner au moment du livrable correspondant — base de travail, pas contrat figé.
> Toute évolution d'un schéma cible ou de `architecture.md` = validation humaine explicite avant code (`rules/workflow.md`).

### `ScoredOffer` — champ ajouté

```python
class HorsPerimetreReason(str, Enum):
    no_tech = "no_tech"        # techs_required == [] (cause incertaine — à inspecter)
    mgmt_role = "mgmt_role"    # role_level == manager (décision tranchée — compteur)

class ScoredOffer(BaseModel):
    # ... champs existants chantier 2 (category, score_in_category, desirability, attainability) ...
    hors_perimetre_reason: HorsPerimetreReason | None = None  # NOUVEAU — dérivé, jamais figé
    # Quand hors_perimetre_reason != None :
    #   - category, score_in_category, desirability, attainability NON calculés (gate amont)
    #     -> valeurs None / sentinelle, à trancher au L (le front doit gérer l'absence)
    #   - criteria_json = []
```

> `category` reste l'enum à 4 cases du chantier 2 — **on n'y ajoute PAS `hors_perimetre`**. Le bucket est un axe orthogonal (nature de l'offre), pas une 5ᵉ valeur de la catégorie désirabilité×atteignabilité. Une offre est soit catégorisée (4 cases), soit hors-périmètre — jamais les deux. Le front lit `hors_perimetre_reason` en premier ; s'il est `null`, il lit `category`.

### Dérivation (Python pur, fonction unique)

```python
def derive_hors_perimetre(facts: ExtractedFacts) -> HorsPerimetreReason | None:
    if not facts.techs_required:          # liste vide d'objets TechRequirement
        return HorsPerimetreReason.no_tech
    if facts.role_level == RoleLevel.manager:
        return HorsPerimetreReason.mgmt_role
    return None
```

> Ordre intentionnel : `no_tech` testé en premier. Une offre manager **sans** techno est étiquetée `no_tech` (la cause la plus en amont / la plus incertaine prime pour l'inspection). À acter au livrable si l'inverse est préféré — mais une offre vide est d'abord un signal d'extraction à vérifier.

### Verdict — statut ajouté

```python
# valeurs de statut verdict existantes (chantier UI) : favori | rejeté | candidaté | masqué
# AJOUT : un statut qui acte le jugement humain sur une offre hors-périmètre
#   hors_perimetre_ok        -> confirmé : l'IA a eu raison, offre sans intérêt
#   hors_perimetre_faux_pos  -> faux positif : l'IA s'est trompée, l'offre méritait mon intérêt
# (noms exacts à trancher au livrable — 2 valeurs, sémantique : verdict de routage, pas note)
```

> `hors_perimetre_faux_pos` posé sur une offre `no_tech` = signal direct d'un bug d'extraction (techs présentes mais non extraites). C'est l'instrument d'inspection du bucket, gratuit, sans table neuve.

---

## Phases

### Phase 0 — Lecture de l'état réel (0 écriture)
Objectif : confirmer/infirmer que `mgmt_role` est une promotion d'un état déjà calculé, et localiser les 3 points d'insertion (gate avant `category`, garde `_build_criteria`, statut `verdicts`). Aucune modification de fichier.

- [x] L0 — Note de lecture (5-8 lignes) répondant à : (a) `attain_role` réel pour `manager` avec `role_ceiling: ic` (≈0 ? `blocked_by="role"` ?) ; (b) point d'entrée exact où `category`/`score_in_category` se calculent (pour gater en amont) ; (c) point exact où `_build_criteria` s'exécute ; (d) comment le front consomme une offre sans `score_in_category` (None toléré ?) ; (e) `techs_required == []` est-il distinguable d'un fallback fantôme dans le code actuel ?

```
✋ Verify before continuing:
- [ ] Réponse tranchée sur (a)-(e), chemins + n° de ligne réels
- [ ] Verdict : mgmt_role = promotion d'un état existant OU calcul neuf (décide la taille du chantier)
- [ ] Aucun fichier modifié

Si tout OK : "go". Sinon dis ce qui cloche.
```

### Phase 1 — Dérivation + gate (Python pur, cœur du chantier)
Objectif : `hors_perimetre_reason` dérivé des faits, et le scoring court-circuité quand `reason != null`.

- [x] L1 — `HorsPerimetreReason` (enum) + `derive_hors_perimetre(facts)` (fonction pure, testable isolément). Ordre `no_tech` avant `mgmt_role` acté.
- [x] L2 — Gate dans le pipeline de scoring : si `derive_hors_perimetre != None`, court-circuiter le calcul désirabilité/atteignabilité/`category`/`score_in_category` AVANT le `min(attain_tech, attain_role)`. Poser `hors_perimetre_reason`, laisser les champs de score à `None`/sentinelle (valeur tranchée ici).
- [x] L3 — `_build_criteria` (API) : si l'offre est hors-périmètre → retourner `[]`. Vérifier que `disagreement()` sur `[]` rend `None` sans crash (déjà attendu, à confirmer).

```
✋ Verify before continuing:
- [ ] Les 3 offres commerciales + le « Directeur de Programme IA » ressortent hors_perimetre avec le bon reason
- [ ] Une offre manager AVEC technos ressort mgmt_role ; une offre vide ressort no_tech (ordre respecté)
- [ ] Aucune offre hors-périmètre n'a de category/score_in_category calculé (gate effectif, pas de min dégénéré)
- [ ] criteria_json == [] pour ces offres ; disagreement() ne crashe pas, rend None
- [ ] verdicts / human_reviews / criteria_json des offres NORMALES strictement intacts
- [ ] 0 appel LLM (§4)

Si tout OK : "go". Sinon dis ce qui cloche.
```

### Phase 2 — Persistance + verdict de validation
Objectif : persister `hors_perimetre_reason` (dérivé, recalculé au rescore), ajouter le statut verdict d'inspection.

- [x] L4 — Migration SQLite : colonne `hors_perimetre_reason` sur `offers` (nullable, écrasée à chaque rescore — c'est un dérivé persisté pour la lecture, JAMAIS une source de vérité figée). Idempotente (`ADD COLUMN IF NOT EXISTS` / check existence).
- [x] L5 — Statuts verdict `hors_perimetre_ok` / `hors_perimetre_faux_pos` (noms tranchés) ajoutés au `Literal` `VerdictIn` côté API + acceptés par l'UPSERT. Aucune autre logique verdict touchée.

```
✋ Verify before continuing:
- [ ] La migration tourne deux fois de suite sans erreur (idempotente)
- [ ] rescore --force repeuple hors_perimetre_reason ; une offre dont l'extraction trouverait des techs sortirait du bucket (réversibilité vérifiée sur un cas forcé)
- [ ] PUT verdict hors_perimetre_faux_pos sur une offre no_tech s'enregistre dans verdicts UNIQUEMENT
- [ ] offers (hors la colonne ajoutée) / human_reviews strictement intacts

Si tout OK : "go". Sinon dis ce qui cloche.
```

### Phase 3 — Rescore + restitution cockpit
Objectif : rejouer les 60 offres, afficher le bucket comme zone inspectable distincte des 4 cases.

- [x] L6 — `rescore.py --force` sur les 60 (0 LLM, faits déjà extraits) : `hors_perimetre_reason` peuplé, 9 offres hors-périmètre (5 no_tech, 4 mgmt_role).
- [x] L7 — Cockpit : zone `hors_perimetre` séparée des 4 cases, groupée/affichable par `reason` (les `no_tech` en priorité de lecture — c'est là que vivent les faux positifs). Pas de `score_in_category` affiché (tri par date ou par titre). Bouton verdict ok/faux-positif disponible sur ces offres.

```
✋ Verify before continuing:
- [ ] Les ~4 offres hors-périmètre sont visibles, groupées par reason, hors des 4 cases
- [ ] Aucune offre hors-périmètre ne fuit dans parfait/reve/atteignable/hors
- [ ] Le cockpit n'a pas de float manquant qui casse l'affichage (score_in_category None géré)
- [ ] Poser un verdict faux-positif sur une offre no_tech est possible et persiste
- [ ] Les 4 cases normales et la calibration human_reviews inchangées

Si tout OK : "go". Sinon dis ce qui cloche.
```

### Phase 4 — Clôture
Objectif : non-régression légère + fermeture propre.

- [x] L8 — `/handoff` : IMPLEMENTATION coché, STATE/JOURNAL/DECISIONS à jour, `IMPLEMENTATION-chantier-traces-viewer.md` archivé dans `_archive/`.

```
✋ Verify before continuing:
- [ ] GET /offers et GET /offers/{id} répondent toujours (API non régressée)
- [ ] DECISIONS.md : OU non fusionné (reason explicite), frontière manager-only (lead reste pénalisé), criteria_json=[] sur hors-périmètre, verdict (pas human_review), dérivé jamais figé — tracés
- [ ] IMPLEMENTATION-chantier-traces-viewer.md déplacé dans _archive/

Si tout OK : "go". Sinon dis ce qui cloche.
```

---

## Livrables détaillés

1. **L0 — Note de lecture** — état réel `attain_role`/`blocked_by` sur manager, 3 points d'insertion localisés, réversibilité confirmable. `XS`
2. **L1 — `HorsPerimetreReason` + `derive_hors_perimetre`** — enum + fonction pure, ordre no_tech>mgmt_role, testable. `XS`
3. **L2 — Gate avant scoring** — court-circuite désir/atteign/category si reason!=null, pas de min dégénéré. `S`
4. **L3 — `_build_criteria` → `[]`** — garde hors-périmètre, disagreement() non régressé. `XS`
5. **L4 — Migration `hors_perimetre_reason`** — colonne nullable idempotente, dérivé persisté pour lecture. `XS`
6. **L5 — Statuts verdict ok/faux-positif** — `VerdictIn` étendu, UPSERT, aucune autre logique touchée. `S`
7. **L6 — `rescore.py --force` 60** — bucket peuplé, ~4 offres, 0 LLM. `XS`
8. **L7 — Cockpit zone hors-périmètre** — groupée par reason, no_tech prioritaire, verdict d'inspection, pas de float manquant. `M`
9. **L8 — Handoff & archivage** — state à jour, chantier-traces-viewer archivé. `XS`

---

## Dépendances critiques

- L0 bloque tout : si `mgmt_role` n'est PAS une promotion d'un état existant (a), L2 change de forme.
- L1 bloque L2 (le gate appelle la fonction de dérivation).
- L2 bloque L3 (la garde criteria_json lit l'état hors-périmètre posé par le gate).
- L4 bloque L6 (pas de rescore persisté sans colonne).
- L2 + L4 bloquent L6 ; L6 bloque L7 (le cockpit affiche ce que le rescore a peuplé).
- L5 indépendant de L1-L4 (peut se faire en parallèle), rangé avant L7 qui l'utilise.

Chemin critique : `L0 → L1 → L2 → L4 → L6 → L7`.

---

## Hors-scope — explicitement reporté

- **Correction du fallback silencieux d'extraction** (`no_tech` peut masquer un bug, pas un vrai-vide) — c'est le chantier de correction des défauts d'extraction repérés aux traces, PAS celui-ci. Ici on **expose** la distinction via le verdict faux-positif ; on ne corrige pas l'extracteur. Si on se surprend à toucher `extractor.py` → hors-scope, stop.
- **Élargir la frontière au-delà de `manager`** (lead/staff/principal hors-périmètre) — tranché : `manager` seul. `lead` reste pénalisé par `attain_role`. L'enum est fermé, pas de staff/principal. Ne pas rouvrir sans décision chat.
- **Réduire `no_tech` à un compteur silencieux** — prématuré. Critère de bascule : sur N lots consécutifs, zéro faux-positif `no_tech` constaté via verdict → alors seulement `no_tech` devient compteur. `mgmt_role` peut être compteur dès maintenant (rien à apprendre). Décision d'observation, pas de code ici.
- **Seuil de falsifiabilité** : combien de faux-positifs `no_tech` avant de juger la frontière mauvaise ? À fixer par Grégoire à l'observation des 60 — métadonnée de discipline, pas livrable.

---

## Garde-fous

- **Dérivé, jamais figé** : si on se surprend à traiter `hors_perimetre_reason` comme une vérité d'ingestion (écrite une fois, jamais recalculée) → on casse la réversibilité, stop. La colonne se réécrit à CHAQUE rescore, comme `category`.
- **Gate avant min, pas bucket après** : si un `min(attain_tech, attain_role)` se calcule sur une offre `no_tech` (attain_tech dégénéré) → le gate est mal placé, stop. Le court-circuit est en amont du scoring.
- **OU non fusionné** : si `hors_perimetre` devient un booléen sans `reason` → on a détruit le diagnostic (no_tech à inspecter vs mgmt_role à compter), stop. La cause est toujours conservée.
- **Pas de 5ᵉ valeur de category** : si on ajoute `hors_perimetre` à l'enum `Category` → on mélange deux axes (nature vs désir×atteign), stop. C'est un champ orthogonal.
- **`human_reviews` intouchée** : la validation du bucket passe par `verdicts` (jugement global), jamais par `human_reviews` (notation par-critère). Si on se surprend à fabriquer un `criteria_json` non vide pour calibrer une offre hors-périmètre → on rouvre le contrat C-2, stop.
- **0 LLM (§4)** : dérivation Python pure par-dessus des faits déjà extraits. Aucun appel modèle. Si une étape veut ré-interroger le modèle pour « confirmer » qu'une offre est hors-périmètre → frontière violée, stop.
- **Schéma cible / architecture.md** : toute évolution = validation humaine explicite avant code (`rules/workflow.md`).
