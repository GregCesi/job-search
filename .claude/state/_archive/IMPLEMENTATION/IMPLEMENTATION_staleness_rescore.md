# IMPLEMENTATION — Séparation avis IA / avis humain + staleness post-rescore

## Vue d'ensemble

Problème : après un rescore (chantiers G, P), les offres déjà annotées gardent `etat_review=validee/corrigee` mais le scoring IA a changé. L'utilisateur ne voit pas la différence entre l'ancien et le nouveau scoring, et les offres ne repassent pas dans la file "à traiter".

Deux livrables couplés :
1. **Staleness** — détecter que l'IA a changé d'avis depuis la dernière review. Les offres stale repassent dans "à traiter" mais gardent leurs annotations (remarque, categorie_corrigee).
2. **Séparation visuelle** — l'avis IA (read-only) et l'avis humain (éditable) sont deux blocs distincts dans OfferDetail. L'écart entre les deux est visible d'un coup d'oeil.

Invariants : cf. `rules/architecture.md` §4 (0 LLM), `rules/frontend.md` (champs dérivés jamais persistés), `DECISIONS.md` 2026-06-15 (categorie_suggeree = snapshot figé).

## Schémas cibles

Base de travail, pas contrat figé — à affiner au livrable correspondant.

### API — nouveaux champs dérivés (jamais persistés)

```python
# Dans _derive_review_fields() — api/offers.py
{
    # existants
    "categorie_suggeree": str | None,      # snapshot figé au moment de la review
    "categorie_corrigee": str | None,
    "categorie_finale": str | None,        # corrigee ?? suggeree
    "etat_review": str | None,             # non_relue | validee | corrigee | a_revoir (NOUVEAU)
    "remarque": str | None,
    "reviewed_at": str | None,
    # nouveaux
    "review_stale": bool,                  # True si l'IA a changé d'avis depuis la review
    "suggestion_actuelle": str | None,     # ce que l'IA pense MAINTENANT (category ou hors_perimetre)
}
```

### Pydantic — OfferRow / OfferDetail (api/schemas.py)

```python
review_stale: bool = False
suggestion_actuelle: str | None = None
```

### TypeScript — OfferRow / OfferDetail (stores/offers.ts)

```typescript
review_stale: boolean
suggestion_actuelle: string | null
```

## Phases

### Phase 1 — Backend : staleness + `a_revoir` (L1–L4)

- [x] **L1** — `_derive_review_fields()` : ajouter `suggestion_actuelle` (= `hors_perimetre` si `hors_perimetre_reason IS NOT NULL`, sinon `category`) et `review_stale` (= `reviewed_at IS NOT NULL AND suggestion_actuelle != categorie_suggeree`). Signature : prend `row` comme aujourd'hui, retourne les mêmes clés + les 2 nouvelles. **XS**

- [x] **L2** — `etat_review` : quand `review_stale=True`, dériver `"a_revoir"` au lieu de `"validee"` ou `"corrigee"`. L'état `a_revoir` signifie "déjà relue, mais l'IA a bougé depuis". **XS**

- [x] **L3** — Schemas Pydantic : ajouter `review_stale: bool = False` et `suggestion_actuelle: str | None = None` sur `OfferRow` et `OfferDetail` (héritage). **XS**

- [x] **L4** — Filtre SQL `etat_review=a_revoir` dans `list_offers()` : clause `o.reviewed_at IS NOT NULL AND CASE WHEN o.hors_perimetre_reason IS NOT NULL THEN 'hors_perimetre' ELSE o.category END != COALESCE(o.categorie_suggeree, '')`. Vérifier aussi `export.py` si le même filtre y est utilisé. **S**

✋ Verify before continuing:
- [ ] `GET /offers?etat_review=non_relue,a_revoir` retourne les offres non relues ET les stale
- [ ] Une offre relue dont `category` n'a pas changé a `review_stale=false, etat_review=validee`
- [ ] Une offre relue dont `category` a changé a `review_stale=true, etat_review=a_revoir`
- [ ] `suggestion_actuelle` reflète le scoring actuel, pas le snapshot

