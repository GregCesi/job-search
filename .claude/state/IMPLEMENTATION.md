# IMPLEMENTATION — Belge dans le périmètre (gate langue · ad_language · EURES)

## Vue d'ensemble

Trois changements séquencés : (1) le gate hors-périmètre cesse de bloquer sur la langue de
l'offre, (2) un champ `ad_language` détecte et stocke la langue de rédaction — branché dans
le pipeline commun pour toutes les sources, pas uniquement EURES — et la vue candidat exclut
les offres rédigées en néerlandais, (3) une source EURES alimente la base en offres belges.
L'ordre est contraint : 1 et 2 doivent être en place avant que les offres EURES soient
visibles correctement. Première chose à attaquer : supprimer la cause `langue` du gate et
rescore les 29 offres libérées.

Refs architecture : `rules/architecture.md` §1 (sources pluggables), §4 (0 LLM au recalcul).
Règles pipeline : `rules/pipeline.md` §1 (adapter), §5 (gates observables).
Règles sources : `rules/sources.md` (contrat adapter).

---

## Réponses Phase 0

*(Faits issus du code et de la base. Guident les choix de plan.)*

**Motif du retrait COMPLET de la cause `langue`** — ce n'est pas les 29 offres libérées qui
motivent le retrait : c'est le fait que le test est faux. Le gate teste la présence d'un nom
de langue dans le texte, pas une exigence. « Notre client est allemand » suffit à couper.
Le retrait est prospectif : il protège les offres belges francophones que Phase 3 fera entrer,
qui mentionneront le néerlandais à un degré passif. Parmi les 29 offres actuellement gatées
par `langue`, aucune ne mentionne dutch/néerlandais — elles portent russe (12), allemand (8),
espagnol (5), italien (3), arabe (2), polonais (2), portugais (1). Zéro offre belge en base
avant Phase 3.

**description vs description_raw** — `description` est non NULL sur les 1934 offres.
`description_raw` est NULL pour 317 (16 % : 219 FT + 50 Indeed + 48 Remotive). Utiliser
`description` uniquement pour la détection.

**Backfill patron** — `backfill_description_raw.py` à la racine : script autonome, idempotent
sur `WHERE col IS NULL`, `--dry-run`, 0 LLM.

**Filtre candidat liste NOIRE** — le filtre exclut `nl` uniquement. `other`, `NULL` et toute
autre valeur restent visibles. `ad_language IN ('fr','en')` remplacerait un couperet langue
par un couperet détecteur probabiliste — le même défaut déplacé. Décision actée le 9 sept.

**Brancher `ad_language` dans le pipeline commun** — la détection appartient à `run.py`
(ingestion) et à `backfill_ad_language.py` (existant en base), pas à un adapter. Sinon les
nouvelles offres FT/Indeed/Remotive arriveraient avec NULL, et le backfill deviendrait un
one-shot périmé au premier run suivant.

**EuresSource config** — via `__init__` comme `FranceTravailSource`. Câblée dans `run.py`
si `"belgique_area"` est dans `active_zones` (déjà déclaré dans le profil). `belgique_area`
a `dept: []` et `keywords` avec "bruxelles", "brussels", etc. — la règle localisation de
`filters.py` (match par keyword) fonctionnera correctement pour les villes couvertes.

**Fingerprint cross-source** — tient en l'état. FT = emplois français ("67 - Strasbourg"),
EURES = emplois belges ("Bruxelles"). Pas de chevauchement géographique → pas de faux doublons.

**Durée LLM** — non mesurable depuis le code (pas de champ `duration_ms` dans les traces).
*Estimation non mesurée* : ~200 offres × 15-25 s/offre (modèle 8B local, basé sur connaissance
générale) = 50-80 min. Risque de run long : réel, non bloquant pour ce chantier.

**perimetre_causes="langue" existant après retrait de l'enum** — le chemin lecture de l'API
(`api/offers.py`, `api/export.py`) lit `perimetre_causes` via `json.loads()` et retourne des
strings brutes. `HorsPerimetreCause` n'est jamais instancié sur le chemin lecture. Les 29
offres continueront à renvoyer `perimetre_causes: ["langue"]` pendant la fenêtre L1a→L1b (avant
rescore). Aucun crash. Le rescore (L1b) écrase ces lignes. La docstring `hp_cause` dans l'API
est mise à jour en L1a.

