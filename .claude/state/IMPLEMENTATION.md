# IMPLEMENTATION — Belge dans le périmètre (gate langue · ad_language · EURES)

## Vue d'ensemble

Trois changements séquencés : (1) le gate hors-périmètre cesse de bloquer sur la langue de l'offre,
(2) un champ `ad_language` détecte et stocke la langue de rédaction pour filtrer la vue candidat,
(3) une source EURES alimente la base en offres belges. L'ordre est contraint : 1 et 2 doivent
être en place avant que les offres EURES soient visibles correctement. Première chose à attaquer :
supprimer la cause `langue` du gate et rescore les 29 offres libérées.

Refs architecture : `rules/architecture.md` §1 (sources pluggables), §3 (scoring explicable),
§4 (0 LLM au recalcul). Règles pipeline : `rules/pipeline.md` §1 (adapter), §5 (gates
observables). Règles sources : `rules/sources.md` (contrat adapter).

---

## Phase 0 — Réponses aux questions de cadrage

*(Informations factuelles issues du code et de la base. Guident les choix de plan.)*

**Q1 — Retrait complet vs retrait dutch uniquement**
29 offres actuellement gatées par `langue`. Parmi elles : 0 mentionnent dutch/néerlandais.
Répartition : russe 12, allemand 8, espagnol 5, italien 3, arabe 2, polonais 2, portugais 1.
→ Retirer seulement dutch|néerlandais = 0 offre récupérée aujourd'hui. Retirer la cause
entièrement = 29 offres récupérées. La décision actée implique le retrait complet.

**Q2 — description vs description_raw pour la détection**
`description` est toujours non NULL (0 sur 1934). `description_raw` est NULL pour 317 offres
(219 FT + 50 Indeed + 48 Remotive — 16 % de la base). Utiliser `description` uniquement.

**Q3 — Patron de backfill**
`backfill_description_raw.py` à la racine est le patron exact : script autonome, idempotent
sur `WHERE col IS NULL`, `--dry-run`, pas de LLM, pas de re-pull.

**Q4 — Filtre candidat : côté API ou Nuxt ?**
Côté API — VIEW_PRESETS envoie des query params, l'API filtre en SQL (pattern de `hors_perimetre`,
`hp_cause`, etc.). Ajouter `ad_language` comme query param dans `GET /offers` ; l'inclure dans
les 4 presets candidat du store. Aucune logique métier côté Nuxt (règle `frontend.md`).

**Q5 — EuresSource reçoit ses config via __init__**
Même patron que `FranceTravailSource(keywords=kw, commune=code, ...)`. Instantiation dans
`run.py` conditionnée sur la présence de "belgique_area" dans `active_zones` (déjà déclaré
dans le profil). `Source.fetch()` ne prend toujours aucun paramètre.

**Q6 — Fingerprint cross-source**
Tient en l'état. FT = emplois français ("67 - Strasbourg"), EURES = emplois belges
("Bruxelles"). Aucun chevauchement géographique → pas de faux doublons inter-sources.

**Q7 — Risque de run trop long**
Non mesurable depuis le code (pas de champ `duration_ms` dans les traces). Fourchette estimée :
200 nouvelles offres × ~15-25 s/offre (modèle local 8B) = 50-80 min. Risque réel mais non
bloquant pour ce chantier ; pas de timer à introduire ici.

---

## Schémas cibles

**`offers.ad_language TEXT`** — nouvelle colonne ajoutée via `migrate_offers_schema`.
Valeurs : `"fr" | "en" | "nl" | "other"` | NULL (NULL = non encore détecté).
Écrite par `backfill_ad_language.py` (existant) et par le pipeline à l'ingestion de
nouvelles offres (à partir de L6 pour EURES). Base de travail, pas contrat figé.

**`HorsPerimetreCause`** — enum réduit à 3 valeurs : `no_tech`, `mgmt_role`, `contrat`.
La valeur `langue` est supprimée. Aucun changement aux valeurs restantes.

Aucun changement au schéma `ExtractedFacts` ni au prompt/schéma de sortie de l'extractor.

---

## Phases

---

### Phase 1 — Retrait de la cause `langue` + rescore des 29 libérées

**Objectif** : aucune offre n'est plus écartée pour raison de langue ; les 29 offres
libérées passent le gate et sont rescorées sans appel LLM.

**Fichiers touchés** : `orchestrator/job_search/scoring/hors_perimetre.py`, rescore en CLI.

- [ ] **L1a** — Quatre fichiers à mettre à jour en une passe :
      — `scoring/hors_perimetre.py` : supprimer `LANGUES_TIERCES`, `_LANGUE_RE`, le bloc
        "Règle langue" (lignes 63-66 actuelles), et la valeur `langue` de l'enum `HorsPerimetreCause`.
      — `tests/test_hors_perimetre.py` : supprimer les tests de la section "Règle langue"
        (classe `TestLangue` ou équivalent — toute assertion sur `HorsPerimetreCause.langue`).
      — `api/offers.py:198` : mettre à jour la docstring `hp_cause` — retirer `langue` de la
        liste des valeurs valides.
      — `api/export.py:41` : idem.
