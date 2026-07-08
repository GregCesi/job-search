# IMPLEMENTATION — Vue candidat (4 onglets par intention)

## Vue d'ensemble

Remplacer les 5 vues actuelles (a_traiter / a_relire / favoris / hors_perimetre / tout) par 4 onglets candidat organisés par **intention** : Cibles (parfait), Gaps (reve), Filet (atteignable), Retenues (verdict retenu). Exclusion systématique des offres `category='hors'` et `hors_perimetre_reason IS NOT NULL`. Renommage `favori` → `retenu`. Isolation UI : zéro outillage opérateur sur `/`, outillage opérateur préservé sur `/operateur`.

Première chose à attaquer : déménager l'existant sur `/operateur` (filet de sécurité), puis renommer favori → retenu.

## Schémas cibles

_Base de travail, pas contrat figé — à affiner au livrable correspondant._

### Backend — `VerdictIn` (schemas.py:52-53)

```python
class VerdictIn(BaseModel):
    status: Literal["retenu", "rejeté", "candidaté", "masqué", "hors_perimetre_ok", "hors_perimetre_faux_pos"]
    #                ^^^^^^ était "favori"
```

### Backend — nouveau param `GET /offers`

```
exclude_category: str | None  # ajoute WHERE o.category != ? (nécessaire pour onglet Retenues)
```

### Backend — migration `seen` → `seen_candidat`

```sql
ALTER TABLE offers RENAME COLUMN seen TO seen_candidat;
```

### Frontend — `ActiveView` + presets (stores/offers.ts)

```typescript
// Candidat (page /)
type CandidateView = 'cibles' | 'gaps' | 'filet' | 'retenues'

// Opérateur (page /operateur) — presets existants, inchangés sauf favori→retenu
type OperatorView = 'a_traiter' | 'a_relire' | 'retenues_op' | 'hors_perimetre' | 'tout'

type ActiveView = CandidateView | OperatorView

const VIEW_PRESETS = {
  // Candidat
  cibles:      { category: 'parfait',     hors_perimetre: false, sort: 'seen_candidat,fetched_at', order: 'asc,desc' },
  gaps:        { category: 'reve',        hors_perimetre: false, sort: 'seen_candidat,fetched_at', order: 'asc,desc' },
  filet:       { category: 'atteignable', hors_perimetre: false, sort: 'seen_candidat,fetched_at', order: 'asc,desc' },
  retenues:    { verdict: 'retenu', hors_perimetre: false, exclude_category: 'hors', sort: 'fetched_at', order: 'desc' },
  // Opérateur (existant, référence 'retenu' au lieu de 'favori')
  a_traiter:      { etat_review: 'non_relue', hors_perimetre: false, sort: 'category',   order: 'desc' },
  a_relire:       { hors_perimetre: false,                           sort: 'category',   order: 'desc' },
  retenues_op:    { verdict: 'retenu',                               sort: 'fetched_at', order: 'desc' },
  hors_perimetre: { hors_perimetre: true,                            sort: 'fetched_at', order: 'desc' },
  tout:           {                                                   sort: 'category',   order: 'desc' },
}
```

Note : pour cibles/gaps/filet, `category=X` exclut `hors` par construction. Pour retenues, `exclude_category='hors'` est nécessaire car le filtre est sur verdict, pas category. Tri candidat : `seen_candidat ASC` (non-vus en tête) puis `fetched_at DESC`.

### Frontend — `Filters` (stores/offers.ts:49-60)

Ajout d'un champ optionnel :
```typescript
exclude_category?: string
```

## Phases

### Phase 0 — Route opérateur : déménagement (L0a–L0b)

- [x] **L0a** — Créer `pages/operateur.vue` : héberge l'EXISTANT TEL QUEL (presets a_traiter / a_relire / retenues_op / hors_perimetre / tout, FiltersPanel sur "tout", OfferDetail avec section review + tous verdicts, OffersTable avec dots review). Le code actuel de `index.vue` sert de base.
- [x] **L0b** — Vérifier que `/operateur` reproduit le comportement actuel de `/` à l'identique.

✋ Verify before continuing:
- [ ] `/operateur` affiche les presets actuels + filtres + review, identique à l'ancien `/`
- [ ] Aucune fonctionnalité opérateur n'est devenue inaccessible (juste déménagée)

### Phase 1 — Renommage favori → retenu + migration seen_candidat (L1–L4)

