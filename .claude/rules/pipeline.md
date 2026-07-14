# Pipeline — contrat par étage

Contrat descriptif-normatif du pipeline d'ingestion. Chaque règle est vraie du code actuel — les souhaits non implémentés vont dans `DECISIONS.md`.

Lecture préalable recommandée : `architecture.md` (invariants fondamentaux), `scoring.md` (seuils de calibration), `sources.md` (checklist adapter).

---

## Étage 1 — Fetch (sources pluggables → JobOffer)

**Réf** : `sources/base.py` (interface `Source`, modèle `JobOffer`), `sources/france_travail.py`, `sources/remotive.py`, `sources/indeed_file.py`, `run.py:55-70`

### CONSOMME
- `profile.zones` + `profile.search_criteria.locations` → résolution des zones actives et répartition `per_zone`
- Variables d'environnement : `FRANCE_TRAVAIL_CLIENT_ID`, `FRANCE_TRAVAIL_CLIENT_SECRET` (FT), `OLLAMA_MODEL`, `OLLAMA_HOST`
- `data/indeed_inbox/*.jsonl` (IndeedFileSource — fichiers déposés par `/ingest-indeed`)
- API Remotive publique (RemotiveSource — `https://remotive.com/api/remote-jobs`)

### PRODUIT
- `list[JobOffer]` — schéma neutre, jamais le schéma natif d'une source
- Chaque adapter remplit `description` (Markdown propre via `_clean.py`) ET `description_raw` (HTML/texte brut source, immuable)

### INVARIANTS
- Tout adapter implémente `Source.fetch() -> list[JobOffer]` — le pipeline aval ne voit QUE `JobOffer`
- Le mapping payload natif → `JobOffer` vit DANS l'adapter, nulle part ailleurs
- `fingerprint` = `sha256(normalize(title)|normalize(company)|normalize(location))[:16]` — crochet cross-source, calculé par `sources/fingerprint.py`
- `source_id` = identifiant stable côté source (id FT, id Remotive, indeed_id)
- Zones actives résolues depuis le profil YAML — pas de dict interne en dur

### INTERDITS
- Faire transiter un champ brut spécifique à une source dans le pipeline aval (étendre `JobOffer` si un champ manque)
- Écraser `description_raw` ou le dériver de `description` — c'est la source de vérité immuable
- Dupliquer la logique de résolution de zones hors du profil YAML

---

## Étage 2 — Dédup

**Réf** : `storage/dedup.py`, `sources/fingerprint.py`

### CONSOMME
- `list[JobOffer]` (sortie étage 1)
- Connexion SQLite (`offers` existantes)

### PRODUIT
- `list[JobOffer]` filtrée (offres nouvelles uniquement)
- Compteur `déjà vues` (log)

### INVARIANTS
- Double clé de dédup : `(source, source_id)` en base + `fingerprint` cross-source
- Guard intra-batch : une offre apparue 2× dans le même fetch n'est comptée qu'une fois
- Aucune suppression — les offres déjà vues restent en base, seules les nouvelles passent à l'étage suivant

### INTERDITS
- Supprimer ou écraser une offre existante lors de la dédup
- Ignorer le fingerprint (raterait les doublons cross-source)

---

## Étage 3 — Hard filters (localisation + contrat)

**Réf** : `scoring/filters.py`, profil YAML (`search_criteria.locations`, `search_criteria.contract_types`, `zones`)

### CONSOMME
- `JobOffer` (une par une)
- `profile.search_criteria` : `locations` (noms de zones + `"remote"`), `contract_types` (whitelist `["cdi", "freelance"]`…)
- `profile.zones` : `Zone(insee, dept, keywords)` par nom de zone

### PRODUIT
- `(filtered_out: bool, filter_reason: str | None)`
- Si filtrée → `save_offer(conn, offer, filtered_out=True, filter_reason=...)` — persistée, jamais supprimée
- Si non filtrée → passe à l'étage 4

