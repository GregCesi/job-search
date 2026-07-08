# IMPLEMENTATION — Chantier canonicalisation des technologies

> Mode **augment**. Devient le document de travail courant.
> L'ancien (`IMPLEMENTATION-chantier-html-markdown.md`) est archivé dans `.claude/state/_archive/`, NON écrasé en place.
> Le `.claude/` structurel (rules, commands, settings) n'est PAS régénéré.
> Invariants `architecture.md` à respecter : §1 (la canonicalisation est un nettoyage de vocabulaire AVANT l'intersection, pas un champ source qui fuit), §3 (scoring explicable — l'intersection reste un recouvrement de listes observable), §4 (0 LLM au recalcul — `canonicalize()` est du Python pur, `rescore --force` la reconsomme à froid), §Persistance (rien n'est écrit dans offers/verdicts/human_reviews — `techs_matched`/`techs_missing` restent calculés à la volée comme aujourd'hui).

## Vue d'ensemble

Le matching technos offre↔profil compare aujourd'hui des chaînes via un dict inline `_TECH_ALIASES` (13 entrées, `attainability.py:26-40`). C'est trop pauvre : le LLM extrait du vocabulaire sale (`csharp`, `pl/sql`, `net`, `aspnet`, `vuejs`), les variantes ne tombent pas sur la même forme canonique que le profil, et l'intersection rate des matchs réels (faux négatifs). Le profil a `sql`, l'offre dit `postgresql` → "manquante" à tort.

Ce chantier fait **une seule chose** : externaliser et enrichir la table d'alias (`alias.yaml`, déjà rédigé et figé), et appliquer une fonction `canonicalize()` **des deux côtés** de l'intersection (nom de tech offre ET nom de tech profil) au point de rencontre unique `attainability.py:79`. Plus un sous-produit : `rescore` émet un fichier des technos inconnues triées par fréquence, pour piloter l'enrichissement manuel d'`alias.yaml`.

**Principe directeur (déjà acté en chat) :** *le LLM extrait en vocabulaire libre, la canonicalisation est une transformation déterministe en aval, à la lecture.* La trace LLM garde la sortie brute immuable (`csharp` reste `csharp` dans la trace — même principe que `description_raw`). Le vocabulaire propre n'existe qu'au moment du scoring. Trace = vérité sur le LLM (sale assumé) ; calcul = vérité sur le match (propre).

**Première phase à attaquer : Phase 0 — relecture ciblée.** La reconnaissance est faite (note de repo ci-dessous), mais trois points exacts du code doivent être revérifiés ligne à ligne avant d'écrire. Rien ne se code avant.

---

## Invariant du chantier (non négociable)

**`canonicalize()` EST UNE TRANSFORMATION À LA LECTURE, JAMAIS À L'INGESTION.** Le vocabulaire sale entre une fois (extraction LLM), n'est jamais réécrit. La forme canonique se calcule au scoring — c'est de la dérivation déterministe, rejouable par `rescore --force` à 0 LLM.

- **La trace reste brute (§ principe `description_raw`).** Si on se surprend à canonicaliser au moment de l'extraction, ou à réécrire `techs_required` en base avec les formes canoniques → on détruit la vérité sur le LLM, stop. La trace garde `csharp`, `pl/sql`, `net` tels quels.
- **Des deux côtés ou rien.** `canonicalize()` doit s'appliquer au nom de tech de l'offre ET au nom de tech du profil au point de comparaison. Canonicaliser un seul côté laisse l'intersection rater (`vuejs` offre vs `vue` profil). C'est le piège central de ce chantier.
- **Inconnu laissé brut, jamais retiré.** Une tech sans alias s'auto-canonicalise (elle est sa propre forme) et reste dans le calcul. On ne supprime JAMAIS une tech inconnue — la retirer serait un filtrage inobservable (anti-pattern proscrit). Elle est marquée `unmatched` pour revue humaine, pas effacée.
- **Exclu retiré du calcul, pas de la trace.** Les termes de la section `exclude` (`none`, `os`, `cloud`, `german`…) sont du bruit/non-techs : retirés de l'intersection (ils ne comptent ni comme matché ni comme manquant). Ils restent visibles dans la trace brute. En interne le code distingue exclu vs inconnu ; il n'expose pas cette distinction en temps réel (inspection au cas par cas quand un score cloche).
- **0 LLM (§4).** Toute la chaîne — chargement YAML, canonicalisation, intersection, rapport unmatched — est Python pur. Aucun appel modèle, nulle part. Si une étape veut « demander au LLM si deux technos sont équivalentes » → frontière violée, stop.
- **Pas de matcher flou.** Pas de similarité de chaînes, pas d'embedding de technos, pas de fuzzy match. Sur ~60 offres, c'est de la sur-ingénierie non-déterministe. La table d'alias est explicite et enrichie à la main depuis l'observation.

