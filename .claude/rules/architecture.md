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

## Persistance — séparation offers / verdicts

`offers` stocke le score LLM. `verdicts` stocke le statut humain (favori/rejeté/candidaté), séparément. Ne JAMAIS fusionner les deux : leur écart est le signal d'apprentissage de la V2 (boucle de feedback). Mauvais schéma ici = re-migration plus tard.