- [x] **L1** — Backend schema : `VerdictIn.status` Literal `"favori"` → `"retenu"` (schemas.py:53). VerdictBadge.vue : clé `favori` → `retenu`, label `★ retenu`.
- [x] **L2** — Migration données : `UPDATE verdicts SET status='retenu' WHERE status='favori'`. Exécuter sur la base de dev.
- [x] **L3** — Frontend renommage : OfferDetail.vue VERDICTS array `favori` → `retenu`. FiltersPanel.vue option Verdict `favori` → `retenu`. Store preset `favoris` → `retenues_op` avec `verdict: 'retenu'`.
- [x] **L3a** — Migration seen : `ALTER TABLE offers RENAME COLUMN seen TO seen_candidat`. Mettre à jour les références SQL dans offers.py (SELECT, UPDATE, WHERE). Mettre à jour schemas.py (`OfferRow.seen` → `seen_candidat`), stores/offers.ts (`OfferRow.seen` → `seen_candidat`), OffersTable.vue (`offer.seen` → `offer.seen_candidat`).
- [x] **L3b** — Side-effect GET /offers/{id} : `UPDATE offers SET seen_candidat = 1` (mécanisme inchangé, colonne renommée).
- [x] **L3c** — Tri candidat : ajouter support tri composite `seen_candidat ASC, fetched_at DESC` côté backend (offers.py sort logic). Les non-vus remontent en tête de chaque onglet candidat.
- [x] **L4** — Vérification : 0 row `favori` en base, PUT `retenu` → 204, PUT `favori` → 422. `seen_candidat` fonctionne.

✋ Verify before continuing:
- [ ] `SELECT status, COUNT(*) FROM verdicts GROUP BY status` ne contient plus `favori`
- [ ] `curl -X PUT localhost:8000/offers/1/verdict -H 'Content-Type: application/json' -d '{"status":"retenu"}'` → 204
- [ ] `curl -X PUT ... -d '{"status":"favori"}'` → 422 (rejeté par le Literal)
- [ ] Une offre jamais ouverte en candidat remonte en tête de son onglet
- [ ] `/operateur` fonctionne toujours (presets mis à jour avec `retenu`)

### Phase 2 — Onglets candidat : plomberie store + API (L5–L8)

- [x] **L5** — Backend : param `exclude_category: str | None = Query(None)` sur `GET /offers` (offers.py). Ajoute `o.category != ?` au WHERE quand renseigné.
- [x] **L6** — Store : ajouter les presets candidat (cibles/gaps/filet/retenues) au `VIEW_PRESETS` existant. `ActiveView` = union CandidateView | OperatorView. `Filters` + champ `exclude_category`. `fetchOffers` envoie `exclude_category` si présent.
- [x] **L7** — `index.vue` : VIEWS array = Cibles / Gaps / Filet / Retenues. Retirer le bloc `v-if="store.activeView === 'tout'"` + FiltersPanel de cette page (le composant reste pour `/operateur`). Appeler `store.setView('cibles')` au mount.
- [x] **L8** — Vérification manuelle : chaque onglet retourne le bon sous-ensemble.

✋ Verify before continuing:
- [ ] Onglet Cibles → uniquement `category=parfait`, 0 offre hors, 0 offre hors_perimetre
- [ ] Onglet Retenues → uniquement `verdict=retenu`, exclut `category=hors` et `hors_perimetre_reason IS NOT NULL`
- [ ] Aucun appel `categorize()` ou recompute déclenché au changement d'onglet (invariant §4 — cf. `rules/architecture.md` §4)
- [ ] API n'écrit rien côté scoring (category, criteria_json, techs_*, extracted_facts) — lecture pure (cf. `rules/architecture.md` §4, DECISIONS.md 2026-06-02)

### Phase 3 — Isolation UI candidat (L9–L12)

- [x] **L9** — OfferDetail.vue : ajouter prop `mode: 'candidat' | 'operateur'` (défaut `'candidat'`). En mode candidat : masquer la section "Catégorie" / review (lignes 61-105), masquer le badge `etatLabel` de la meta bar (ligne 31), ne garder que le bouton verdict `retenu` dans la section Verdict. En mode opérateur : comportement actuel inchangé. `operateur.vue` passe `mode="operateur"`.
- [x] **L10** — OffersTable.vue : ajouter prop `mode`. En mode candidat : masquer la colonne dots review (lignes 38-42) + `th` vide (ligne 12). Référencer `seen_candidat` au lieu de `seen` pour le style lignes vues/non-vues. En mode opérateur : inchangé.
- [x] **L11** — Nettoyage index.vue : passer `mode="candidat"` aux composants. Vérifier que `submitCategoryReview` n'est pas appelé depuis la route candidat (il reste dans le store pour `/operateur`).
- [x] **L12** — Vérification finale.