---

## Décisions de cadrage (prises en chat, gravées ici)

| Décision | Valeur tranchée | Raison | Écarté |
|---|---|---|---|
| Source des alias | **`alias.yaml` externe** (remplace `_TECH_ALIASES` inline) | Enrichissable à la main sans toucher au code, inspectable, versionnable | Garder le dict inline (couplage code/données, illisible à 50+ entrées) |
| Application | **Aux deux côtés** au point de rencontre `attainability.py:79` (offre ET profil) | Canonicaliser un seul côté laisse l'intersection rater (`vuejs`≠`vue`) | Un seul côté (faux négatifs persistants) |
| Moment | **Au scoring, à la lecture** (rejouable par `rescore`) | Trace brute préservée, 0 LLM au recalcul (§4) | À l'ingestion (réécrit la sortie LLM, détruit la trace) |
| Divergence front | **HORS-SCOPE, dette tracée** (A2) | Le front (`OfferDetail.vue:214-224`) a son propre matching brut ; le corriger touche API+Vue → chantier dédié | A1 (back source de vérité, front affiche) — élargit vers l'UI, déborde le scope S |
| Terme exclu | **Retiré du calcul, distingué en interne, non exposé** | Bruit/non-tech ne doit ni matcher ni manquer ; la trace garde tout | Exposer un flux temps réel des exclus (sur-ingénierie pour ce volume) |
| Tech inconnue | **Laissée brute + marquée `unmatched`** | Jamais de filtrage inobservable ; auto-canonicalisation | Retirer (rejet silencieux) ; fuzzy match (non-déterministe) |
| Rapport unmatched | **Fichier émis par `rescore`, trié par fréquence** | Pilote l'enrichissement manuel d'`alias.yaml` ; ~10 lignes, pas d'UI | Endpoint API / digest CLI (over-engineering pour une liste de revue) |

---

## Calage sur l'existant (note de reconnaissance — à REVÉRIFIER ligne à ligne en Phase 0)

Faits du repo établis à la reconnaissance. La Phase 0 les confirme dans le code réel avant d'écrire :