**`langdetect`** — absente de `requirements.txt`. Nouvelle dépendance à ajouter explicitement
en L3.

**`langues_requises`** — stocké dans `extracted_facts_json` et dans `ExtractedFacts` (Python),
mais absent de `ExtractedFactsSchema` (`api/schemas.py:37-42`), de `_parse_facts()` dans
`api/offers.py`, de l'interface TS `ExtractedFacts` dans `stores/offers.ts`, et de
`OfferDetail.vue`. Le signal "langue exigée" est extrait et ignoré. À corriger en L6.

---

## Schémas cibles

**`offers.ad_language TEXT`** — ajoutée via `migrate_offers_schema`. Valeurs :
`"fr" | "en" | "nl" | "other"` | NULL (NULL = offre antérieure non encore backfillée).

**`HorsPerimetreCause`** — enum réduit à 3 valeurs : `no_tech`, `mgmt_role`, `contrat`.
Valeur `langue` supprimée. Aucun changement aux valeurs restantes.

**`ExtractedFactsSchema`** — ajout du champ `langues_requises: list[str] = []`.
Aucun changement au prompt LLM ni au schéma de sortie de l'extractor.

Aucun changement à `save_offer()` sauf ajout du paramètre `ad_language: str | None = None`.

---

## Phases

---

### Phase 1 — Retrait de la cause `langue` + rescore des 29 libérées

**Objectif** : aucune offre n'est plus écartée pour raison de langue ; les 29 offres libérées
passent le gate et sont rescorées sans appel LLM.

**Fichiers touchés** : `scoring/hors_perimetre.py`, `tests/test_hors_perimetre.py`,
`api/offers.py`, `api/export.py`, puis rescore CLI.

- [x] **L1a** — Quatre fichiers en une passe :
      — `scoring/hors_perimetre.py` : supprimer `LANGUES_TIERCES`, `_LANGUE_RE`, le bloc
        "Règle langue" (lignes 63-66 actuelles), et la valeur `langue` de l'enum
        `HorsPerimetreCause`. Ne toucher à aucun autre bloc.
      — `tests/test_hors_perimetre.py` : supprimer tous les tests de la section "Règle langue"
        (toute assertion sur `HorsPerimetreCause.langue`).
      — `api/offers.py:198` : retirer `langue` de la docstring du query param `hp_cause`.
      — `api/export.py:41` : idem.
- [x] **L1b** — Rescore : `python -m orchestrator.job_search.rescore --force`. Réutilise les
      `extracted_facts_json` en cache — 0 appel LLM. Relever `wc -l
      data/traces/extract_facts.jsonl` AVANT l'exécution pour comparer APRÈS.

✋ Verify before continuing:
- [x] `git diff orchestrator/job_search/scoring/extractor.py` est vide — prompt système et schéma de sortie identiques (L1a)
- [x] `wc -l data/traces/extract_facts.jsonl` avant = après le rescore — 0 nouvelle trace LLM (L1b)
- [x] `SELECT COUNT(*) FROM offers WHERE perimetre_causes LIKE '%"langue"%'` → 0 après le rescore (L1b)

Si tout est OK : "go". Sinon dis ce qui cloche.

---

### Phase 2 — Champ `ad_language` : colonne + module + pipeline + backfill + filtre candidat

**Objectif** : toute offre en base porte sa langue de rédaction (nouvelles et existantes) ;
la vue candidat exclut uniquement les offres rédigées en néerlandais ; la langue exigée est
visible dans la vue candidat.

**Fichiers touchés** : `storage/db.py`, nouveau `scoring/ad_language.py`, `storage/offers.py`,
`run.py`, nouveau `backfill_ad_language.py` (racine), `api/offers.py`, `api/schemas.py`,
`web/app/stores/offers.ts`, `web/app/components/OfferDetail.vue`.

