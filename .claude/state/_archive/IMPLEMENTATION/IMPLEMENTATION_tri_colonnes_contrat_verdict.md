# IMPLEMENTATION — Tri colonnes Contrat et Verdict

## Vue d'ensemble

Les colonnes "Contrat" (`contract_type`) et "Verdict" dans la table des offres ne sont pas triables : marquées `sortable: false` côté frontend, absentes du whitelist backend. Fix : ajouter un tri sémantique (CASE SQL) pour chaque colonne, même pattern que `category` et `location`.

## Phase 1 — Ajout du tri sémantique backend + activation frontend

### Livrables

- [x] **1.1** `api/offers.py` — Ajouter un `elif s == "contract_type"` dans le bloc de tri composite (L269-289) avec CASE sémantique :
  ```
  CDI/Permanent/Full-time → 1 (stable)
  Freelance/LIB → 2
  CDD → 3
  MIS → 4
  Part-time → 5
  ELSE → 6
  NULL → NULLS LAST
  ```
  Done : `GET /offers?sort=contract_type&order=asc` trie CDI en tête, types précaires en fin.

- [x] **1.2** `api/offers.py` — Ajouter un `elif s == "verdict"` dans le même bloc avec CASE sémantique sur `v.status` (pas `o.verdict` — c'est un alias du JOIN) :
  ```
  retenu → 1
  hors_perimetre_faux_pos → 2
  hors_perimetre_ok → 3
  rejeté → 4
  NULL → 5
  ```
  Done : `GET /offers?sort=verdict&order=asc` trie retenu en tête, rejeté en fin, sans verdict après.

- [x] **1.3** `api/export.py` — Même ajout des deux CASE dans le bloc de tri (L100-123). Référencer la même logique.
  Done : l'export respecte les mêmes tris que l'API principale.

- [x] **1.4** `web/app/components/OffersTable.vue` — Passer `sortable: true` sur `contract_type` (L124) et `verdict` (L128).
  Done : les en-têtes Contrat et Verdict sont cliquables et affichent la flèche de tri.

- [x] **1.5** Test manuel : lancer API + front, cliquer sur Contrat et Verdict, vérifier le tri dans les deux sens.

### ✋ Verify before continuing:
- [x] `GET /offers?sort=contract_type&order=asc` → CDI/Permanent/Full-time en tête
- [x] `GET /offers?sort=contract_type&order=desc` → ordre inverse, CDI en fin
- [x] `GET /offers?sort=verdict&order=asc` → retenu en tête, NULL en fin
- [x] `GET /offers?sort=verdict&order=desc` → ordre inverse
- [x] Clic sur en-tête "Contrat" dans le front → tri toggle + flèche affichée
- [x] Clic sur en-tête "Verdict" dans le front → tri toggle + flèche affichée
- [x] Les autres tris existants (category, location, title, company, fetched_at) ne sont pas impactés

Si tout est OK : "go". Sinon dis ce qui cloche.