### INVARIANTS
- Règle contrat : `alternance=True` → out ; codes stage (`STA/STG/APP/PRO`) → out ; nature_contract contenant stage/apprentissage/alternance → out ; si `contract_types` renseigné, seuls les types mappés passent
- Règle localisation : `remote=True` ET `"remote" in locations` → OK ; sinon match zone via `dept` (préfixe) ou `keywords` (substring) ; ni l'un ni l'autre → `location:hors_zone`
- Toute variable de filtrage (zones, contrats) vit dans le profil YAML — le code la consomme, jamais de dict interne

### INTERDITS
- Filtrer sur un critère non déclaré dans le profil (pas de filtre en dur dans le code)
- Supprimer une offre filtrée de la base — elle est marquée `filtered_out`, pas effacée

---

## Étage 4 — Extraction LLM (faits intrinsèques)

**Réf** : `scoring/extractor.py`, `scoring/tracing.py`, `sources/base.py` (`ExtractedFacts`)

### CONSOMME
- `JobOffer` (title, description[:8000], experience_required, rome_label, alternance)
- Modèle Ollama (`$OLLAMA_MODEL`, température 0.1)
- 3 few-shot examples intégrés au prompt

### PRODUIT
- `ExtractedFacts` : `seniority_required`, `techs_required` (list[TechRequirement] avec importance core/required/nice_to_have), `domain` (8 valeurs fermées), `role_level` (ic/lead/manager), `langues_requises`, `parse_failed`
- Trace JSONL en append dans `data/traces/extract_facts.jsonl` (`LLMTrace` : prompt complet, réponse brute, facts parsés, timestamp)

### INVARIANTS
- Un seul appel LLM par offre, à l'ingestion — résultat persisté sur `offers.extracted_facts_json`, jamais recalculé sauf `--re-extract` explicite
- Faits intrinsèques = indépendants du profil (cf. `architecture.md` §4)
- Parsing défensif : 2 retries (3 tentatives au total), fallback `ExtractedFacts(parse_failed=True, techs_required=[], domain="other")` — ne crashe jamais le run
- La trace est sacrée : le vocabulaire brut du LLM est conservé tel quel dans le JSONL — la canonicalisation (`alias.yaml`) n'intervient qu'au scoring (étage 5)
- Coercion v1 : si `techs_required` arrive en `list[str]` (ancien format), le model_validator coerce en `list[TechRequirement]` avec importance `"required"`

### INTERDITS
- Appeler le LLM pour un recalcul déclenché par un changement de profil — c'est du Python pur (étage 5)
- Modifier la trace JSONL après écriture — c'est un log d'audit append-only
- Laisser une exception non catchée remonter au pipeline — fallback obligatoire

---

## Étage 5 — Scoring + gates + catégorisation (Python pur)

**Réf** : `scoring/desirability.py`, `scoring/attainability.py`, `scoring/hors_perimetre.py`, `scoring/categorize.py`, `scoring/aliases.py`, `profiles/alias.yaml`

### CONSOMME
- `ExtractedFacts` (sortie étage 4)
- `profile` : `search_criteria.domains`, `skills` (level + desire), `role_ceiling`, `seniority_ceiling`
- `alias_table` : chargée depuis `profiles/alias.yaml` — canonicalisation variante→forme canonique, exclusions

### PRODUIT
- `Desirability(score, detail)` : `domain_gradient × desire_factor × 100`
- `Attainability(score, attain_tech, attain_role, seniority_malus, techs_matched, techs_missing, blocked_by)` : `max(0, min(attain_tech, attain_role) − seniority_malus)`
- `list[HorsPerimetreCause]` : causes `no_tech`, `mgmt_role`, `langue`, `contrat` — liste vide = dans le périmètre
- `Category` : `parfait` / `reve` / `atteignable` / `hors` (2 seuils : d>50, a>40)

