---
paths: ["web/**"]
---

# Frontend — conventions projet

## VIEW_PRESETS = source de vérité des vues

`stores/offers.ts:VIEW_PRESETS` définit les 7 vues (candidat : a_postuler/suivi/ecartees ; opérateur : a_traiter/hors_perimetre/texte_manquant/tout) avec leurs filtres et tri. Toute nouvelle vue = nouvelle entrée dans PRESETS. Jamais de logique de filtrage dans les composants — les composants lisent `filters` depuis le store.

Exception : la vue À postuler (liste principale et file « À étudier ») ne lit pas `filters`. Elle lit ses choix (file, famille, filtre, tri) dans son propre store, `stores/aPostuler.ts`, servi par `GET /a-postuler` ; rang, ordre et filtrage y sont décidés par l'API, et son entrée dans VIEW_PRESETS ne porte que le tri (EXE-211, TCK-391).

## Champs dérivés : ne jamais persister

`categorie_finale` et `etat_review` sont dérivés à la volée côté API (`_derive_review_fields` dans `api/offers.py`). **Interdit** de les persister en DB ou de les calculer côté front. Raison : le delta `categorie_suggeree ↔ categorie_corrigee` EST la vérité terrain — persister le dérivé détruit la propriété qui fait que la review humaine survit aux changements de scoring.

## Stores API-driven, zéro logique métier côté front

Toute logique métier (scoring, matching techs, catégorisation, dérivation de champs) vit dans le back (orchestrator ou API). Les stores Pinia font du fetch + state management, jamais de calcul métier. Le matching techs front a été supprimé volontairement (cf. `DECISIONS.md` 2026-06-25).
