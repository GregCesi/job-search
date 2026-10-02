---
paths: ["orchestrator/**"]
---

# Scoring — décisions de calibration

Les invariants structurels (scoring explicable, 0 LLM au recalcul) vivent dans `rules/architecture.md` §3-§4. Les valeurs numériques (gradients, poids, seuils) vivent dans le code — voir `docs/CODEMAP.md` §Scoring pour les pointeurs.

Ce fichier documente les **décisions de calibration** non déductibles du code.

## Seuils de catégorisation : 50/40

`categorize.py` utilise `DESIRABILITY_THRESHOLD=50` et `ATTAINABILITY_THRESHOLD=40`. Le seuil de désirabilité est centré (50 = « moitié du gradient × moitié de l'envie-techno »). Le seuil d'atteignabilité est volontairement plus bas (40) : une offre où tu couvres ~40 % des techs pondérées mérite inspection — le match technique n'est pas éliminatoire, la décision de candidature reste humaine.

## `min()` non-compensatoire

Le score final catégorisation utilise `min(attain_tech, attain_role)`, pas une moyenne. Raison : un rôle manager avec 100 % de couverture techno reste inaccessible si `role_ceiling=ic`. La compensation masquerait un blocage dur. Le `min()` garantit que tout blocage structurel (rôle OU couverture) se voit dans la catégorie.

## `parse_failed`

`parse_failed=True` marque une extraction **dégradée** : le modèle a répondu, mais un champ sortait du vocabulaire et a pris sa valeur par défaut. L'offre est scorée. Le flag est un signal de debug : sa place est dans le viewer de traces, pas comme verdict.

Une extraction **échouée** (aucune réponse lisible) ne produit aucun fait et n'est jamais scorée : l'offre reste à refaire (cf. `architecture.md`, exception TCK-273).

**Interdit** : scorer des valeurs de repli comme si c'étaient des faits, ou ranger une extraction échouée sous `no_tech`.

## Règle de modification

Tout changement de gradient, poids d'importance, ou seuil de catégorisation → rescore complet (`python -m orchestrator.job_search.rescore`) + entrée datée dans `state/DECISIONS.md` avec la raison du changement et la valeur précédente.
