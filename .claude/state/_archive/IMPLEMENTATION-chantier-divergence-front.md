# IMPLEMENTATION — Chantier divergence front : matching techs canonicalisé exposé par le back

> Mode **augment**. Devient le document de travail courant.
> L'ancien (`IMPLEMENTATION-chantier-canonicalisation.md`) est archivé dans `.claude/state/_archive/`, NON écrasé en place.
> Le `.claude/` structurel (rules, commands, settings) n'est PAS régénéré.
> Invariants `architecture.md` à respecter : §4 (0 LLM au recalcul — `techs_matched`/`techs_missing` sont du Python pur produit au scoring, persisté, JAMAIS recalculé à la lecture API), §"API read-only" (l'API sert ce que l'orchestrateur a produit, ne le refait pas), §Persistance (on ajoute une donnée dérivée sur `offers`, on ne touche à aucune table d'interaction).

## Vue d'ensemble

Le chantier canonicalisation (18/06) a fait converger les technos offre↔profil via `alias.yaml` des deux côtés de l'intersection, dans `_compute_attain_tech` (`attainability.py`). Le back sait donc, au scoring, quelles technos de l'offre matchent le profil (forme canonique) et lesquelles manquent vraiment : `Attainability.techs_matched` / `techs_missing`. Mais **le front les ignore** : `OfferDetail.vue:214-224` + `index.vue` refont leur propre matching en JS, lowercase brut, sans `alias.yaml`. Résultat : le cockpit affiche `vuejs` comme "manquante" alors que le profil a `vue` et que le back l'a matchée. **La vue ment par rapport au scoring réel.**

Ce chantier fait **une seule chose** : faire du back la **seule source de vérité** du matching techs. Le résultat canonicalisé (`techs_matched`/`techs_missing`), déjà calculé au scoring, est **persisté au (re)score** et **exposé tel quel** par l'API. `OfferDetail.vue` et `index.vue` **suppriment leur computed JS de matching** et affichent les listes du back. Plus aucun matching côté front, par construction impossible à faire diverger.

**Principe directeur (tranché en chat) :** *le front lit, ne recalcule pas.* Porter `canonicalize()` en JS (option A) réparerait le symptôme mais graverait une **deuxième implémentation** de la règle métier, qui re-divergerait au prochain enrichissement d'`alias.yaml`. On retire le matching du front, on ne le corrige pas.

**Décision de fond (tranchée en chat) :** *persister `techs_matched`/`techs_missing` au rescore, lus directement par l'API — zéro calcul dans le chemin de requête.* Cohérent avec le traitement déjà réservé à `attain_tech` (dérivé profil-dépendant, recalculé au rescore, jamais à la lecture — §4) et avec « API read-only ». Le recalcul à la volée dans `GET /offers/{id}` est **écarté** : il coupterait l'API au scoring et créerait deux régimes de fraîcheur (score figé / matching live) → incohérence interne au même écran si le profil bouge sans rescore. `rescore --force` reste le point unique de réconciliation profil→données.

**Première phase à attaquer : Phase 0 — relecture ciblée.** Trois points exacts conditionnent la forme du chantier (réceptacle de persistance, point d'assemblage, ampleur du retrait front). Rien ne se code avant.

---

## Invariant du chantier (non négociable)

**LE MATCHING TECHS EST PRODUIT UNE FOIS AU SCORING, PERSISTÉ, LU PARTOUT. JAMAIS RECALCULÉ À LA LECTURE.**

- **Source unique.** `techs_matched`/`techs_missing` naissent dans `_compute_attain_tech` (Python pur, canonicalisé deux côtés). C'est la SEULE implémentation du matching dans tout le projet. Après ce chantier, aucun matching de technos ne vit côté front (ni JS, ni computed, ni lowercase brut).
- **Persisté au (re)score, pas recalculé à la lecture (§4 + API read-only).** Les deux listes se figent au moment où `attain_tech` se calcule, exactement comme lui. L'API les SELECT et les sert. Si on se surprend à appeler `_compute_attain_tech` (ou à charger profil + alias table) depuis une route API → frontière violée, stop. Le profil n'entre jamais dans le navigateur ni dans le chemin de requête.
- **Rejouable par `rescore --force`.** Le profil ou `alias.yaml` bouge → `rescore` réécrit les deux listes comme il réécrit `attain_tech`/`category`. Aucune colonne ne fige un matching "pour toujours" ; c'est un dérivé persisté pour la lecture, jamais une vérité d'ingestion.
- **Le front affiche, ne juge pas.** `OfferDetail.vue`/`index.vue` reçoivent deux listes prêtes et les rendent. Zéro logique de comparaison, zéro chargement de profil, zéro `alias`.
- **0 LLM (§4).** Toute la chaîne (calcul → persistance → API → affichage) est Python/JS pur. Aucun appel modèle nulle part.

---

## Décisions de cadrage (prises en chat, gravées ici)

| Décision | Valeur tranchée | Raison | Écarté |
|---|---|---|---|
| Stratégie | **Back seule source, front affiche** (option B) | Une seule implémentation du matching, impossible à faire diverger par construction | Porter `canonicalize()` en JS (option A) — duplique la règle métier en 2 langages, re-divergence au prochain enrichissement alias |
| Fraîcheur | **Persister au (re)score** | Même nature que `attain_tech` (dérivé profil-dépendant déjà persisté/rescoré) ; cohérence de fraîcheur sur tout l'objet | Recalcul à la volée dans l'API — couple API↔scoring (viole "API read-only"), 2 régimes de fraîcheur → incohérence écran |
| Réceptacle | **À TRANCHER EN PHASE 0** : entrée dédiée enrichie si un JSON de critères/facts est encore servi, SINON 2 colonnes dédiées | Dépend de ce qui survit au drop du 15/06 (chantier review humaine) | — |
| Point de production | `_compute_attain_tech` (`attainability.py`) — déjà calculé là | Les deux listes existent à cet endroit, il suffit de les faire remonter au sérialiseur | Recréer un matching ailleurs (duplication) |
| Front | **Retrait total du matching** (`OfferDetail.vue:214-224` + `index.vue`) | Le front ne doit porter aucune règle métier de matching | Garder un matching front "de secours" (re-divergence garantie) |

---

## Calage sur l'existant (note de reconnaissance — à TRANCHER ligne à ligne en Phase 0)

Faits supposés (reconnaissance Claude Code antérieure + mémoire). La Phase 0 les confirme dans le code réel avant d'écrire :

- **`Attainability.techs_matched` / `techs_missing` existent et sont calculés** dans `_compute_attain_tech` (`attainability.py`), canonicalisés des deux côtés depuis le 18/06. **Calculés puis jetés** : non persistés, non exposés API (reconnaissance Claude Code de cette conv).
- **`attainability.py` est VIVANT** malgré le chantier review humaine du 15/06 : ce sont les **colonnes DB scoring /100** qui ont été droppées (`db.py:100-107`), pas le code de calcul. `attain_tech` se calcule encore comme étape interne de production de `category` (journal 18/06, confirmé sur la canonicalisation). **À reconfirmer** : `attainability` tourne-t-il encore dans `run.py`/`rescore.py` ou seulement dans `categorize` ?
- **`criteria_json` : statut incertain.** Le 15/06 a retiré `_build_criteria` (normaliseur API) et l'affichage scoring. **À trancher en Phase 0** : `criteria_json` est-il encore peuplé en base et servi au front, ou mort ? → décide le réceptacle (entrée enrichie vs colonnes dédiées).
- **Migration SQLite** : pattern maison `ADD COLUMN IF NOT EXISTS` / check existence, idempotent, module-load (`db.py`). Pas d'Alembic. Réutilisé si colonnes dédiées.
- **Front** : `OfferDetail.vue:214-224` fait le matching JS brut (dette gravée 18/06). **À confirmer** : `index.vue` le duplique-t-il, et le **profil est-il chargé côté front** pour pouvoir matcher (si oui, on retire aussi ce chargement) ?
- **`rescore.py`** : recalcule desirability/attainability/category sans LLM. **Consommateur direct** — c'est là que les deux listes se persisteront.

> Note de méthode : la Phase 0 distingue ce chantier `S` d'un `S/M`. Si `criteria_json` est encore servi → on enrichit son entrée tech, zéro migration SQL (chantier S). Si mort → 2 colonnes dédiées + migration (chantier S/M). Et si `techs_matched`/`missing` ne remontent pas jusqu'au point de sérialisation → un fil à faire remonter (quelques lignes). Lire d'abord.

---

## Schémas cibles

> À affiner au moment du livrable correspondant — base de travail, pas contrat figé.
> Toute évolution d'un schéma cible ou de `architecture.md` = validation humaine explicite avant code (`rules/workflow.md`).

### Persistance — DEUX FORMES POSSIBLES, tranchées en Phase 0

**Forme A — `criteria_json` (ou équivalent JSON) encore vivant :**
enrichir l'entrée tech avec `matched` / `missing`. Pas de migration SQL (JSON sans schéma rigide). L'API qui sert déjà ce JSON les expose sans changement de route.

**Forme B — `criteria_json` mort → 2 colonnes dédiées sur `offers` :**
```sql
-- idempotent (check existence), module-load, pattern db.py existant
ALTER TABLE offers ADD COLUMN techs_matched_json TEXT;   -- JSON list[str], formes canoniques
ALTER TABLE offers ADD COLUMN techs_missing_json TEXT;   -- JSON list[str], formes canoniques
-- nullable ; repeuplées à CHAQUE rescore (dérivé, jamais figé)
```

### API — réponse détail (et liste si `index.vue` matche aussi)

```python
# OfferDetail (api/schemas.py) gagne :
techs_matched: list[str] = []   # servi tel quel depuis la persistance, AUCUN recalcul
techs_missing: list[str] = []
# Si index.vue matche aussi → exposer également sur OfferRow (sinon détail seul suffit).
```

### Front — ce qui DISPARAÎT

```
OfferDetail.vue:214-224  → computed/logique de matching JS supprimé,
                           remplacé par rendu direct de offer.techs_matched / offer.techs_missing
index.vue                → si matching présent, idem
chargement du profil côté front (s'il existe pour le matching) → supprimé
```

---

## Phases

### Phase 0 — Relecture ciblée (0 écriture)
Objectif : trancher le réceptacle de persistance, confirmer le point d'assemblage, mesurer l'ampleur du retrait front. Aucune modification de fichier.

- [x] L0 — Note de lecture (8-10 lignes), chemins + n° de ligne réels :
  (a) **`techs_matched`/`techs_missing`** : confirmés produits dans `_compute_attain_tech` ? Sous quelle forme exacte (list[str] de formes canoniques) ? Remontent-ils jusqu'au point où l'offre est sérialisée/sauvée, ou sont-ils jetés dans `Attainability` consommé localement ?
  (b) **Point de (re)score exact** où l'offre est persistée (`run.py`/`rescore.py` + `save_offer` dans `storage/`) : où insérer l'écriture des deux listes ?
  (c) **`criteria_json` vivant ou mort ?** Encore peuplé en base ? Encore servi par `GET /offers/{id}` ? → tranche Forme A (enrichir JSON) vs Forme B (2 colonnes). **C'est l'inconnu central.**
  (d) **`api/offers.py` + `api/schemas.py`** : forme actuelle de la réponse détail ; point d'ajout de `techs_matched`/`techs_missing`.
  (e) **`OfferDetail.vue:214-224`** : code exact du matching JS, données d'entrée consommées (liste techs offre ? **profil chargé côté front ?**), sortie affichée.
  (f) **`index.vue`** : matching dupliqué ou non ? → décide si on expose aussi sur `OfferRow`.

```
✋ Verify before continuing:
- [ ] (a)-(f) tranchés, chemins + lignes réels
- [ ] Réceptacle décidé : Forme A (criteria_json/JSON vivant, enrichi) OU Forme B (2 colonnes dédiées + migration)
- [ ] techs_matched/missing remontent-ils au sérialiseur, ou fil à faire remonter ? (mesure le travail back)
- [ ] index.vue matche-t-il aussi ? (décide OfferRow)
- [ ] Profil chargé côté front pour le matching ? (décide si on le retire aussi)
- [ ] Verdict de taille : S (Forme A) ou S/M (Forme B)
- [ ] Aucun fichier modifié

Si tout OK : "go". Sinon dis ce qui cloche.
```

### Phase 1 — Persistance des deux listes au (re)score (back)
Objectif : `techs_matched`/`techs_missing` écrits au scoring, repeuplés au rescore. 0 LLM.

- [x] L1 — Selon Phase 0 : (Forme B) migration idempotente `ADD COLUMN techs_matched_json` / `techs_missing_json` sur `offers` (check existence, module-load). (Forme A) pas de migration.
- [x] L2 — Faire remonter `techs_matched`/`techs_missing` de `_compute_attain_tech` jusqu'au point de persistance (si Phase 0(a) montre qu'ils sont jetés en route). `save_offer` (ou équivalent) écrit les deux listes (sérialisées JSON) dans le réceptacle tranché. Écrit au run ET au rescore.

```
✋ Verify before continuing:
- [ ] rescore --force repeuple les deux listes sur toutes les offres (0 LLM)
- [ ] Une offre `vuejs` (profil `vue`) a `vuejs`/`vue` dans techs_matched, PAS dans techs_missing (forme canonique persistée correcte)
- [ ] Une offre `postgresql` (profil `sql`) idem (faux négatif mort en base)
- [ ] Les deux listes se réécrivent au rescore (dérivé, pas figé) — vérifier sur un cas forcé
- [ ] verdicts / human_reviews / colonnes review strictement intacts
- [ ] 0 appel LLM

Si tout OK : "go". Sinon dis ce qui cloche.
```

### Phase 2 — Exposition API (read-only, aucun recalcul)
Objectif : l'API SELECT les deux listes et les sert. Zéro appel à `_compute_attain_tech`, zéro chargement profil/alias dans l'API.

- [x] L3 — `api/schemas.py` : `techs_matched: list[str]` / `techs_missing: list[str]` sur `OfferDetail` (+ `OfferRow` si Phase 0(f) montre `index.vue` consommateur). `api/offers.py` : inclure les deux colonnes/champs dans le SELECT + mapping, désérialiser le JSON. Lecture seule stricte.

```
✋ Verify before continuing:
- [ ] GET /offers/{id} renvoie techs_matched / techs_missing servis depuis la persistance
- [ ] AUCUN appel à _compute_attain_tech, AUCUN chargement de profil/alias dans le chemin API (grep de contrôle)
- [ ] Si OfferRow concerné : GET /offers les inclut aussi
- [ ] 0 appel LLM, 0 écriture

Si tout OK : "go". Sinon dis ce qui cloche.
```

### Phase 3 — Retrait du matching front (le cœur du chantier)
Objectif : `OfferDetail.vue`/`index.vue` n'ont plus aucune logique de matching ; ils affichent les listes du back.

- [x] L4 — `OfferDetail.vue` : supprimer le computed/logique de matching brut (l.214-224), remplacer par le rendu direct de `offer.techs_matched` / `offer.techs_missing` reçus de l'API. Conserver l'apparence (badges matchées/manquantes), seule la source change.
- [x] L5 — `index.vue` : si matching présent (Phase 0(f)), même retrait. Supprimer le **chargement du profil côté front** s'il n'existait que pour ce matching (Phase 0(e)). Vérifier qu'aucun autre composant ne dépend du matching front retiré.

```
✋ Verify before continuing:
- [ ] OfferDetail affiche les badges techs depuis le back ; `vuejs`/`postgresql` ne sont PLUS faussement "manquantes"
- [ ] Plus aucune logique de matching JS dans OfferDetail.vue ni index.vue (grep `toLowerCase`/comparaison techs = 0)
- [ ] Profil retiré du front s'il n'y servait qu'au matching (le navigateur ne charge plus gregoire.yaml)
- [ ] La vue reflète exactement le scoring back (cohérence cockpit↔scoring atteinte — objectif du chantier)

Si tout OK : "go". Sinon dis ce qui cloche.
```

### Phase 4 — Validation terrain + clôture
Objectif : cohérence vue↔back vérifiée sur cas réels, fermeture propre.

- [x] L6 — Validation end-to-end : ouvrir 3-4 offres aux variantes connues (`vuejs`, `postgresql`, `csharp`...) → les badges du cockpit == matching back == ce que le scoring a utilisé. Plus aucune divergence.
- [x] L7 — `/handoff` : IMPLEMENTATION coché, STATE/JOURNAL/DECISIONS à jour, `IMPLEMENTATION-chantier-canonicalisation.md` archivé dans `_archive/`. Graver la décision (back source unique, persistance au rescore, recalcul-à-la-volée écarté) dans DECISIONS.

```
✋ Verify before continuing:
- [ ] GET /offers et GET /offers/{id} répondent (API non régressée)
- [ ] Cockpit ↔ scoring back cohérents sur les variantes (dette 18/06 résolue)
- [ ] DECISIONS.md : back seule source, techs_matched/missing persistés au rescore, recalcul-à-la-volée écarté (couplage API↔scoring + 2 régimes de fraîcheur), retrait matching front — tracés
- [ ] IMPLEMENTATION-chantier-canonicalisation.md déplacé dans _archive/

Si tout OK : "go". Sinon dis ce qui cloche.
```

---

## Livrables détaillés

1. **L0 — Note de lecture Phase 0** — réceptacle (criteria_json vivant ?), point d'assemblage, remontée des listes, ampleur retrait front. `XS`
2. **L1 — Migration (Forme B) ou no-op (Forme A)** — 2 colonnes idempotentes si JSON mort. `XS`
3. **L2 — Persistance au (re)score** — listes remontées jusqu'à `save_offer`, écrites au run + rescore. `S`
4. **L3 — Exposition API** — `OfferDetail`(+`OfferRow`?) enrichis, SELECT, read-only strict. `S`
5. **L4 — Retrait matching `OfferDetail.vue`** — computed JS supprimé, rendu depuis le back. `S`
6. **L5 — Retrait matching `index.vue` + profil front** — duplication retirée, profil dégagé du navigateur. `S`
7. **L6 — Validation terrain** — cohérence cockpit↔scoring sur variantes réelles. `XS`
8. **L7 — Handoff & archivage** — state à jour, décision gravée. `XS`

---

## Dépendances critiques

- L0 bloque tout : tranche Forme A/B (réceptacle) et si les listes remontent déjà au sérialiseur.
- L1 (migration) avant L2 si Forme B ; no-op si Forme A.
- L2 (persistance) bloque L3 (l'API ne sert que ce qui est persisté).
- L3 (API) bloque L4/L5 (le front ne peut afficher que ce que l'API expose).
- L4 et L5 indépendants entre eux, mais L5 dépend de Phase 0(f) pour savoir s'il y a lieu.
- L6 après L3+L4(+L5) : la cohérence terrain n'a de sens qu'une fois la chaîne complète.

Chemin critique : `L0 → L2 → L3 → L4 → L6`.

---

## Hors-scope — explicitement reporté

- **Enrichissement d'`alias.yaml`** depuis `unmatched_techs.txt` — boucle d'usage distincte (gravée 18/06), pas ce chantier. Ici on EXPOSE le matching, on n'améliore pas la table.
- **Axe désirabilité découplé de la compétence** (offre exigeant une tech désirable mais inconnue) — limite de fond de l'approche intersection, réflexion notée 18/06, autre sujet.
- **Hiérarchie d'abstraction / implication** (`tailwind` ⟹ `css`) — solution future = relation d'implication, pas un alias, autre chantier.
- **Re-typage des badges par importance** (core/required/nice) — l'affichage des badges existe déjà (chantier review 15/06) ; ici on corrige la SOURCE matched/missing, pas le typage. Si on se surprend à toucher l'importance → hors-scope.
- **Toute modification du calcul de matching lui-même** — `_compute_attain_tech` est correct depuis le 18/06. Ce chantier le PERSISTE et l'EXPOSE, ne le retouche pas. Si on se surprend à modifier la logique d'intersection → stop.

---

## Garde-fous

- **API read-only sacrée** : si une ligne d'`api/` appelle `_compute_attain_tech`, charge `gregoire.yaml` ou `alias.yaml`, ou recalcule un matching → couplage API↔scoring, frontière violée, stop. L'API SELECT et sert, point.
- **Dérivé, jamais figé** : si `techs_matched`/`missing` ne se réécrivent pas au rescore (traités comme vérité d'ingestion) → on casse la réconciliation profil→données, stop. Repeuplés à CHAQUE rescore, comme `attain_tech`.
- **Une seule implémentation du matching** : si à la fin du chantier une logique de comparaison de technos survit côté front (computed, lowercase, alias JS) → on a laissé la porte à la re-divergence, stop. Le front affiche deux listes prêtes, rien d'autre.
- **Pas de profil dans le navigateur** : si le front continue de charger `gregoire.yaml` après le retrait → le profil n'a rien à faire côté client, stop (sauf usage légitime non-matching confirmé en Phase 0).
- **0 LLM (§4)** : toute la chaîne est Python/JS pur. Aucun appel modèle. Si une étape veut "demander au LLM si deux technos matchent" → frontière violée, stop.
- **Schéma cible / architecture.md** : toute évolution = validation humaine explicite avant code (`rules/workflow.md`).