✋ Verify before continuing:
- [ ] `/` : section review absente, dots absents, seul verdict = retenu
- [ ] `/operateur` : section review présente, dots présents, tous verdicts affichés
- [ ] API `PUT /offers/{id}/category-review` toujours fonctionnel (chantier opérateur)
- [ ] Offre ouverte → vu (seen_candidat), retenu toggle → fonctionne. Aucune autre écriture côté candidat.
- [ ] ⚠️ DETTE : GET /offers/{id} écrit seen_candidat même appelé depuis /operateur. Documenter dans DECISIONS.md.

## Livrables détaillés

1. **L0a** — Route /operateur avec existant — done : page opérateur fonctionnelle — **M**
2. **L0b** — Vérification /operateur — done : identique à l'ancien / — **XS**
3. **L1** — Renommage schema + badge — done : Literal + VerdictBadge acceptent `retenu` — **XS**
4. **L2** — Migration DB favori→retenu — done : 0 row avec `favori` — **XS**
5. **L3** — Renommage front complet — done : VERDICTS array, FiltersPanel, preset — **S**
6. **L3a** — Migration seen→seen_candidat — done : colonne + refs Python/TS/Vue — **S**
7. **L3b** — Side-effect seen_candidat — done : GET /offers/{id} écrit seen_candidat — **XS**
8. **L3c** — Tri non-vus en tête — done : sort composite backend + presets candidat — **S**
9. **L4** — Vérification renommage + seen — done : aucun orphelin, tri correct — **XS**
10. **L5** — Param exclude_category backend — done : `o.category != ?` filtré — **XS**
11. **L6** — Store : presets candidat + opérateur — done : union ActiveView, 9 presets — **S**
12. **L7** — index.vue : tabs candidat — done : 4 boutons, mount sur cibles — **S**
13. **L8** — Vérification onglets — done : chaque onglet montre le bon sous-ensemble — **XS**
14. **L9** — OfferDetail : prop mode + isolation — done : candidat sans review, opérateur complet — **M**
15. **L10** — OffersTable : prop mode + isolation — done : candidat sans dots, seen_candidat — **S**
16. **L11** — index.vue : câblage mode candidat — done : mode passé, pas d'appel review — **XS**
17. **L12** — Vérification finale — done : isolation complète, deux routes fonctionnelles — **XS**

## Dépendances critiques

- L0a (route opérateur) bloque Phase 2-3 (filet de sécurité avant modification de /)
- L1-L2 (renommage) bloquent L3-L6 (les presets référencent `retenu`)
- L5 (param backend) bloque L6 (preset retenues utilise `exclude_category`)
- L3a (migration seen) bloque L3c (tri sur seen_candidat) et L10 (ref seen_candidat dans OffersTable)
- L9-L10 (mode prop) dépendent de L6-L7 (les onglets doivent être en place pour tester)

## Garde-fous

- Si des offres `favori` apparaissent après migration → le Literal backend rejette `favori` en écriture, impossible après L1.
- Si un onglet affiche des offres `hors` ou `hors_perimetre` → vérifier que le preset envoie bien les deux filtres, vérifier le WHERE SQL.
- Si `/operateur` casse après renommage → les presets opérateur sont mis à jour en L3 (favori→retenu), vérifier en L4.

## Dettes ouvertes (à documenter dans DECISIONS.md)

- `GET /offers/{id}` écrit `seen_candidat` quel que soit l'appelant (candidat ou opérateur). Quand `/operateur` câblera son propre `seen_operateur`, le side-effect devra distinguer la vue d'origine. NE PAS résoudre maintenant — chantier opérateur.

## Hors périmètre (chantier opérateur — ne pas traiter)

- Sort de candidaté / rejeté / masqué / hors_perimetre_ok / hors_perimetre_faux_pos
- seen_operateur (câblé au chantier opérateur)
- Distinction vue d'origine dans side-effect GET /offers/{id}
- masqué (soft delete) : à reconsidérer côté opérateur
- Deep-link offre (pont candidat→opérateur)
- human_reviews orpheline, UNIQUE(offer_id) manquant