- [x] **L2** — `storage/db.py:migrate_offers_schema` : ajouter `("ad_language", "TEXT")` dans
      la liste `add_cols`. Idempotent.
- [x] **L3** — Nouveau `orchestrator/job_search/scoring/ad_language.py` :
      `detect_ad_language(text: str) -> str` retournant `"fr" | "en" | "nl" | "other"`.
      0 import réseau, 0 LLM — uniquement `langdetect` (offline, *nouvelle dépendance à ajouter
      dans `requirements.txt`*). Si `len(text) < 100` → retourner `"other"` (texte trop court,
      logguer un warning).
- [x] **L4** — Brancher dans le pipeline commun :
      — `storage/offers.py:save_offer` : ajouter paramètre `ad_language: str | None = None`,
        l'inclure dans l'INSERT et dans la clause `ON CONFLICT DO UPDATE`.
      — `run.py` : avant chaque appel `save_offer()` (les trois chemins : filtered, hors-
        périmètre, scoré), appeler `detect_ad_language(offer.description)` et passer le
        résultat à `save_offer()`.
- [x] **L5** — Nouveau `backfill_ad_language.py` à la racine (à créer), calqué sur
      `backfill_description_raw.py` : idempotent sur `WHERE ad_language IS NULL`, lit
      `description`, appelle `detect_ad_language`, écrit `ad_language`. Argument `--dry-run`.
      Exécuter le dry-run manuellement avant la passe réelle.
- [x] **L6** — Filtre candidat + signal `langues_requises` visible :
      — `api/offers.py:list_offers` : ajouter query param `exclude_ad_language: str | None`.
        Si renseigné, filtrer `(o.ad_language IS NULL OR o.ad_language NOT IN (...))` —
        `NOT IN` s'évaluant à NULL sur une colonne NULL, la clause doit préserver explicitement
        les lignes NULL. Valeurs séparées par virgule.
      — `stores/offers.ts:VIEW_PRESETS` : ajouter `exclude_ad_language: 'nl'` dans les 4
        presets candidat (`cibles`, `gaps`, `filet`, `retenues`). Ajouter `exclude_ad_language`
        dans l'interface `Filters`.
      — `api/schemas.py:ExtractedFactsSchema` : ajouter `langues_requises: list[str] = []`.
      — `api/offers.py:_parse_facts` : extraire `langues_requises` depuis `data` et l'inclure
        dans `ExtractedFactsSchema(...)`.
      — `stores/offers.ts:ExtractedFacts` (interface TS) : ajouter
        `langues_requises: string[]`.
      — `web/app/components/OfferDetail.vue` : afficher `langues_requises` si non vide, dans
        le bloc extraction existant (même section que seniority, domain, etc.).

✋ Verify before continuing:
- [x] `wc -l data/traces/extract_facts.jsonl` identique au relevé de Phase 1 — 0 appel LLM depuis le début du chantier (L3+L5) — **1683 tout au long**
- [x] Imports de `scoring/ad_language.py` ne contiennent aucun de : `ollama`, `requests`, `httpx`, `socket`, `urllib` (L3) — uniquement `langdetect`, `logging`, `warnings`
- [x] `SELECT COUNT(*) FROM offers WHERE ad_language IS NULL` → 0 après le backfill (L5)
- [x] La clause SQL du filtre candidat préserve explicitement les lignes dont `ad_language` est NULL — `(o.ad_language IS NULL OR o.ad_language NOT IN (...))` — observé dans `api/offers.py`
- [x] Ouvrir une offre dont `langues_requises` est non vide : la langue exigée est lisible dans la vue (L6) — confirmé via `OfferDetail.vue` (ajout du span v-if)
- [x] Aucune offre `nl` en base avant Phase 3 — echantillon vide, contrôle reporté en Phase 3

Si tout est OK : "go". Sinon dis ce qui cloche.

---

### Phase 3 — Source EURES + câblage run.py

**Objectif** : les offres belges rentrent dans la base via EURES, avec url + company réels,
sans bloquer sur la localisation, et invisibles dans la vue candidat si rédigées en néerlandais.