Si tout est OK : "go". Sinon dis ce qui cloche.

### Phase 2 — Frontend : séparation visuelle + gestion staleness (L5–L9)

- [x] **L5** — Types TS + VIEW_PRESETS : ajouter `review_stale: boolean` et `suggestion_actuelle: string | null` aux interfaces `OfferRow` et `OfferDetail`. Mettre à jour `a_traiter` preset : `etat_review: 'non_relue,a_revoir'`. **XS**

- [x] **L6** — OfferDetail.vue — bloc "Avis IA" (read-only) : nouveau bloc au-dessus de la section review. Affiche `suggestion_actuelle` sous forme de badge catégorie (même style que les boutons mais non cliquable) + `score_breakdown`. Les badges techs (section "Faits extraits") restent où ils sont — c'est déjà de l'info IA. **S**

- [x] **L7** — OfferDetail.vue — bloc "Mon avis" (éditable) : restructurer la section existante "Catégorie". Les boutons de sélection de catégorie restent, le textarea remarque reste, le bouton submit reste. Le `suggestedCategory` pour la logique validation/correction utilise `suggestion_actuelle` (pas `categorie_suggeree`). **S**

- [x] **L8** — Indicateur stale : quand `review_stale=true`, afficher un bandeau entre les deux blocs : "Rescoré — l'IA suggérait [categorie_suggeree], dit maintenant [suggestion_actuelle]". Afficher la remarque précédente en italique si elle existe. L'état `a_revoir` a son propre label/classe dans les helpers etatLabel/etatClass. **S**

- [x] **L9** — Re-confirmation : quand l'utilisateur clique "Valider" ou "Corriger" sur une offre stale, le PUT `/category-review` re-snapshot `categorie_suggeree` au `category` actuel (c'est déjà le comportement de l'endpoint — vérifier que ça fonctionne). Après submit, `review_stale` repasse à `false`. **XS**

✋ Verify before continuing:
- [ ] Onglet "À traiter" : les offres stale apparaissent dans la liste
- [ ] Ouverture d'une offre stale : bloc "Avis IA" montre la catégorie actuelle, bloc "Mon avis" montre l'ancienne annotation
- [ ] Bandeau "Rescoré" visible entre les deux blocs avec before/after
- [ ] Validation d'une offre stale : elle disparaît de "à traiter", `review_stale=false`
- [ ] Offre non stale : pas de bandeau, comportement identique à l'existant (non-régression)

Si tout est OK : "go". Sinon dis ce qui cloche.

## Livrables détaillés

1. **L1** — `_derive_review_fields()` : 2 champs dérivés (`suggestion_actuelle`, `review_stale`) — **XS**
2. **L2** — `etat_review` : nouvel état `a_revoir` — **XS**
3. **L3** — Schemas Pydantic : 2 champs sur OfferRow — **XS**
4. **L4** — Filtre SQL `a_revoir` dans list_offers + export — **S**
5. **L5** — Types TS + preset `a_traiter` — **XS**
6. **L6** — Bloc "Avis IA" read-only dans OfferDetail — **S**
7. **L7** — Bloc "Mon avis" éditable restructuré — **S**
8. **L8** — Bandeau stale + label `a_revoir` — **S**
9. **L9** — Re-confirmation (vérification du flow existant) — **XS**

## Dépendances critiques

- L1/L2/L3 bloquent L4 (le filtre SQL utilise la même logique de staleness)
- L4 bloque L5 (le preset front envoie `a_revoir` que le back doit comprendre)
- L5 bloque L6–L9 (les types doivent exister pour le template)

## Garde-fous

- Si `categorie_suggeree IS NULL` (offre jamais relue) → `review_stale = False` par définition (pas de review à comparer). Ne jamais faire passer une offre jamais relue en `a_revoir`.
- Si `category IS NULL` ET `hors_perimetre_reason IS NULL` (offre pas encore scorée) → `suggestion_actuelle = None`, `review_stale = False`.
