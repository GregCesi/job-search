# Architecture — invariants non négociables

Trois décisions structurent tout le projet. Ne jamais les contourner pour aller plus vite.

## 1. Sources pluggables

Toute source d'offres implémente l'interface `Source` (`fetch() -> list[JobOffer]`). Le pipeline aval (dédup, embedding, scoring, persistance, digest) ne connaît QUE le schéma neutre `JobOffer`, jamais le schéma natif d'une source.

- France Travail = premier (et seul en V1) adapter : `FranceTravailSource`.
- Le mapping payload natif → `JobOffer` vit DANS l'adapter, nulle part ailleurs.
- **Interdit** : faire transiter un champ brut spécifique à France Travail dans le pipeline aval. Si un champ manque dans `JobOffer`, on étend `JobOffer`, on ne fuit pas le schéma source.

## 2. Profil cible mutable

Le profil de recherche vit dans `profile.yaml` (déclaratif), jamais codé en dur dans le code Python. Le loader le charge, le valide, et calcule son hash.

- Ré-embed du profil **uniquement si le hash change**. La base d'offres ChromaDB n'est jamais rebuildée pour un simple changement de profil.
- Plusieurs profils possibles = plusieurs fichiers. Le code ne présuppose jamais un profil unique.
- `gregoire.py` (recapitalisé de rag-job-matching) devient loader/validateur du fichier, PAS le dépôt du profil.

## 3. Scoring explicable par construction

Le LLM note des **critères atomiques** (0-10 chacun) avec une mini-justification par critère. Le **score global est calculé côté code** par agrégation pondérée — jamais produit en bloc par le LLM.

- Raison : sur un modèle local 7B/8B, un score produit en bloc est sujet à rationalisation post-hoc (la justification ne reflète pas ce qui a produit le chiffre). La structure garantit la fidélité.
- Le détail des critères + justifications est persisté (`criteria_json`) = observabilité de décision. C'est l'objet d'apprentissage du projet.
- **Interdit** : demander au LLM "donne un score sur 100 et justifie". Toujours passer par la grille de critères.
- Parsing défensif obligatoire : retry + fallback (`score=0`, flag `parse_failed`) si le JSON casse. Ne jamais crasher le run sur une offre mal parsée.

## 4. Frontière extraction / matching — 0 LLM au recalcul

Le LLM intervient UNE SEULE FOIS par offre, à l'ingestion, pour extraire des **faits intrinsèques** (indépendants du profil) : séniorité exigée, technos exigées, domaine métier. Tout le scoring qui dépend du profil ou des critères de recherche (désirabilité, atteignabilité) est un **calcul Python** par-dessus ces faits.

- **Interdit** : tout appel LLM déclenché par un changement de `profile.yaml`. Monter le profil d'un cran sur 4000 offres = 4000 recalculs Python, 0 appel LLM, CPU froid.
- Raison : un recalcul LLM serait inviable en volume (coût machine) et instable (7B/8B sur jugement relatif, cf. §3). L'intelligence va là où elle ne se répète pas : la lecture de l'offre.
- Les faits extraits sont persistés sur `offers` et ne sont JAMAIS recalculés tant que l'offre ne change pas. Seuls les scores dérivés se recalculent.
- Corollaire matching : le match technique est un **recouvrement de listes** (technos exigées ∩ profil), observable par construction. Pas de jugement LLM nuancé dans le match — on n'en rajoute QUE si l'observation prouve que le Python pur se trompe.

## Persistance — séparation offers / verdicts / human_reviews

Trois tables d'interaction, jamais fusionnées :

- `offers` — score LLM + `criteria_json` (décision IA). Source de vérité du scoring.
- `verdicts` — statut humain global (favori/rejeté/candidaté).
- `human_reviews` — notation humaine **par-critère** contre l'IA, pour la calibration. Clé `offer_id`. Stocke `ratings_json` (notes/justifs humaines par critère, optionnelles) + `ai_snapshot_json` (copie figée du `criteria_json` à l'instant de la review) + audit global libre.

**Interdit** : écrire dans `offers` (score, criteria_json) depuis un avis humain, ou recalculer le scoring depuis `verdicts` / `human_reviews`. Ce sont des données d'interaction (même statut que `seen`), pas des intrants de recalcul. Leur écart avec le score IA est le signal d'apprentissage — le fusionner le détruit.

Le snapshot dans `human_reviews` rend chaque review auto-portante : la distance de désaccord se calcule contre l'IA _telle qu'elle était_ au moment de l'avis, et survit aux évolutions du scoring (refonte profil, nouveaux critères). Une review n'est jamais invalidée par un changement de grille ultérieur.