**Fichiers touchés** : nouveau `sources/eures.py`, `run.py`, `scoring/filters.py`, `storage/offers.py`.

**Écarts découverts à l'exécution :**
- L'API EURES réelle est `https://europa.eu/eures/api/jv-searchengine` (SPA Angular).
  Le détail n'est pas nécessaire : la réponse `search` contient déjà titre, employeur,
  description complète (via `translations`) et codes NUTS pour la localisation.
  `eures.py` utilise une approche mono-étape (search only).
- Les `positionOfferingCode` EURES (`directhire`, `selfemployed`, `contract`, ...) n'étaient
  pas dans `_CONTRACT_MAP` → toutes les offres filtrées `contract:directhire`. Corrigé :
  `scoring/filters.py:_CONTRACT_MAP` étendu.
- `save_offer` écrase `ad_language` avec NULL lors d'un rescore (pas de `ad_language` passé).
  Corrigé : `ON CONFLICT DO UPDATE ad_language = COALESCE(excluded.ad_language, ad_language)`.
- `Zone` model nécessitait `Field(min_length=1)` → relaxé à `Field(default_factory=list)` pour
  `belgique_area` qui a `insee: []` et `dept: []` (usage keyword-only).

- [x] **L7** — Nouveau `orchestrator/job_search/sources/eures.py` :
      `EuresSource(keywords: list[str], location_codes: list[str] = ["be1", "be3"], max_per_keyword: int = 200)`.
      `location_codes` = codes de zone EURES (`be1` = Bruxelles, `be3` = Wallonie). `be2`
      (Flandre) est exclu : mesuré le 9 sept, 281/294 offres flamandes (96 %) rédigées en
      néerlandais — elles seraient écartées par `ad_language` après avoir consommé un appel LLM
      chacune. be2 s'ajoutera si le besoin apparaît.
      — Pagination : POST search avec 1 keyword (`keywords` = tableau à 1 élément), `resultsPerPage` ≤ 50,
        `pageNumber` incrémenté. `jvs` vide = fin (HTTP 200 = fin normale, pas d'erreur).
      — Détail : GET `.../public/jv/id/{id}` pour chaque offre — employer réel, url candidature,
        ville en clair.
      — Délai entre appels (au minimum `time.sleep(0.5)`).
      — Mapping → `JobOffer` : `source="eures"`, `url` résolu dans cet ordre :
          1. `jvProfiles.<lang>.personContacts[].communications.webProfiles[].uri` si présente ;
          2. sinon `https://europa.eu/eures/portal/jv-se/jv-details/{id}?lang=fr` construit
             depuis l'`id` de l'offre — c'est la page officielle du portail EURES, vérifiée le
             9 sept. **Interdit** : url NULL. **Attention** : le portail est une SPA qui rend
             HTTP 200 avec un shell de 68 924 octets même pour un id inexistant — ne jamais
             vérifier l'existence d'une url par son statut HTTP ; seul `GET /jv/id/{id}` de
             l'API discrimine.
        `company` = employeur réel (champ `employer` de la réponse détail, pas l'agence
        intermédiaire si différent), `location` = ville en clair depuis réponse détail,
        `description` = texte nettoyé via `_clean.html_to_markdown()`, `description_raw` =
        texte brut avant nettoyage.
      — Fingerprint via `fingerprint(title, company, location)`.
      — Une offre échouée = warning + skip, pas de crash.
- [x] **L8** — `run.py` : instancier `EuresSource(keywords=kw)` si `"belgique_area" in active_zones`.
      Ajouter option CLI `--no-eures`.

✋ Verify before continuing:
- [x] `SELECT COUNT(*) FROM offers WHERE source='eures' AND url IS NULL` → 0 (L7 — url toujours non nulle)
- [x] `SELECT location, filter_reason FROM offers WHERE source='eures' AND filter_reason='location:hors_zone'` → 0 lignes pour des lieux belges réels (L7+L8)
- [x] Sur 10 offres EURES tirées au hasard : `company` correct (SNCB, ERIPM, etc.) ; plusieurs viennent d'agences (EDITX BV, ICTJOB BV) ce qui reflète la réalité EURES — l'API ne distingue pas l'agence de l'employeur final.
- [x] `SELECT COUNT(*), ad_language FROM offers WHERE source='eures' GROUP BY ad_language` : nl=301 en base ET 0 visible dans les vues candidat (L6+L7)
- [x] 5 offres nl-classifiées lues : toutes rédigées en néerlandais — aucun faux positif

Si tout est OK : "go". Sinon dis ce qui cloche.

---

## Livrables détaillés

1. **L1a — Retrait cause `langue`** (4 fichiers) — suppressions dans `hors_perimetre.py` +
   tests + docstrings API. Done = `git diff` ne montre que des suppressions dans ces fichiers,
   aucune addition de logique. **XS**
2. **L1b — Rescore libération** — `rescore --force`, 0 LLM. Done = `wc -l` avant = après. **XS**
3. **L2 — Colonne `ad_language`** (`storage/db.py`) — ajout idempotent. Done = `PRAGMA
   table_info(offers)` montre `ad_language`. **XS**
4. **L3 — Module `scoring/ad_language.py`** + `requirements.txt` — `detect_ad_language`,
   offline. Done = imports sans client réseau, dépendance `langdetect` dans requirements.txt. **S**
5. **L4 — Pipeline commun** (`storage/offers.py` + `run.py`) — `save_offer` reçoit
   `ad_language`, `run.py` l'appelle avant chaque `save_offer`. Done = toute nouvelle offre
   ingérée a `ad_language` non NULL. **S**
6. **L5 — Backfill `backfill_ad_language.py`** (à créer) — idempotent, `--dry-run`. Done = 0
   NULL en base après exécution. **S**
7. **L6 — Filtre candidat + signal `langues_requises`** (API + store + composant) — liste noire
   `nl`, `langues_requises` visible. Done = `other`/NULL visibles ; offres nl absentes des vues
   candidat ; langue exigée lisible sur offre concernée. **M**
8. **L7 — `EuresSource`** (`sources/eures.py`) — search + detail, mapping complet, url non
   nulle, company réel, délai, pagination sur jvs vide. Done = 0 url NULL, company réel sur
   échantillon. **M**
9. **L8 — Câblage `run.py`** — condition belgique_area + `--no-eures`. Done = run déclenche
   EuresSource quand belgique_area est dans active_zones. **XS**

## Dépendances critiques

- L1a bloque L1b (rescore impossible sans le retrait)
- L2 bloque L4 et L5 (la colonne doit exister avant d'y écrire)
- L3 bloque L4 et L5 (`detect_ad_language` doit exister)
- L4 bloque L5 (`save_offer` doit accepter `ad_language` avant le backfill)
- L6 (filtre candidat) doit être terminé avant L8 (sinon les offres nl EURES sont visibles)
- L1 + L2 + L3 + L4 + L5 + L6 doivent être terminés avant que L7+L8 soient utiles

## Garde-fous

- Si `detect_ad_language` produit > 5 % d'erreurs visibles sur le dry-run du backfill (offres
  fr classées "other" ou "nl") → stop, inspecter l'échantillon avant de continuer. `langdetect`
  est probabiliste sur les textes courts.
- Si `SELECT COUNT(*) FROM offers WHERE source='eures' AND url IS NULL` > 0 après un run EURES
  → stop immédiat : toute offre EURES doit avoir une url — soit la webProfile URI de la réponse
  détail, soit le fallback portail construit depuis l'id. Une url NULL signale que ni l'un ni
  l'autre n'a été écrit.
- Si le rescore (L1b) aboutit à 0 offre changée de catégorie (toutes tombent en `no_tech`) →
  information attendue (elles avaient peut-être `techs_required=[]` en plus de la cause langue).
  Si certaines obtiennent une catégorie (parfait/reve/etc.) → comportement nominal ; signaler
  le décompte.
- Le filtre candidat est une **liste noire** (`nl` exclu). Si le livrable L6 implémente
  accidentellement une liste blanche (`fr,en` inclus) → stop et remonte : `other` et `NULL`
  disparaîtraient de la vue, recréant un couperet.
