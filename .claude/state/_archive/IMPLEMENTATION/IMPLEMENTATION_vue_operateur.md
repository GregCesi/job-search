# IMPLEMENTATION — Vue opérateur (élagage onglets, verdicts HP, tri & filtres)

## Vue d'ensemble

Refondre la vue `/operateur` : supprimer les onglets sans plus-value (Toutes relues, Retenues), remettre la classification faux-positif sur les offres hors-périmètre, et enrichir le tableau + filtres pour un usage quotidien d'exploration (tri par entreprise, lieu, filtres source/review/HP combinables).

Première chose à attaquer : élaguer les onglets et câbler les verdicts HP dans le détail offre.

## Schémas cibles

_Base de travail, pas contrat figé — à affiner au livrable correspondant._

### Frontend — `OperatorView` + presets (stores/offers.ts)

```typescript
// Opérateur — après élagage
type OperatorView = 'a_traiter' | 'hors_perimetre' | 'tout'

const VIEW_PRESETS = {
  // ... candidat inchangé ...
  // Opérateur
  a_traiter:      { etat_review: 'non_relue', hors_perimetre: false, sort: 'category',   order: 'desc' },
  hors_perimetre: { hors_perimetre: true,                            sort: 'fetched_at', order: 'desc' },
  tout:           {                                                   sort: 'category',   order: 'desc' },
}
```

### Frontend — Verdicts HP dans OfferDetail (mode opérateur, onglet HP)

```typescript
// Verdicts affichés quand l'offre a hors_perimetre_reason (onglet HP ou détail d'une offre HP)
const HP_VERDICTS = [
  { status: 'hors_perimetre_ok',       label: '✓ Confirmé HP',  activeClass: '...' },
  { status: 'hors_perimetre_faux_pos', label: '✗ Faux positif', activeClass: '...' },
]
```

### Backend — `_SORT_COLS` (offers.py:25)

```python
_SORT_COLS = {"fetched_at", "title", "company", "category", "seen_candidat", "location"}
#                                                                              ^^^^^^^^ ajouté
```

### Frontend — colonnes triables (OffersTable.vue)

```typescript
const COLS = [
  { key: 'title',         label: 'Poste',       sortable: true  },
  { key: 'company',       label: 'Entreprise',  sortable: true  },  // était false
  { key: 'contract_type', label: 'Contrat',     sortable: false },
  { key: 'location',      label: 'Lieu',        sortable: true  },  // était false
  { key: 'category',      label: 'Catégorie',   sortable: true  },
  { key: 'fetched_at',    label: 'Récupéré',    sortable: true  },
  { key: 'verdict',       label: 'Verdict',     sortable: false },
]
```

### Frontend — FiltersPanel enrichi

Ajout de 3 filtres (backend les supporte déjà) :
- **Source** : select (Tous / France-Travail / Remotive / Indeed)
- **État review** : select (Tous / Non relue / Validée / Corrigée)
- **Hors-périmètre** : select (Tous / Uniquement HP / Exclure HP)

## Phases

### Phase 1 — Élagage onglets + verdicts HP (L1–L5)

- [x] **L1** — Store : supprimer `a_relire` et `retenues_op` de `OperatorView`, `VIEW_PRESETS`, et `ActiveView`. Default view reste `a_traiter`.
- [x] **L2** — `operateur.vue` : retirer les entrées `a_relire` et `retenues_op` du tableau `VIEWS`. Résultat : 3 boutons (À traiter / Hors-périmètre / Tout).
- [x] **L3** — `OfferDetail.vue` : en mode opérateur, quand l'offre a un `hors_perimetre_reason`, afficher les boutons verdict HP (✓ Confirmé HP / ✗ Faux positif) à la place ou en plus des verdicts standards. Les verdicts standards restent disponibles pour les offres non-HP.
- [x] **L4** — `VerdictBadge.vue` : vérifier que `hors_perimetre_ok` et `hors_perimetre_faux_pos` ont un rendu (label + couleur). Déjà présent.
- [x] **L5** — Vérification : build OK, 3 onglets, verdicts HP câblés. Validé manuellement.

✋ Verify before continuing:
- [x] `/operateur` affiche exactement 3 onglets : À traiter, Hors-périmètre, Tout
- [x] Onglet Hors-périmètre → ouvrir une offre → boutons ✓ Confirmé HP / ✗ Faux positif visibles
- [x] PUT verdict `hors_perimetre_ok` / `hors_perimetre_faux_pos` → 204, badge affiché
- [x] Workflow review catégorie inchangé (valider/corriger fonctionne toujours)

### Phase 2 — Tri colonnes + filtres enrichis (L6–L10)

- [x] **L6** — Backend : ajouter `"location"` à `_SORT_COLS` (offers.py:25).
- [x] **L7** — `OffersTable.vue` : passer `company` et `location` à `sortable: true`.
- [x] **L8** — `FiltersPanel.vue` : ajouter les selects Source, État review, Hors-périmètre. Câbler `apply()` pour envoyer `source`, `etat_review`, `hors_perimetre` au store. Câbler `reset()` pour les remettre à undefined.
- [x] **L9** — `FiltersPanel.vue` : filtres réactifs immédiatement (@change), bouton Appliquer retiré, Réinitialiser conservé.
- [x] **L10** — Vérification : build OK, tri colonnes + filtres enrichis câblés. Validé manuellement.

✋ Verify before continuing:
- [x] Clic sur "Entreprise" dans le header → tri alphabétique (asc/desc toggle)
- [x] Clic sur "Lieu" → tri par localisation
- [x] FiltersPanel "Tout" : filtre Source = "Indeed" → uniquement offres Indeed
- [x] Filtre combiné Remote + Source → intersection correcte
- [x] Aucune régression sur les onglets À traiter / Hors-périmètre (presets non affectés)

## Livrables détaillés

1. **L1** — Store élagage presets — done : 3 presets opérateur restants — **XS**
2. **L2** — operateur.vue élagage tabs — done : 3 boutons — **XS**
3. **L3** — OfferDetail verdicts HP — done : boutons HP visibles sur offres HP — **S**
4. **L4** — VerdictBadge rendu HP — done : label + couleur pour les 2 statuts — **XS**
5. **L5** — Vérification Phase 1 — done : onglets + verdicts HP — **XS**
6. **L6** — Backend sort location — done : `location` dans `_SORT_COLS` — **XS**
7. **L7** — OffersTable colonnes triables — done : company + location cliquables — **XS**
8. **L8** — FiltersPanel enrichi — done : source + état review + HP — **S**
9. **L9** — FiltersPanel UX (apply immédiat ou bouton) — done : comportement validé — **XS**
10. **L10** — Vérification Phase 2 — done : tri + filtres combinables — **XS**

## Dépendances critiques

- L1 (store) bloque L2 (les types doivent compiler)
- L6 (backend sort) bloque L7 (le front ne doit pas envoyer un sort ignoré)

## Garde-fous

- Si une offre HP n'affiche pas les boutons verdict HP → vérifier la condition sur `hors_perimetre_reason` dans OfferDetail
- Si le tri par location est erratique → vérifier que les valeurs `location` sont cohérentes en base (NULL, vide, formats mixtes)