### INVARIANTS
- Gate hors-périmètre appliquée APRÈS d/a — les scores sont calculés et conservés intacts même si l'offre est gatée (observabilité)
- `perimetre_causes` est une liste de causes (pas un booléen) — chaque cause est traçable
- Canonicalisation (`alias.yaml`) appliquée au scoring seulement, jamais à l'ingestion ni à la trace LLM
- Techs exclues (`alias.yaml#exclude`) retirées du calcul (ni matchées ni manquantes)
- Techs inconnues (pas dans alias ni profil) : auto-canonicalisées, surfacées dans `data/unmatched_techs.txt` au rescore
- min() non-compensatoire : un bon axe (tech ou rôle) ne rachète jamais un axe disqualifiant
- Seuils de catégorisation (`DESIRABILITY_THRESHOLD=50`, `ATTAINABILITY_THRESHOLD=40`) et poids d'importance (`core=3.0`, `required=2.0`, `nice_to_have=0.5`) sont des constantes calibrables — tout changement exige un rescore + entrée `DECISIONS.md` (cf. `scoring.md`)

### INTERDITS
- Appeler le LLM à cet étage — tout est du Python pur sur `ExtractedFacts`
- Moyenner d et a au lieu de min() — la non-compensation est structurante
- Persister d/a comme colonnes en base — ce sont des détails de calcul internes, recalculables
- Appliquer la canonicalisation aux données d'ingestion ou à la trace

---

## Étage 6 — Persistance

**Réf** : `storage/offers.py` (`save_offer`), `storage/db.py` (`init_db`, schéma `offers`)

### CONSOMME
- `JobOffer` (tous champs)
- Résultats étages 3-5 : `filtered_out` + `filter_reason`, `extracted_facts` (JSON), `category`, `techs_matched` / `techs_missing` (JSON), `perimetre_causes` (JSON)

### PRODUIT
- UPSERT dans `offers` sur `ON CONFLICT(source, source_id)` — une ligne par offre, mise à jour si rescorée
- Colonnes clés : `extracted_facts_json`, `category`, `techs_matched_json`, `techs_missing_json`, `hors_perimetre_reason` (causes jointes), `filtered_out`, `filter_reason`

### INVARIANTS
- `offers` = seule table de vérité du scoring — jamais recalcul depuis `verdicts` ou `human_reviews`
- `verdicts` (statut humain) et `human_reviews` (notation par-critère) = données d'interaction, même statut que `seen` — leur écart avec le score IA est le signal d'apprentissage, le fusionner le détruirait (cf. `architecture.md`)
- `extracted_facts_json` persisté une fois, relu sans appel LLM au rescore (sauf `--re-extract`)
- Offres filtrées marquées `filtered_out=True` — jamais supprimées

### INTERDITS
- Écrire dans `offers` (extracted_facts_json, category) depuis un avis humain
- Supprimer une offre de la base (toute offre ingérée reste, y compris filtrée et hors-périmètre)
- Recalculer le scoring depuis `verdicts` / `human_reviews`

---

## Invariants transversaux

Ces invariants traversent tous les étages. Ils ont été payés pendant les vagues de remédiation et ne sont pas négociables.

1. **Profil YAML = source unique de pilotage.** Toute variable de pilotage (zones, contrats acceptés, seuils, distances, skills, desires) vit dans le profil YAML. Le code la consomme, ne la duplique jamais en dicts internes. Changer un paramètre = éditer le YAML + relancer le scoring Python, 0 code touché.

2. **Zéro LLM au rescore.** Le LLM extrait une fois à l'ingestion (étage 4). Tout recalcul aval (`rescore.py`, changement de profil, ajout de zone) est du Python pur sur `extracted_facts_json`. Un rescore de 4000 offres = 4000 calculs Python, 0 appel LLM, CPU froid.

3. **Trace brute sacrée.** La canonicalisation (`alias.yaml`, source unique `profiles/`) est appliquée au scoring (étage 5) seulement, jamais à l'ingestion (étage 4) ni à la trace JSONL. Le vocabulaire brut du LLM est la source de vérité pour l'audit et la calibration.

4. **Zéro code mort résiduel.** Tout changement d'architecture supprime ce qu'il remplace — git est la mémoire. On ne ressuscite un pattern que sur cas réel confirmé, jamais par précaution.

5. **Gates post-scoring observables.** `perimetre_causes` est une liste de causes (pas un flag booléen). Les scores d/a sont calculés et persistés AVANT le gate — une offre gatée a quand même ses scores, pour que l'écart soit observable. Les éliminations sont traçables cause par cause.
