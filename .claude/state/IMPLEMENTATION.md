# IMPLEMENTATION — Alignement endpoint export sur listing (bug copier hors-périmètre)

## Vue d'ensemble

Le bouton "Copier" de l'export ne fonctionne pas sur l'onglet hors-périmètre (et potentiellement sur d'autres vues futures). Cause : `GET /export/offers` est une copie simplifiée de `GET /offers` qui n'a jamais été maintenue en synchronisation — sort restrictif (4 valeurs vs 7), pas de tri composite, filtres manquants. Le front (`ExportPopover.vue:doCopy()`) omet aussi des filtres que `fetchOffers()` envoie. Première chose à attaquer : aligner le backend, puis le front.

Invariants : cf. `rules/architecture.md` §4 (0 LLM). L'export est lecture pure, aucun risque sur le scoring.

## Inventaire des écarts (Phase 0)

### Backend — `api/export.py` vs `api/offers.py`

| Écart | `GET /offers` | `GET /export/offers` |
|---|---|---|
| Sort colonnes | `_SORT_COLS` = 7 valeurs (incl. `hors_perimetre_reason`, `seen_candidat`, `location`) | Pattern regex 4 valeurs → **422 sur `hors_perimetre_reason`** |
| Sort composite | `sort=col1,col2` + `order=dir1,dir2` | Sort unique, pas de split |
| Sort category direction | Respecte `{d}` (ASC/DESC paramétrique) | Hardcodé `ASC` |
| Filtre `hp_cause` | Présent (LIKE sur `perimetre_causes`) | **Absent** |
| Filtre `exclude_category` | Présent | **Absent** |
| Filtre `seen_candidat` | Présent | **Absent** (non critique pour export) |
| Filtre `filtered_out` | Présent (défaut = exclues) | Hardcodé `filtered_out = 0` (OK) |

### Frontend — `ExportPopover.vue:doCopy()` vs `stores/offers.ts:fetchOffers()`

| Écart | `fetchOffers()` | `doCopy()` |
|---|---|---|
| `hp_cause` | Envoyé (L116) | **Absent** |
| `exclude_category` | Envoyé (L114) | **Absent** |
| `seen_candidat` | Envoyé (L121) | **Absent** (non pertinent pour export) |

## Phases

### Phase 1 — Backend : aligner le sort et les filtres de l'export (L1–L3)

- [x] **L1** — Sort : retirer le `pattern=` regex du param `sort`. Adopter le même `_SORT_COLS` que `offers.py` (7 valeurs). Fallback sur `"category"` si la valeur n'est pas dans le set (même logique que `offers.py:253-256`).
- [x] **L2** — Sort composite : supporter `sort=col1,col2` + `order=dir1,dir2` (même split/zip que `offers.py:235-257`). Le sort `category` doit respecter la direction passée (pas hardcodé ASC).
- [x] **L3** — Filtres manquants : ajouter les params `hp_cause` et `exclude_category` à `export_offers()`, même logique de WHERE que dans `list_offers()`.

✋ Verify before continuing:
- [ ] `curl "localhost:8000/export/offers?hors_perimetre=true&sort=hors_perimetre_reason&order=asc"` → 200, pas 422
- [ ] `curl "localhost:8000/export/offers?sort=category&order=desc"` → tri category DESC (pas hardcodé ASC)
- [ ] `curl "localhost:8000/export/offers?sort=seen_candidat,fetched_at&order=asc,desc"` → 200, tri composite
- [ ] `curl "localhost:8000/export/offers?category=parfait"` → même résultat qu'avant (non-régression)
- [ ] `curl "localhost:8000/export/offers?hp_cause=langue&hors_perimetre=true"` → filtre HP par cause

Si tout est OK : "go". Sinon dis ce qui cloche.

### Phase 2 — Frontend : aligner `doCopy()` sur `fetchOffers()` (L4)

- [x] **L4** — `ExportPopover.vue:doCopy()` : ajouter les filtres `hp_cause` et `exclude_category` manquants, en miroir exact de `fetchOffers()`. Ne pas ajouter `seen_candidat` (pas de sens pour un export).

✋ Verify before continuing:
- [ ] Onglet hors-périmètre : clic "Copier" → le contenu est copié dans le presse-papiers (pas d'erreur console)
- [ ] Onglet "À traiter" : clic "Copier" → fonctionne toujours (non-régression)
- [ ] Onglet "Tout" : clic "Copier" → fonctionne toujours (non-régression)
- [ ] Vue candidat "Cibles" : clic "Copier" → fonctionne (sort composite `seen_candidat,fetched_at`)

Si tout est OK : "go". Sinon dis ce qui cloche.

## Livrables détaillés

1. **L1** — Sort : set de colonnes élargi — done : `_SORT_COLS` aligné, pattern regex retiré, fallback category — **XS**
2. **L2** — Sort composite + direction category — done : split/zip comme `offers.py`, direction paramétrique — **S**
3. **L3** — Filtres `hp_cause` + `exclude_category` — done : mêmes clauses WHERE que `list_offers()` — **XS**
4. **L4** — `doCopy()` filtres manquants — done : `hp_cause` + `exclude_category` ajoutés — **XS**

## Dépendances critiques

- L1/L2/L3 (backend) bloquent L4 (front) — le front ne peut pas envoyer des params que le back rejette.

## Garde-fous

- Si le sort composite introduit une injection SQL via les noms de colonnes → vérifier que le fallback whitelist (`_SORT_COLS`) est bien appliqué (même garde que `offers.py`).