- [ ] **L1b** — Rescore des libérées : `python -m orchestrator.job_search.rescore --force`.
      Réutilise les `extracted_facts_json` en cache — 0 appel LLM. Relever `wc -l
      data/traces/extract_facts.jsonl` avant l'exécution pour comparer après.

✋ Verify before continuing:
- [ ] `git diff orchestrator/job_search/scoring/extractor.py` est vide — prompt système et schéma de sortie identiques (invariant L1a)
- [ ] `wc -l data/traces/extract_facts.jsonl` avant = après le rescore — 0 nouvelle trace LLM (invariant L1b)
- [ ] `SELECT COUNT(*) FROM offers WHERE perimetre_causes LIKE '%"langue"%'` → 0 — aucune offre encore gatée par `langue`

Si tout est OK : "go". Sinon dis ce qui cloche.

---

### Phase 2 — Champ `ad_language` + backfill + filtre candidat

**Objectif** : toute offre en base porte sa langue de rédaction ; la vue candidat
n'affiche que les offres rédigées en français ou en anglais.

**Fichiers touchés** : `storage/db.py`, nouveau `scoring/ad_language.py`, nouveau
`backfill_ad_language.py` (racine), `api/offers.py`, `web/app/stores/offers.ts`.

- [ ] **L2** — `storage/db.py:migrate_offers_schema` : ajouter `("ad_language", "TEXT")` dans
      la liste `add_cols`. La migration est idempotente — si la colonne existe déjà, rien ne
      se passe.
- [ ] **L3** — Nouveau `orchestrator/job_search/scoring/ad_language.py` : fonction
      `detect_ad_language(text: str) -> str` retournant `"fr" | "en" | "nl" | "other"`.
      Détection offline uniquement — aucun import `ollama`, `requests`, `httpx`, `socket` ni
      aucun client modèle. Utiliser `langdetect` (bibliothèque offline). Si `len(text) < 100`
      : retourner `"other"` (texte trop court, détection non fiable — logguer un warning).
- [ ] **L4** — Nouveau `backfill_ad_language.py` à la racine, calqué sur
      `backfill_description_raw.py` : idempotent sur `WHERE ad_language IS NULL`, lit
      `description`, appelle `detect_ad_language`, écrit `ad_language`. Argument `--dry-run`.
      Exécuter après écriture du fichier et valider le dry-run avant la passe réelle.
- [ ] **L5** — `api/offers.py:list_offers` : ajouter query param `ad_language: str | None`.
      Si renseigné, filtrer `o.ad_language IN (...)` (valeurs séparées par virgule comme
      `etat_review`). `stores/offers.ts:VIEW_PRESETS` : ajouter `ad_language: "fr,en"` dans
      les 4 presets candidat (`cibles`, `gaps`, `filet`, `retenues`). `OfferRow` et `Filters`
      : ajouter le champ `ad_language`.

✋ Verify before continuing:
- [ ] Imports de `scoring/ad_language.py` ne contiennent aucun de : `ollama`, `requests`, `httpx`, `socket`, `urllib` — vérifiable via lecture du fichier (invariant L3)
- [ ] `SELECT COUNT(*) FROM offers WHERE ad_language IS NULL` → 0 après le backfill (L4 — backfill complet)
- [ ] `SELECT COUNT(*), ad_language FROM offers GROUP BY ad_language` : les offres nl sont en base mais `GET /offers` avec les filtres candidat (`ad_language=fr,en`) ne les retourne pas (L5 — filtre candidat)

Si tout est OK : "go". Sinon dis ce qui cloche.

---

### Phase 3 — Source EURES + câblage run.py

**Objectif** : les offres belges rentrent dans la base via EURES, avec url + company réels,
sans bloquer sur la localisation, et invisibles dans la vue candidat si rédigées en néerlandais.

**Fichiers touchés** : nouveau `orchestrator/job_search/sources/eures.py`, `run.py`.

