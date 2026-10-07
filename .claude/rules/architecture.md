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

## Exceptions encadrées — fiche entreprise, CV, lettre (TCK-224, TCK-225, TCK-226)

Trois appels LLM existent hors extraction à l'ingestion. Chacun part **uniquement** d'une action explicite sur une offre `retenue` : un POST sur la route de sa pièce (`/offers/{id}/fiche` et son explication de point `.../explain` ; `/offers/{id}/cv` ; la route de la lettre). Jamais d'un changement de `profile.yaml`, jamais d'un rescore.

Chacun tourne dans sa propre table d'interaction, jamais mêlée à `offers` : `fiches_entreprise`, `cvs` (avec `cv_corrections`), et la table de la lettre. Les choix humains qu'elles stockent — tas des points, corrections de compétences, points retenus pour la lettre, texte relu — ne recalculent rien.

**Lancement au geste de retenir (TCK-281).** Retenir une offre est aussi une action explicite : ce geste lance la fiche entreprise et le CV de l'offre, puis sa lettre quand la fiche est terminée, sur des points de la fiche désignés par l'appel de la fiche lui-même. Aucun appel de modèle ne s'ajoute aux trois existants. Les routes de chaque pièce restent la voie de relance à la main.

Ce qui ne change pas : rien ne part d'un changement de `profile.yaml`, d'un rescore, d'un démarrage de l'API ou d'une offre déjà retenue ; les tas des points et la marque « Prête » ne viennent que de Grégoire ; un choix de points fait à la main n'est jamais remplacé par celui du système.

_Écrit le 5 octobre 2026, TCK-281 : une candidature demandait trois lancements à la main, dans l'ordre, pour 30 candidatures visées le 9 octobre._

## Exception encadrée — identification d'une offre ajoutée à la main sans titre (TCK-183)

Une offre ajoutée à la main par son texte, sans titre saisi, passe par un appel d'identification **avant** l'extraction : un prompt système distinct, qui ne rend que le titre, l'entreprise et le lieu lus dans le texte. Il part uniquement de cet ajout — jamais d'une offre de source, jamais d'un changement de `profile.yaml`, jamais d'un rescore.

L'extraction qui suit est l'extraction ordinaire, prompt inchangé : l'invariant 4 vaut pour elle. L'appel d'identification ne rend aucun fait qui entre dans le scoring (ni séniorité, ni techno, ni domaine, ni langue). Il est tracé comme l'extraction.

_Écrit le 29 septembre 2026, TCK-183 : sur deux pages d'offre essayées, aucune n'a été lue ; le collage devient la voie principale._

## Exception encadrée : reprise d'une extraction échouée et seconde passe (TCK-273)

L'invariant 4 dit que le LLM intervient une seule fois par offre. Deux cas y dérogent, à l'ingestion seulement.

**Reprise.** Une extraction échouée (aucune réponse lisible du modèle après ses tentatives) n'a produit aucun fait. L'offre reste à extraire, et un run ultérieur rappelle le modèle pour elle. Aucun fait de repli n'est enregistré ni scoré à sa place. Une extraction réussie n'est jamais refaite par ce chemin.

**Seconde passe.** Le run extrait chaque offre avec un modèle de tri. Il l'extrait une seconde fois avec un modèle de précision dans trois cas seulement : le tri la classe parfait ou rêve, le tri n'a pas réussi à la lire, ou le tri la range « sans techno ». Les faits du modèle de précision remplacent alors ceux du tri, et la catégorie est recalculée en Python sur eux. Les deux modèles reçoivent le même prompt.

Ce qui ne change pas : aucun de ces appels ne part d'un changement de `profile.yaml` ni d'un rescore, les faits extraits restent intrinsèques, et chaque appel est tracé avec son modèle.

_Écrit le 2 octobre 2026, TCK-273 : le run du jour a duré 5h20 pour 52 extractions avec un seul modèle, et 148 extractions échouées ont été rangées « sans techno »._

_Troisième cas ajouté le 3 octobre 2026, TCK-273 : au run du jour, le modèle de tri a rangé 46 offres sur 199 en « sans techno », sur des textes de 849 à 5329 caractères ; le modèle de précision en range 12 sur 806._

**Offre sans texte.** Une offre dont le texte est absent ou trop court pour être lu n'est envoyée à aucun modèle. Elle n'a ni faits, ni catégorie, ni cause hors périmètre : elle reste visible comme « texte manquant » jusqu'à ce qu'une source rapporte son texte.

_Écrit le 3 octobre 2026, TCK-273 : 8 offres Indeed sans description ont été classées sur leur titre seul, dont une en rêve en tête du digest._

## Exception encadrée : rejeu du jeu de référence (TCK-221)

Le rejeu d'un jeu de référence appelle le modèle d'extraction hors ingestion, sur des offres déjà extraites, pour mesurer un modèle ou un prompt contre une extraction attendue écrite à la main. Il part uniquement d'une commande lancée à la main : jamais d'un run, jamais d'un changement de `profile.yaml`, jamais d'un rescore.

Il n'écrit rien dans `offers` ni dans la trace d'extraction du run. Ses résultats vivent dans son rapport et dans MLflow.

_Écrit le 2 octobre 2026, TCK-221._

## Exception encadrée : banc de la lettre (TCK-251)

Le banc de la lettre appelle des modèles hors des routes des pièces, pour comparer des modèles sur la boucle de la lettre (tamis, rédaction, juge recruteur) avant qu'elle soit branchée à l'application. Il part uniquement d'une commande lancée à la main, sur des offres retenues : jamais d'un run, jamais d'un changement de `profile.yaml`, jamais d'un rescore, jamais du geste de retenir, jamais d'une route de l'API.

Il travaille en deux commandes. La préparation du jeu d'évaluation lit `offers` et `verdicts`, lance pour chaque offre la recherche d'entreprise avec la demande de la fiche entreprise, et range les faits trouvés dans un fichier figé sous `data/lettre/banc/`. Le banc lit ce fichier et les fichiers de `data/lettre/` : il n'ouvre pas la base. Aucune des deux commandes n'écrit dans une table, et la table `fiches_entreprise` n'est ni lue ni écrite. Les résultats vivent dans le rapport du banc et dans MLflow. Le nombre d'appels de modèle par offre est borné par le plafond de tours de la boucle, et chaque appel est tracé avec son modèle.

Le lancement au geste de retenir n'est pas touché : la phrase « Aucun appel de modèle ne s'ajoute aux trois existants » reste vraie pour lui.

_Jeu d'évaluation figé ajouté le 7 octobre 2026 : le premier banc lisait les fiches de l'application, et tester la nouvelle recherche d'entreprise a obligé à retirer deux fiches de la base._

_Écrit le 7 octobre 2026, TCK-251 : la lettre écrite en un seul appel a été jugée non envoyable le 5 octobre 2026, et deux lettres écrites à la main sur une deuxième offre ont été rejetées faute d'un répertoire des textes de Grégoire._
