# IMPLEMENTATION — Chantier review humaine : vérité terrain + suppression scoring + UI sortie LLM

> Mode **augment**. Devient le document de travail courant.
> L'ancien (`IMPLEMENTATION-chantier-hors-perimetre.md`) est archivé dans `.claude/state/_archive/`, NON écrasé en place.
> Le `.claude/` structurel (rules, commands, settings) n'est PAS régénéré.
> Invariants `architecture.md` à respecter : §4 (0 LLM — ce chantier ne touche NI l'ingestion, NI l'extraction ; il lit l'existant en base et ajoute une couche d'interaction humaine), §Persistance (offers/verdicts/human_reviews jamais fusionnées — la review de catégorie est une **donnée d'interaction** de plus, jamais un intrant de recalcul).

## Vue d'ensemble

Le projet a construit tôt une couche de scoring (notes /10 par critère → désirabilité/atteignabilité /100, croix d'atteignabilité) pour un problème de volume qui n'existe pas encore. Cette couche est over-engineerée pour le besoin réel et son affichage est devenu illisible. **Décision actée : on cesse de juger automatiquement.** Le préfiltre LLM+Python reste comme baseline (coût marginal nul, il produit la **catégorie suggérée**), mais c'est désormais l'humain qui tranche. Chaque offre est relue, sa catégorie suggérée est validée ou corrigée, une remarque libre est saisie. Ces verdicts constituent une **base de vérité terrain** — exploitable le jour où le volume augmentera (autres sources) pour refonder extraction et scoring sur preuves, pas sur intuition.

Le chantier fait **trois choses, rien d'autre** : (1) supprimer l'ancien scoring /10-/100, (2) installer la boucle de review (colonnes parallèles + finale dérivée), (3) refondre l'affichage de la sortie LLM (champs en clair + badges techs).

**Première phase à attaquer : Phase 0 — cartographie de l'existant.** Une hypothèse risquée bloque tout : si la catégorie suggérée **dérive** du scoring qu'on veut supprimer, le drop emporte la suggestion qu'on veut garder. Rien de destructif avant que Phase 0 ait parlé.

---

## Invariant du chantier (non négociable)

**LA SUGGESTION N'EST JAMAIS ÉCRASÉE.** La correction humaine vit dans une colonne parallèle (`categorie_corrigee`), jamais en surcharge de la suggestion. `categorie_finale = categorie_corrigee ?? categorie_suggeree` est **dérivée à la volée** (lecture API/SQL), jamais persistée. Toute la valeur du dataset est le **delta** suggéré↔corrigé : le fusionner le détruit.

- **3 états naissent des colonnes, pas d'un champ de statut.** non relue = `reviewed_at IS NULL` ; validée = `reviewed_at` non-null ET `categorie_corrigee IS NULL` ; corrigée = `categorie_corrigee` non-null. Aucun champ `status` à maintenir.
- **`categorie_suggeree` figée au moment de la review** : on capture ce que le préfiltre disait quand l'humain a tranché (cohérent avec le pattern `ai_snapshot_json` de la calibration — la review survit aux évolutions ultérieures du préfiltre).
- **Suppression, pas désactivation.** Le scoring /10-/100 est retiré en commits dédiés (revert-able via git), pas planqué derrière un flag.
- **0 LLM, 0 nouvelle dépendance.** On lit l'existant en base. France Travail et Ollama non sollicités. Stack figée : Python + SQLite + FastAPI + Nuxt 4 + Pinia v3.
- **Périmètre fermé** : ingestion, extraction LLM (prompt/parsing/schéma), scoring **de catégorie**, volume/sources = HORS. Si on se surprend à toucher `extractor.py` ou le prompt → stop.

---

## Calage sur l'existant (à VÉRIFIER en Phase 0 — NON négociable)

Le PROSIT raisonne sur un modèle mental « scores /10 → /100 ». Le repo réel (chantier 2 + hors-périmètre) a une forme **plus avancée** qu'il faut confirmer avant de couper. Faits à trancher dans le code réel :

- **D'où vient la catégorie suggérée ?** Le repo calcule `category ∈ {parfait, reve, atteignable, hors}` (chantier 2, `scoring/`, croisement désirabilité × atteignabilité) + `hors_perimetre_reason ∈ {no_tech, mgmt_role, null}` (chantier hors-périmètre). **C'est ÇA, la « catégorie suggérée » du PROSIT** — pas une note /100. Confirmer : `categorie_suggeree` du chantier = `category` (4 cases) + lecture de `hors_perimetre_reason` ? Trancher comment les deux axes se présentent à l'humain (5 valeurs de choix ? 4 + un état hors-périmètre orthogonal ?).
- **Le scoring à supprimer = quoi exactement ?** Candidats lus dans le repo : `desirability.py`, `attainability.py` (`attain_tech`/`attain_role`/`min`/`blocked_by`), `score_in_category`, les colonnes SQLite `desirability`/`attainability`/`attain_tech`/`attain_role`/`blocked_by`/`score_in_category`, l'affichage cockpit « Désir/Reach » + barres + badges. **`category` et `hors_perimetre_reason` NE sont PAS du scoring à supprimer** — ce sont la suggestion qu'on garde. Cartographier la frontière exacte : que calcule `category` en amont ? Si `category` consomme `desirability`/`attainability`, **le drop casse la suggestion** → il faut d'abord rendre `category` autonome (ou figer la suggestion AVANT de couper). **C'est l'hypothèse risquée.**
- **Le type des techs est-il persisté ?** Chantier 2 a introduit `TechRequirement{name, importance ∈ core/required/nice_to_have}` dans `ExtractedFacts`, persisté dans `extracted_facts_json`. Confirmer que le **type** (`importance`) est bien lisible par l'API/front, pas seulement produit. Si oui → badges colorés (core=bleu, required=vert, nice=gris). Si non → repli badge gris neutre + signalement (PAS de correction d'extraction, hors-scope).
- **`domain`, `role_level`, `seniority` exploitables tels quels ?** Présents dans `ExtractedFacts` (chantier 2). Confirmer qu'ils sont lisibles par le front pour affichage direct.
- **Les colonnes de scoring à dropper nourrissent-elles autre chose ?** Le digest trie sur le cadran (`category`). `_build_criteria` (API) dérive `criteria_json` des champs scoring pour la calibration `human_reviews`. **Confirmer l'impact sur la calibration** : si on supprime desirability/attainability, `_build_criteria` n'a plus de quoi dériver ses 3 critères. Trancher le sort de `human_reviews` + `/export/calibration` + page `/traces` (probablement intacts, mais à acter — la calibration auditait un scoring qu'on supprime).

> Note de méthode : la Phase 0 distingue ce chantier `S/M` d'un chantier qui casse l'amont. Si `category` est déjà autonome (ne lit pas desirability/attainability) → coupe franche en un commit. Sinon → découpler d'abord. **Lire avant de couper.**

---

## Schémas cibles

> À affiner au moment du livrable correspondant — base de travail, pas contrat figé.
> Toute évolution d'un schéma cible ou de `architecture.md` = validation humaine explicite avant code (`rules/workflow.md`).

### Colonnes de review (SQLite, sur `offers` OU table dédiée — tranché en L2 selon Phase 0)

```sql
-- Ajout (migration idempotente, offres existantes intactes → NULL partout)
categorie_suggeree  TEXT,        -- figée au moment de la review (snapshot de category/hors_perimetre)
categorie_corrigee  TEXT,        -- NULL si l'humain valide la suggestion
remarque            TEXT,        -- libre, optionnelle (NULL par défaut)
reviewed_at         TEXT         -- ISO8601 ; NULL = non relue
```

> `categorie_suggeree` est **écrite à la review**, pas à l'ingestion (snapshot du préfiltre tel qu'il était). À trancher en L2 : colonnes sur `offers` (cohérent avec `seen`, donnée d'interaction) vs table dédiée `category_reviews` (cohérent avec `human_reviews`/`trace_notes`). Le PROSIT penche colonnes sur `offers` ; la cohérence repo penche table dédiée. **Décider en L2 d'après Phase 0.**

### États dérivés (jamais stockés)

```
reviewed_at IS NULL                              -> "non_relue"
reviewed_at NOT NULL AND categorie_corrigee NULL -> "validee"
categorie_corrigee NOT NULL                      -> "corrigee"

categorie_finale = categorie_corrigee ?? categorie_suggeree   -- dérivée API/SQL
```

### Payload review (API)

```python
class ReviewIn(BaseModel):
    categorie_corrigee: str | None = None   # None = validation de la suggestion
    remarque: str | None = None             # optionnelle

# en lecture, OfferRow/OfferDetail gagnent :
#   categorie_suggeree, categorie_corrigee, categorie_finale (dérivée), remarque, reviewed_at, etat_review
```

### Badges techs (front)

```
importance == "core"          -> bleu
importance == "required"      -> vert
importance == "nice_to_have"  -> gris
importance absent (repli)     -> gris neutre + signalement "typage techs = futur chantier extraction"
```

---

## Phases

### Phase 0 — Cartographie de l'existant (0 écriture, BLOQUANT absolu)
Objectif : lever l'hypothèse risquée (la suggestion dérive-t-elle du scoring ?) et localiser exactement ce qu'on coupe / ce qu'on garde / ce qu'on affiche.

- [x] L1 — Note de cartographie (1 page max) répondant tranché, chemins + n° de ligne réels : (a) **source de `categorie_suggeree`** = `category` (4 cases) + `hors_perimetre_reason` ? comment les deux se combinent pour l'humain ? (b) **`category` est-il autonome** ou consomme-t-il `desirability`/`attainability` ? (si couplé → l'ordre de coupe change) ; (c) **liste exhaustive** du scoring /10-/100 à retirer (fichiers `scoring/`, colonnes SQLite, affichage cockpit) avec frontière nette vs ce qui reste ; (d) **type des techs** (`importance`) persisté + lisible front ? (e) **`domain`/`role_level`/`seniority`** lisibles front ? (f) **impact calibration** : `_build_criteria` / `human_reviews` / `/export/calibration` / `/traces` survivent-ils au drop, ou faut-il les traiter ?

```
✋ Verify before continuing:
- [ ] Hypothèse risquée tranchée : la catégorie suggérée survit-elle au drop du scoring OUI/NON (avec preuve code)
- [ ] Frontière "à couper" vs "à garder" listée fichier par fichier, colonne par colonne
- [ ] Sort de la calibration (human_reviews) décidé : intacte / adaptée / retirée
- [ ] Aucun fichier modifié

Si tout OK : "go". Sinon dis ce qui cloche.
```

### Phase 1 — Migration colonnes review (additive, non destructive)
Objectif : les colonnes de review existent, les offres déjà en base passent à NULL sans casse.

- [x] L2 — Trancher emplacement (colonnes `offers` vs table dédiée) d'après Phase 0, puis migration idempotente : `categorie_suggeree`, `categorie_corrigee`, `remarque`, `reviewed_at`. `ADD COLUMN IF NOT EXISTS` / check existence. Aucune colonne droppée ici.

```
✋ Verify before continuing:
- [ ] La migration tourne deux fois de suite sans erreur (idempotente)
- [ ] Les offres existantes ont les 4 champs à NULL, le reste intact
- [ ] verdicts / human_reviews strictement intacts

Si tout OK : "go". Sinon dis ce qui cloche.
```

### Phase 2 — Backend review (endpoint + finale dérivée)
Objectif : poser un verdict s'écrit correctement ; la finale se lit dérivée, jamais stockée.

- [x] L3 — Endpoint `PUT /offers/{id}/category-review` : reçoit `{categorie_corrigee?, remarque?}`, capture `categorie_suggeree` (snapshot du préfiltre à l'instant T), écrit `reviewed_at`. Aucune logique de scoring. Upsert (une review courante par offre).
- [x] L4 — `categorie_finale` exposée en lecture (`categorie_corrigee ?? categorie_suggeree`) + `etat_review` dérivé, calculés à la volée dans la réponse API. Jamais persistés.

```
✋ Verify before continuing:
- [ ] PUT review écrit categorie_suggeree (snapshot) + corrigee + remarque + reviewed_at, et RIEN d'autre (offers métier / verdicts / human_reviews intacts en DB)
- [ ] Valider une offre (corrigee=null) -> etat "validee", finale = suggeree
- [ ] Corriger une offre -> etat "corrigee", finale = corrigee, suggeree toujours lisible (delta auditable)
- [ ] 0 appel LLM

Si tout OK : "go". Sinon dis ce qui cloche.
```

### Phase 3 — Suppression du scoring (backend, commit dédié)
Objectif : retirer le scoring /10-/100 mort, après confirmation Phase 0 qu'il ne nourrit pas la suggestion.

- [x] L5 — Drop SQLite des colonnes de scoring confirmées mortes en Phase 0 (migration dédiée, idempotente). La catégorie suggérée survit (vérifié).
- [x] L6 — Retrait code scoring backend (`desirability.py`/`attainability.py`/`score_in_category` selon Phase 0) + ce qui en dépend (rescore, digest, `_build_criteria` si concerné). **Commit isolé, revert-able.** `category`/`hors_perimetre_reason` préservés.

```
✋ Verify before continuing:
- [ ] La catégorie suggérée est toujours produite et lue après le drop (preuve : une offre l'affiche)
- [ ] GET /offers et GET /offers/{id} répondent (API non régressée)
- [ ] Le sort de la calibration acté en Phase 0 est respecté (intacte ou retirée proprement, pas à moitié cassée)
- [ ] Suppression isolée dans un commit dédié (git diff lisible, revert possible)
- [ ] 0 appel LLM

Si tout OK : "go". Sinon dis ce qui cloche.
```

### Phase 4 — UI sortie LLM (facts + badges)
Objectif : remplacer le fouillis de scores par un bloc facts lisible d'un coup d'œil.

- [x] L7 — Composant facts LLM (Nuxt) : `domain`, `role_level`, `seniority` en clair + rangée de badges techs colorés par `importance` (core=bleu / required=vert / nice=gris ; repli gris neutre + signalement si type absent). Remplace l'affichage actuel des faits.
- [x] L10 — Retrait de l'affichage scoring front (bloc scores /100 + croix d'atteignabilité). Fait APRÈS L7 pour ne pas laisser de trou visuel.

```
✋ Verify before continuing:
- [ ] Une offre IA SANS tech exigée saute aux yeux (le diagnostic visé fonctionne)
- [ ] Les badges sont colorés par type si dispo, gris neutre + signalé sinon (pas de faux typage)
- [ ] Plus aucun score /100 ni croix d'atteignabilité affiché ; pas de trou visuel

Si tout OK : "go". Sinon dis ce qui cloche.
```

### Phase 5 — UI review (geste + état)
Objectif : valider/corriger des dizaines d'offres sans friction ; les 3 états visibles.

- [x] L8 — Geste de review : catégorie suggérée **pré-sélectionnée**, validation = 1 clic, correction = sélection d'une autre catégorie, champ remarque optionnel. Le cas majoritaire (suggestion correcte) coûte un clic.
- [x] L9 — Indicateur d'état d'offre : distinction visuelle non relue / validée / corrigée, dérivée de `reviewed_at` + `categorie_corrigee`. Une vue/filtre « à traiter » = `reviewed_at IS NULL`.

```
✋ Verify before continuing:
- [ ] Valider la suggestion coûte 1 clic ; corriger = 1 clic sur une autre catégorie ; remarque jamais obligatoire
- [ ] Les 3 états sont distinguables d'un coup d'œil ; "à traiter" liste bien les non relues
- [ ] Le verdict persiste (recharger la page le recharge sur la bonne offre)

Si tout OK : "go". Sinon dis ce qui cloche.
```

### Phase 6 — Validation terrain + clôture
Objectif : éprouver la boucle sur des offres réelles, fermer proprement.

- [x] L11 — Validation end-to-end manuelle : relire 5 offres réelles (valider 3, corriger 2 avec remarque), vérifier que les 3 états s'affichent, que les verdicts persistent, que le delta suggéré↔corrigé est lisible.
- [x] L12 — `/handoff` : IMPLEMENTATION coché, STATE/JOURNAL/DECISIONS à jour, `IMPLEMENTATION-chantier-hors-perimetre.md` archivé dans `_archive/`.

```
✋ Verify before continuing:
- [ ] 5 offres relues, 3 états observés, verdicts persistés après reload
- [ ] DECISIONS.md : colonnes parallèles + finale dérivée, suppression (pas désactivation), snapshot suggestion, sort calibration — tracés
- [ ] IMPLEMENTATION-chantier-hors-perimetre.md déplacé dans _archive/

Si tout OK : "go". Sinon dis ce qui cloche.
```

---

## Livrables détaillés

1. **L1 — Cartographie Phase 0** — source de la suggestion + autonomie de `category` + frontière scoring + dispo techs/facts + impact calibration, tranchés sur preuve code. Lève l'hypothèse risquée. `S`
2. **L2 — Migration colonnes review** — 4 colonnes nullables idempotentes, offres existantes intactes, emplacement tranché. `S`
3. **L3 — Endpoint review** — `PUT /offers/{id}/review`, snapshot suggestion + corrigee + remarque + reviewed_at, zéro scoring. `S`
4. **L4 — `categorie_finale` dérivée** — `corrigee ?? suggeree` + `etat_review`, à la volée, jamais stockés. `XS`
5. **L5 — Drop SQLite scoring** — colonnes mortes retirées, suggestion survit. `S`
6. **L6 — Retrait code scoring backend** — desirability/attainability/score_in_category + dépendances, commit isolé revert-able. `S`
7. **L7 — Composant facts + badges** — domain/role/seniority en clair + badges techs par type, repli neutre. `M`
8. **L8 — Geste de review** — suggestion pré-sélectionnée, validation/correction 1 clic, remarque optionnelle. `M`
9. **L9 — Indicateur d'état** — non relue / validée / corrigée, dérivé. `S`
10. **L10 — Retrait affichage scoring front** — bloc /100 + croix supprimés, pas de trou visuel. `XS`
11. **L11 — Validation terrain** — 5 offres relues, 3 états, persistance, delta lisible. `S`
12. **L12 — Handoff & archivage** — state à jour, hors-périmètre archivé. `XS`

---

## Dépendances critiques

- **L1 bloque tout** : si la suggestion dérive du scoring (hypothèse risquée), l'ordre des opérations change (découpler `category` AVANT de couper).
- L2 indépendant du reste, part dès Phase 0 finie.
- L5 **conditionné par L1** : ne droppe que si confirmé que la suggestion ne dépend pas des colonnes. Sinon découpler d'abord.
- L3 + L4 après L2 (les colonnes existent).
- L6 après L5 (commit dédié).
- L7 indépendant du backend review, parallélisable dès Phase 0 connue (on sait quoi afficher).
- L8 + L9 après L3/L4 (backend répond) et L7 (composant existe).
- L10 après L7 (pas de trou visuel entre-temps).

Chemin critique : `L1 → L2 → L3/L4 → L5 → L6` // `L1 → L7 → L8/L9 → L10` → `L11`.

---

## Garde-fous

- **Suggestion jamais écrasée** : si on se surprend à écrire la correction par-dessus `categorie_suggeree`, ou à stocker `categorie_finale` → on détruit le delta, stop. Colonnes parallèles + dérivation, toujours.
- **Lire avant couper** : si une ligne de migration de drop ou de suppression de code est écrite avant que L1 ait tranché l'hypothèse risquée → violation du plan, stop.
- **Pas de demi-mesure scoring** : décision = suppression, pas flag. Si on se surprend à masquer derrière une condition « au cas où » → stop, on supprime (git est le filet).
- **Périmètre fermé sur l'extraction** : si le type des techs manque et qu'on est tenté de toucher `extractor.py`/le prompt pour le produire → hors-scope, badge neutre + signalement, stop.
- **Calibration** : `human_reviews` (notation par-critère contre l'IA) auditait le scoring qu'on supprime. Trancher son sort en Phase 0 et l'exécuter proprement — ne pas la laisser à moitié branchée sur des colonnes droppées.
- **0 LLM, 0 dépendance** : tout est lecture base + interaction humaine + UI. Aucun appel modèle, aucune lib nouvelle. Si une étape veut ré-interroger Ollama → frontière violée, stop.
- **Schéma cible / architecture.md** : toute évolution = validation humaine explicite avant code (`rules/workflow.md`).