- **`desirability.py` + `attainability.py` sont VIVANTS** (pas supprimés le 15/06 — c'étaient les colonnes DB scoring qui ont été droppées, `db.py:100-107`). Pipeline vivant : `compute_desirability()` + `compute_attainability()` → `categorize(d.score, a.score)` → `save_offer(..., category=cat)` (`run.py:102-105`).
- **L'intersection techs vit dans `_compute_attain_tech`** (`attainability.py:60-93`) : itère `techs_required`, canonicalise via `_canonical()` (l.79), regarde `profile.tech_level(canonical)`. Produit `techs_matched` + `techs_missing`.
- **`_TECH_ALIASES`** : dict inline 13 entrées (`attainability.py:26-40`), wrappé par `_canonical()` (l.43-45). Appelé en attainability l.79 ET ré-importé par `desirability.py` (l.13+48+50). → **deux consommateurs du canonicalizer**, pas un. À confirmer : que fait desirability de la canonicalisation exactement (l.48-50) ?
- **`techs_required` = `list[TechRequirement]{name, importance}`** (`sources/base.py:27-46`), validator v1 coerce les anciennes `list[str]`. Vocabulaire sale réel confirmé : `pl/sql`, `net`, `csharp`, `aspnet`, `vuejs`.
- **Profil** : skills en clés lowercase dans `gregoire.yaml`, lookup via `.lower()` dans `profile.py:33-41`, **pas de canonicalisation côté profil aujourd'hui**. → c'est l'autre moitié à brancher.
- **`rescore.py` vivant** : réutilise `extracted_facts_json` en cache, recalcule desirability+attainability+category sans LLM (sauf `--re-extract`). **Consommateur direct** du changement d'alias.
- **`techs_matched`/`techs_missing`/`attain_tech` NON persistés** : calculés à la volée. → le rapport unmatched ne lit pas la DB, il se construit pendant le run/rescore.

> Note de méthode : la Phase 0 confirme surtout **le second consommateur** (desirability l.48-50) et **la forme exacte de `profile.tech_level()`** — si le profil normalise déjà d'une façon qui entrerait en conflit avec `canonicalize()`, le branchement côté profil change. Lire d'abord.

---

## Schémas cibles

> À affiner au moment du livrable correspondant — base de travail, pas contrat figé.
> Toute évolution d'un schéma cible ou de `architecture.md` = validation humaine explicite avant code (`rules/workflow.md`).

### `alias.yaml` (déjà rédigé et figé — à déposer, pas à concevoir)

Structure existante (fournie) : `aliases:` (canonique → liste de variantes) + `exclude:` (liste de termes retirés du calcul). Emplacement à trancher en L1 (pressenti : `profiles/alias.yaml` à côté de `gregoire.yaml`, ou `orchestrator/job_search/scoring/alias.yaml` près du consommateur). Décision : proximité du consommateur de scoring vs proximité des données de profil.

### Loader + fonction de canonicalisation (module Python)

```python
# Vit dans scoring/ (près du consommateur attainability/desirability).
# Charge alias.yaml une fois, construit l'index inverse variante->canonique.

def load_alias_table(path) -> AliasTable:
    """Charge alias.yaml, construit {variante: canonique} + set(exclude). Validé au chargement."""
    ...

def canonicalize(tech: str, table: AliasTable) -> str | None:
    """
    - variante connue      -> forme canonique
    - terme dans `exclude`  -> None (retiré du calcul, distingué en interne)
    - inconnu               -> tech.lower().strip() inchangé (auto-canonicalisation)
    Retour None = à filtrer du calcul. Retour str = à comparer au profil.
    L'appelant distingue 'exclu' (None) de 'inconnu' (retour == entrée normalisée).
    """
    ...
```

> `canonicalize()` remplace `_canonical()`. Appliqué AUX DEUX côtés : `canonicalize(tech.name, table)` pour l'offre, et le profil est lu via `profile.tech_level(canonicalize(nom_profil, table))` — OU les clés du profil sont canonicalisées au chargement (à trancher en L : canonicaliser à la lecture du profil vs canonicaliser la requête). Le piège : si seul le côté offre passe par `canonicalize()`, `vuejs`→`vuejs` ne trouvera jamais `vue` du profil. Les deux côtés doivent converger vers la même forme.

### Rapport unmatched (fichier plat)

```
# data/unmatched_techs.txt (ou .md) — régénéré à chaque rescore, gitignoré
# Techs extraites des offres qui ne sont NI dans aliases NI dans exclude.
# Triées par fréquence décroissante. Sert à décider quels alias ajouter à la main.
wallix        7
csharpp       3
devbooster    2
...
```

---

## Phases

### Phase 0 — Relecture ciblée (0 écriture)
Objectif : confirmer le second consommateur (desirability) et la forme exacte du lookup profil avant de brancher. Aucune modification de fichier.

- [x] L0 — Note de lecture (6-8 lignes), chemins + n° de ligne réels : (a) ce que `desirability.py` (l.13+48+50) fait de `_canonical()` — matche-t-il aussi des techs, ou autre usage ? le branchement `canonicalize()` doit-il le couvrir ? ; (b) signature et corps exacts de `profile.tech_level()` (`profile.py:33-41`) — normalise-t-il déjà (`.lower()`, strip) d'une façon qui doit s'articuler avec `canonicalize()` ? ; (c) `_canonical()` (`attainability.py:43-45`) — exactement quels appelants, pour tous les rerouter vers `canonicalize()` sans en oublier ; (d) `rescore.py` — point exact où injecter la génération du rapport unmatched (boucle sur offres, accès aux `techs_required`) ; (e) emplacement retenu pour `alias.yaml` (près scoring vs près profil) ; (f) `techs_required` lus comment dans desirability/attainability (objets `TechRequirement`, accès `.name`).

```
✋ Verify before continuing:
- [ ] Réponses tranchées (a)-(f), chemins + lignes réels
- [ ] Verdict : combien de consommateurs de canonicalize() (attainability seul, ou + desirability ?)
- [ ] Articulation canonicalize() ↔ profile.tech_level() tranchée (où canonicaliser le côté profil)
- [ ] Aucun fichier modifié

Si tout OK : "go". Sinon dis ce qui cloche.
```

### Phase 1 — Loader `alias.yaml` + `canonicalize()` (testés isolément, AVANT de toucher le scoring)
Objectif : la fonction propre et testée, AVANT toute intégration. C'est ici que se gagne le chantier (test unitaire > trace, cf. décision Langfuse écartée).

- [x] L1 — Déposer `alias.yaml` à l'emplacement tranché en L0. Créer le module loader + `canonicalize()` dans `scoring/`. Chargement validé (YAML bien formé, index inverse variante→canonique construit une fois, set `exclude`). Détection d'une variante déclarée deux fois (erreur de config explicite, pas silencieuse).
- [x] L2 — Tests unitaires couvrant les trois cas + les pièges réels du dataset : `csharp`→`c#`, `postgresql`→`postgresql` (forme canonique), `vuejs`→ même forme que le profil `vue` (vérifier la convergence des deux côtés sur un cas réel), `pl/sql` (slash préservé ou normalisé — à acter), `none`/`os`/`cloud`→None (exclu), `wallix`→`wallix` (inconnu inchangé). Test de non-régression sur les 13 entrées de l'ancien `_TECH_ALIASES` (toutes doivent produire le même résultat qu'avant).

