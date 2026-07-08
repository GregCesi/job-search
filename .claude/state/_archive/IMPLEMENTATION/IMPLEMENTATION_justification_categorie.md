# IMPLEMENTATION — Ligne de justification catégorie (vue opérateur)

## Vue d'ensemble

Exposer une ligne unique expliquant pourquoi une offre est dans sa catégorie, visible en vue opérateur. Format figé : `{catégorie} — {levier} bloque : {preuve}`. Génération 100 % Python, 0 LLM, dérivée à la volée (jamais persistée).

Première chose à attaquer : câbler `_derive_score_breakdown()` dans l'API, calqué sur `_derive_review_fields()`.

## Décision de bifurcation (Phase 0)

Les fonctions `compute_desirability()` et `compute_attainability()` retournent des objets riches (`Desirability.detail`, `Attainability.blocked_by/attain_tech/attain_role/techs_missing`), mais ces sous-facteurs ne sont PAS persistés en SQLite (droppés explicitement dans `db.py:108-114`).

**Approche retenue** : appeler les fonctions de scoring (Python pur, 0 LLM) à la volée dans `GET /offers/{id}`, exactement comme `_derive_review_fields()`. Le profil + alias table sont chargés une fois et cachés au niveau module. Source unique préservée, zéro migration, zéro réimplémentation.

Invariants respectés (cf. `rules/architecture.md`) :
- §3 : scoring explicable — la ligne consomme les sous-facteurs, ne les recalcule pas
- §4 : 0 LLM — `compute_desirability()` et `compute_attainability()` sont des fonctions pures Python
- Séparation offers/verdicts/human_reviews intouchée
- `ai_snapshot_json` non impacté

## Phases

### Phase 1 — Helper API + champ schema (L1–L3)

- [x] **L1** — `api/offers.py` : ajouter `_load_scoring_context()` (profile + alias table, cachés module-level) et `_derive_score_breakdown(row) -> str | None`. Logique :
  1. Parser `extracted_facts_json` → `ExtractedFacts`
  2. Appeler `compute_desirability(facts, criteria, profile, table)` et `compute_attainability(facts, profile, table)`
  3. Mapper `category` + sous-facteurs vers la ligne formatée :
     - `parfait` → `"Parfait — rien ne bloque."`
     - `reve` → blocker(s) atteignabilité : rôle / techs / les deux
     - `atteignable` → blocker désirabilité : domaine
     - `hors` → combiner blocker désirabilité + blocker atteignabilité
     - `None` / hors-périmètre / filtered → `None`
  4. Gabarit preuve :
     - rôle : `"poste {role_level}, ta cible est {role_ceiling}"`
     - techs : `"manque {tech1}, {tech2} ({importance})"` (top 3 missing, importance core/required seulement)
     - domaine : `"{domain}, hors cible {cible}"`
- [x] **L2** — `api/schemas.py` : ajouter `score_breakdown: str | None = None` à `OfferDetail`.
- [x] **L3** — `api/offers.py:get_offer()` : passer `score_breakdown=_derive_score_breakdown(row)` dans la construction de `OfferDetail`.

✋ Verify before continuing:
- [x] `GET /offers/{id}` retourne un champ `score_breakdown` non-null pour une offre scorée
- [x] Les 5 cas du gabarit rendent correctement (rôle seul, domaine seul, techs seul, double levier, parfait)
- [x] Aucun appel Ollama/LLM dans le chemin `GET /offers/{id}` (grep `ollama` dans api/)
- [x] `ai_snapshot_json` inchangé après ouverture d'une offre

Si tout est OK : "go". Sinon dis ce qui cloche.

### Phase 2 — Rendu frontend (L4–L5)

- [x] **L4** — `web/app/stores/offers.ts` : ajouter `score_breakdown?: string | null` au type `OfferDetail`.
- [x] **L5** — `web/app/components/OfferDetail.vue` : en mode opérateur, afficher `offer.score_breakdown` sous la section Catégorie (après les boutons catégorie, avant la textarea remarque). Rendu conditionnel : visible seulement si non-null. Style sobre : texte `text-xs text-gray-500 italic mt-2`.

✋ Verify before continuing:
- [x] Vue opérateur → ouvrir une offre scorée → ligne de justification visible sous les boutons catégorie
- [x] Offre parfait → "rien ne bloque"
- [x] Offre hors-périmètre → pas de ligne affichée (score_breakdown = null)
- [x] Aucune migration SQLite introduite (diff db.py = vide)

Si tout est OK : "go". Sinon dis ce qui cloche.

## Livrables détaillés

1. **L1** — Helper `_derive_score_breakdown()` — done : retourne la ligne formatée pour les 5 cas — **S**
2. **L2** — Schema `score_breakdown` sur `OfferDetail` — done : champ optional ajouté — **XS**
3. **L3** — Câblage dans `get_offer()` — done : champ peuplé à la réponse — **XS**
4. **L4** — Type TS `OfferDetail` — done : champ ajouté — **XS**
5. **L5** — Rendu `OfferDetail.vue` — done : ligne visible mode opérateur — **XS**

## Dépendances critiques

- L1 (helper) bloque L3 (câblage endpoint)
- L2 (schema) bloque L3 (le champ doit exister sur OfferDetail)
- L3 (backend) bloque L5 (le front consomme la donnée)

## Garde-fous

- Si le profil YAML n'est pas trouvé au démarrage API → `_derive_score_breakdown()` retourne `None` (dégradation gracieuse, pas de crash)
- Si `extracted_facts_json` est null ou `parse_failed=True` → retourner `None` (pas de breakdown sur donnée dégradée)
