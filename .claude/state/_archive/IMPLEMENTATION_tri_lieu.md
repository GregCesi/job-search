# IMPLEMENTATION — Tri par lieu : grouper les remote

## Vue d'ensemble

Le tri `sort=location` dans l'API génère `ORDER BY o.location {d} NULLS LAST` sans considérer `o.remote`. Les offres remote ont un `location` incohérent (NULL, vide, ou une ville réelle) mais sont affichées "Remote" en UI → elles se dispersent au hasard dans le tri par lieu.

Fix : ajouter un `CASE` SQL spécial pour `location` (même pattern que `category` L272-280) qui sépare remote/non-remote avant de trier par ville.

## Phase 1 — Cas spécial `location` dans le tri SQL

Fichier unique : `api/offers.py`, bloc de tri L269-285.

### Livrables

- [x] **1.1** Ajouter un `elif s == "location"` avant le `elif s in _SORT_COLS` (L281) qui génère un ORDER BY à deux clauses :
  - `CASE WHEN o.remote = 1 THEN 1 ELSE 0 END {d}` — sépare remote/non-remote
  - `o.location {d} NULLS LAST` — trie par ville dans chaque groupe

  SQL généré attendu :
  ```sql
  -- ASC → villes A→Z, remote groupés en fin
  CASE WHEN o.remote = 1 THEN 1 ELSE 0 END ASC, o.location ASC NULLS LAST
  -- DESC → remote groupés en tête, villes Z→A
  CASE WHEN o.remote = 1 THEN 1 ELSE 0 END DESC, o.location DESC NULLS LAST
  ```

  Done : le tri par lieu groupe les remote ensemble (fin en ASC, tête en DESC), les non-remote triés par ville.

- [x] **1.2** Test manuel : lancer l'API, appeler `GET /offers?sort=location&order=asc` puis `order=desc`, vérifier que les remote sont groupés et les villes triées.

### ✋ Verify before continuing:
- [ ] `GET /offers?sort=location&order=asc` → remote en fin de liste, villes A→Z avant
- [ ] `GET /offers?sort=location&order=desc` → remote en tête, villes Z→A après
- [ ] Les autres tris (category, title, company, fetched_at) ne sont pas impactés

Si tout est OK : "go". Sinon dis ce qui cloche.