```
✋ Verify before continuing:
- [ ] Les 3 cas (variante / exclu / inconnu) passent sur des exemples réels du dataset
- [ ] Convergence des deux côtés vérifiée : la forme canonique de l'offre == celle du profil sur vuejs/vue, postgresql/sql
- [ ] Les 13 anciens alias produisent un résultat identique à _TECH_ALIASES (non-régression)
- [ ] Variante dupliquée dans alias.yaml → erreur de chargement explicite, pas un écrasement silencieux
- [ ] Fonction Python pure, 0 LLM, 0 réseau

Si tout OK : "go". Sinon dis ce qui cloche.
```

### Phase 2 — Branchement aux deux côtés (remplace `_canonical()`)
Objectif : `canonicalize()` remplace `_canonical()` partout, appliqué à l'offre ET au profil. L'intersection cesse de rater sur les variantes.

- [x] L3 — Côté profil : canonicaliser le nom de tech au point de lookup (selon l'articulation tranchée en L0 — soit clés profil canonicalisées au chargement, soit requête canonicalisée). Le profil `vue`/`vuejs` et l'offre `vuejs`/`vue` convergent.
- [x] L4 — Côté offre : remplacer `_canonical(tech.name)` par `canonicalize(tech.name, table)` dans `_compute_attain_tech` (`attainability.py:79`). Gérer le retour `None` (exclu) : la tech est retirée du calcul (ni matchée ni manquante), pas comptée comme `techs_missing`.
- [x] L5 — Couvrir le second consommateur si L0 le confirme (`desirability.py` l.48-50). Supprimer `_TECH_ALIASES` inline + `_canonical()` une fois tous les appelants reroutés (commit où l'ancien dict disparaît, `alias.yaml` est seule source).

```
✋ Verify before continuing:
- [ ] Une offre `postgresql` avec profil `sql` ressort MATCHÉE (plus "manquante") — le faux négatif cible est mort
- [ ] Une offre `vuejs` avec profil `vue`(`vuejs`) ressort matchée des deux côtés
- [ ] Un terme exclu (`none`/`os`) n'apparaît NI dans techs_matched NI dans techs_missing
- [ ] `_TECH_ALIASES` et `_canonical()` n'existent plus (alias.yaml seule source) ; tous les appelants reroutés
- [ ] desirability couvert si L0 l'a montré consommateur ; intact sinon
- [ ] 0 appel LLM (§4)

Si tout OK : "go". Sinon dis ce qui cloche.
```

### Phase 3 — Rapport unmatched dans `rescore`
Objectif : `rescore` émet la liste des technos inconnues triées par fréquence, pour piloter l'enrichissement manuel.

- [x] L6 — Dans `rescore.py` (point tranché en L0) : accumuler pendant le passage les techs dont `canonicalize()` rend l'inconnu (retour == entrée normalisée ET absente d'`aliases`). Exclure les exclus (eux sont voulus). Écrire `data/unmatched_techs.txt` trié par fréquence décroissante, écrasé à chaque run. Gitignoré. ~10 lignes de code, 0 LLM.

```
✋ Verify before continuing:
- [ ] `rescore --force` produit data/unmatched_techs.txt avec les techs inconnues triées par fréquence
- [ ] Les exclus (none/os/cloud) n'apparaissent PAS dans le rapport (ils sont voulus, pas à reviewer)
- [ ] Les alias connus n'apparaissent pas (déjà canonicalisés)
- [ ] Le fichier est écrasé proprement à chaque run, gitignoré
- [ ] 0 appel LLM, aucune écriture en base

Si tout OK : "go". Sinon dis ce qui cloche.
```

### Phase 4 — Rescore complet + validation terrain
Objectif : rejouer toutes les offres, vérifier que les faux négatifs ciblés sont morts sans régression.

- [x] L7 — `rescore.py --force` sur toutes les offres (0 LLM, faits déjà extraits). Vérifier : les offres `postgresql`/`vuejs`/`csharp` voient leur `techs_matched` corrigé ; les `category` qui en dépendent (via attain_tech) bougent dans le bon sens ; aucune offre cassée. Lire `unmatched_techs.txt` produit, repérer 2-3 candidats d'alias réels (sans les ajouter — c'est la boucle d'après).

```
✋ Verify before continuing:
- [ ] rescore --force passe sur toutes les offres sans erreur, 0 LLM
- [ ] Les faux négatifs cibles (postgresql/sql, vuejs/vue) sont corrigés en terrain réel
- [ ] Aucune category aberrante introduite (vérifier 3-4 offres connues)
- [ ] unmatched_techs.txt lisible, candidats d'alias identifiables à l'œil
- [ ] verdicts / human_reviews / criteria_json / colonnes review strictement intacts

Si tout OK : "go". Sinon dis ce qui cloche.
```

### Phase 5 — Clôture
Objectif : non-régression légère + fermeture propre + dette front tracée.

- [x] L8 — `/handoff` : IMPLEMENTATION coché, STATE/JOURNAL/DECISIONS à jour, `IMPLEMENTATION-chantier-html-markdown.md` archivé dans `_archive/`. **Dette front gravée** dans DECISIONS + STATE : `OfferDetail.vue:214-224` fait son propre matching brut sans canonicalisation → cockpit affiche des "manquantes" fausses sur les alias → chantier UI dédié (réflexion/PROSIT/kickoff) à venir.

```
✋ Verify before continuing:
- [ ] GET /offers et GET /offers/{id} répondent (API non régressée)
- [ ] DECISIONS.md : alias.yaml externe (remplace _TECH_ALIASES), canonicalize() deux côtés au scoring, exclu→None, inconnu→brut+unmatched, rapport rescore, dette front A2 — tracés
- [ ] STATE.md : dette divergence front explicitement notée comme prochain chantier candidat
- [ ] IMPLEMENTATION-chantier-html-markdown.md déplacé dans _archive/

Si tout OK : "go". Sinon dis ce qui cloche.
```

---

## Livrables détaillés

1. **L0 — Note de lecture Phase 0** — second consommateur (desirability), forme `tech_level()`, appelants de `_canonical()`, point rapport rescore, emplacement alias.yaml. `XS`
2. **L1 — `alias.yaml` déposé + loader + `canonicalize()`** — module scoring, index inverse, set exclude, détection doublon. `S`
3. **L2 — Tests unitaires** — 3 cas + pièges dataset + convergence deux côtés + non-régression 13 anciens alias. `S`
4. **L3 — Branchement côté profil** — lookup canonicalisé, convergence vue/vuejs. `S`
5. **L4 — Branchement côté offre** — `canonicalize()` remplace `_canonical()` en `attainability.py:79`, gestion du None (exclu). `S`
6. **L5 — Second consommateur + suppression `_TECH_ALIASES`** — desirability couvert si besoin, dict inline + `_canonical()` retirés, alias.yaml seule source. `S`
7. **L6 — Rapport unmatched dans rescore** — fichier trié par fréquence, exclus écartés, gitignoré. `S`
8. **L7 — Rescore complet + validation terrain** — faux négatifs cibles morts, pas de régression, candidats d'alias repérés. `S`
9. **L8 — Handoff & archivage + dette front** — state à jour, divergence front gravée. `XS`

---

## Dépendances critiques

- L0 bloque tout : si desirability est un second consommateur réel (a), L5 s'élargit ; si `tech_level()` normalise déjà (b), l'articulation côté profil (L3) change.
- L1 bloque L2 (les tests valident la fonction) et L3/L4/L5/L6 (tous appellent `canonicalize()`).
- L3 + L4 sont les deux moitiés de l'intersection — **aucune valeur si une seule est faite** (le faux négatif persiste). À considérer comme un bloc.
- L5 (suppression `_TECH_ALIASES`) après L4 (sinon on retire le canonicalizer encore utilisé).
- L6 indépendant de L3/L4 (lit `techs_required`, pas le résultat du match) mais rangé après pour ne pas mélanger.
- L7 (rescore) après L3+L4+L5 : la validation terrain n'a de sens qu'une fois les deux côtés branchés.

Chemin critique : `L0 → L1 → L2 → (L3 + L4) → L5 → L7`.

---

## Hors-scope — explicitement reporté

- **Divergence front (A2)** — `OfferDetail.vue:214-224` + `index.vue` font leur propre matching brut sans canonicalisation. Le corriger touche API (exposer/persister `techs_matched`) + Vue. Chantier dédié (réflexion → PROSIT → kickoff). Ici on grave la dette, on ne la traite pas. Si on se surprend à toucher le front → hors-scope, stop.
- **Axe désirabilité découplé de la compétence** — une offre peut exiger une tech désirable mais inconnue (ex. Langfuse). La vraie désirabilité se mesure au niveau du poste, pas tech par tech. Limite de fond de l'approche "intersection de technos" — réflexion notée, pas un chantier.
- **Hiérarchie d'abstraction / relation d'implication** — technos molles (`ia`, `frontend`) non vérifiables ; briques implicites (`tailwind` ⟹ `css`). Solution future = relation d'implication, PAS un alias. Autre chantier. `alias.yaml` ne traite explicitement PAS les technos molles (commentaire dans le fichier).
- **Matcher flou / fuzzy / embeddings de technos** — proscrit : sur-ingénierie + non-déterministe sur ~60 offres. La table est explicite, enrichie à la main.
- **Enrichissement d'`alias.yaml` depuis le rapport** — le rapport unmatched est produit ce chantier-ci ; *décider quels alias ajouter* depuis son observation est la boucle d'usage qui suit, pas un livrable ici.
- **Profil enrichi** — laissé minimal (absence de tech = 0 désir / 0 niveau, signal explicite). Hors-scope.
- **Canonicalisation à l'ingestion / réécriture de la trace** — interdit (§ invariant). La trace reste brute.

---

## Garde-fous

- **Trace brute sacrée** : si une ligne réécrit `techs_required` en base avec les formes canoniques, ou canonicalise au moment de l'extraction → la vérité sur le LLM est détruite (même faute que canonicaliser `description_raw`), stop. La transformation est à la lecture, au scoring.
- **Les deux côtés ou rien** : si seul le côté offre passe par `canonicalize()` et pas le profil (ou l'inverse) → l'intersection rate toujours sur les variantes, le chantier n'a rien réglé, stop. L3 et L4 forment un bloc.
- **Inconnu jamais retiré** : si une tech sans alias disparaît du calcul "parce qu'inconnue" → filtrage inobservable, anti-pattern proscrit, stop. L'inconnu reste, marqué `unmatched`.
- **Exclu ≠ inconnu** : si le code confond un terme `exclude` (voulu hors calcul) avec un inconnu (à reviewer) et le fait remonter dans `unmatched_techs.txt` → le rapport se pollue de bruit voulu, stop. Le rapport ne liste que les inconnus.
- **Pas de fuzzy** : si on se surprend à coder une distance de chaînes, un seuil de similarité, un embedding de technos → sur-ingénierie non-déterministe, stop. Table explicite uniquement.
- **0 LLM (§4)** : tout est Python pur (YAML + dict + intersection + tri). Aucun appel modèle. Si une étape veut "demander au LLM de canonicaliser" → frontière violée, stop.
- **`_TECH_ALIASES` ne survit pas en double** : après L5, le dict inline ne doit plus exister. Deux sources d'alias (inline + yaml) = dérive silencieuse garantie, stop.
- **Schéma cible / architecture.md** : toute évolution = validation humaine explicite avant code (`rules/workflow.md`).