- [ ] **L6** — Nouveau `sources/eures.py` : implémenter `EuresSource(keywords: list[str],
      countries: list[str] = ["BE"], max_per_keyword: int = 200)`.
      — Pagination : POST search avec 1 keyword, `resultsPerPage` ≤ 50, `pageNumber` incrémenté
        jusqu'à ce que `jvs` soit vide (HTTP 200 = fin normale, pas d'erreur).
      — Détail : GET `.../public/jv/id/{id}` pour chaque offre — champs à récupérer : employer
        réel, url de candidature, ville en clair.
      — Délai entre appels (au minimum `time.sleep(0.5)`).
      — Mapping → `JobOffer` : `source="eures"`, `url` = lien de candidature non nul (toujours
        depuis la réponse détail), `company` = employeur réel (champ `employer` de la réponse
        détail, pas l'agence intermédiaire), `location` = ville en clair depuis la réponse
        détail, `description` = champ texte de l'offre nettoyé via `_clean.html_to_markdown()`,
        `description_raw` = texte brut avant nettoyage.
      — Fingerprint via `fingerprint(title, company, location)` (module partagé).
      — Gestion d'erreur : une offre échouée = warning + skip (jamais de crash du run).
- [ ] **L7** — `run.py` : dans le bloc fetch, si `"belgique_area" in active_zones`, instancier
      `EuresSource(keywords=kw)` et l'ajouter à `sources`. Ajouter option CLI `--no-eures`.

✋ Verify before continuing:
- [ ] `SELECT COUNT(*) FROM offers WHERE source='eures' AND url IS NULL` → 0 (invariant L6 — url toujours non nulle)
- [ ] `SELECT location, filter_reason FROM offers WHERE source='eures' AND filter_reason='location:hors_zone'` → 0 lignes pour des lieux belges réels comme Bruxelles, Gand, etc. (invariant L6+L7)
- [ ] Sur 10 offres EURES tirées au hasard : `company` = employeur réel, pas agence interim (invariant L6 — company mapping depuis réponse détail)
- [ ] `SELECT COUNT(*), ad_language FROM offers WHERE source='eures' GROUP BY ad_language` : `nl` > 0 en base ET `GET /offers` avec les filtres candidat ne les retourne pas (invariants L5+L6 combinés)

Si tout est OK : "go". Sinon dis ce qui cloche.

---

## Livrables détaillés

1. **L1a — Retrait cause `langue`** (`scoring/hors_perimetre.py`) — supprimer enum value,
   constantes regex, et bloc de règle. Done = `git diff` ne montre que des suppressions dans
   ce fichier, aucune addition. **XS**

2. **L1b — Rescore libération** — `rescore --force` sur 29 offres. Done = `wc -l
   extract_facts.jsonl` avant = après (0 appel LLM). **XS**

3. **L2 — Colonne `ad_language`** (`storage/db.py`) — ajout idempotent dans `migrate_offers_schema`.
   Done = `PRAGMA table_info(offers)` montre `ad_language TEXT`. **XS**

4. **L3 — Module `scoring/ad_language.py`** — `detect_ad_language(text) -> str`, offline.
   Done = imports sans client réseau ni modèle, détection correcte sur échantillon. **S**

5. **L4 — Backfill `backfill_ad_language.py`** — idempotent, `--dry-run`. Done = 0 NULL en
   base après exécution, dry-run validé manuellement avant la passe réelle. **S**

6. **L5 — Filtre candidat** (`api/offers.py` + `stores/offers.ts`) — query param `ad_language`
   + VIEW_PRESETS. Done = `GET /offers?ad_language=fr,en` exclut les offres nl. **S**

7. **L6 — `EuresSource`** (`sources/eures.py`) — search + detail par offre, mapping complet,
   url non nulle, company = employeur réel, délai, pagination sur jvs vide. Done = 0 url
   NULL, company = employeur réel sur échantillon. **M**

8. **L7 — Câblage `run.py`** — condition belgique_area + `--no-eures`. Done = run déclenche
   EuresSource quand belgique_area est dans active_zones. **XS**

## Dépendances critiques

- L1a bloque L1b (rescore impossible sans le retrait)
- L2 bloque L4 (la colonne doit exister avant d'y écrire)
- L3 bloque L4 (backfill appelle `detect_ad_language`)
- L5 bloque la visibilité correcte des offres EURES dans la vue candidat
- L1 + L2 + L3 + L4 + L5 doivent être terminés avant L7 (sinon : offres nl visibles)

## Garde-fous

- Si `detect_ad_language` produit > 5 % d'erreurs sur le dry-run du backfill (offres en fr
  classées "other" ou "nl") → stop, inspecter l'échantillon avant de committer. La bibliothèque
  `langdetect` est probabiliste sur les textes courts.
- Si `SELECT COUNT(*) FROM offers WHERE source='eures' AND url IS NULL` > 0 après un run
  EURES → stop immédiat, remonter : l'url doit venir de la réponse détail, jamais construite
  synthétiquement.
- L'enum `HorsPerimetreCause` réduit à 3 valeurs : si un consommateur référence `HorsPerimetreCause.langue`
  quelque part dans le code, le retrait en L1a cassera à l'import → grep avant de retirer.
- Si le rescore (L1b) fait passer des offres de `perimetre_causes=['langue']` directement
  en catégorie (parfait/reve/etc.) sans les bloquer sur une autre cause → comportement
  nominal ; si toutes tombent en `perimetre_causes=['no_tech']` → attendu aussi (elles
  avaient peut-être techs_required=[] en plus de la cause langue).
