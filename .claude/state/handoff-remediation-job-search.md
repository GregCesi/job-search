# HANDOFF — Remédiation job-search
> Produit le 2026-07-14, en clôture du chantier cadrage (cartographie → confrontation → plan).
> Source : CARTE.md (carte factuelle validée) + décisions de la conversation de cadrage.
> Usage : sections PROMPT à coller dans Claude Code, une par session. Une vague = une session = un cycle complet (Phase 0 → implémentation → /review → /handoff).

---

## A. REGISTRE DES DÉCISIONS ACTÉES

| # | Sujet | Décision | Justification métier |
|---|-------|----------|----------------------|
| D1 | Zones géographiques | Source unique dans `profiles/gregoire.yaml` : une entrée par zone portant les DEUX faces (`insee` pour le fetch France Travail, `dept` + `keywords` pour le hard filter). `AREA_COMMUNES` (france_travail.py:17) et `AREA_RULES` (filters.py:22) supprimés. Validation Pydantic : zone incomplète refusée. | Bug nancy (fetchée puis rejetée au gate) rendu structurellement impossible. Élargissement France = ajout d'entrées YAML, zéro code. |
| D2 | `contract_types` | Branché : le gate contrat (filters.py:31) lit `profile.search_criteria.contract_types` au lieu de ses patterns hardcodés. | Config déclarée et remplie mais ignorée = mensonge actif. Dette dangereuse, corrigée. |
| D3 | Distance 30 km | Dette MARQUÉE, non corrigée. Registre de dette. | Pas de besoin réel actuel. Déclencheur de réveil : vouloir chercher au-delà de 30 km. |
| D4 | Seuils catégorie 50/40 | Dette MARQUÉE, non corrigée. Registre de dette. | Idem. Déclencheur : vouloir recalibrer parfait/rêve. |
| D5 | Bloc ChromaDB | Suppression TOTALE : `matching/embedder.py`, appel run.py step 11b, `data/chroma/`, `data/profile_cache.json`, dépendance sentence-transformers. | Écrit à chaque ingestion, jamais lu (`similarity()` sans appelant — carte §7.3). Vestige de l'archi embedding remplacée par le scoring déterministe. Git garde tout ; on ressuscitera sur cas réel confirmé. |
| D6 | `insert_stub()` (dedup.py:28) | Suppression. | Jamais appelée (carte §6.1). |
| D7 | `purge_irrelevant()` | Suppression fonction + 2 appels (run.py, rescore.py). | No-op, corps vide (carte §6.1). Faux-travail dans le pipeline. |
| D8 | `view.py` | Suppression. | Cassé (colonnes `score`, `criteria_json` droppées) ; jamais utilisé depuis le front Nuxt. Confirmé par Grégoire. |
| D9 | Chantier persistance/exposition API | PARKÉ, vague 4. Périmètre acté : dérivés (score_breakdown, etat_review, categorie_finale, review_stale) persistés au rescore ; API en SELECT pur ; route explicite « marquer vue » (fin du GET R4 à effet de bord) ; système d'états couleur (bleu foncé = à regarder, bleu clair = vu non validé, vert = validé, jaune = corrigé) comme états PERSISTÉS ; bugs export/traces (#6, #12). Les imports api→scoring (#11) tombent d'eux-mêmes. | Hors du process récupération→scoring délimité par Grégoire. Chantier moyen bien délimité — pas une refonte d'architecture (tout vit déjà dans le seul job_search.sqlite ; le défaut est « recalculer au lieu de lire »). |
| D10 | Workflow calibration (`human_reviews`) | PARKÉ avec D9. Constat carte : `upsert_review()` sans appelant, R10 lit une table qui ne se remplit plus. | Rattaché au chantier export/review. |
| D11 | Règles / cause racine | Chantier 3 : extraire les contrats par étage APRÈS les vagues 1-2, depuis le code assaini. Jamais avant (règles nées périmées). Pendant les vagues, les garde-fous vivent dans chaque prompt. | La majorité des fautes = règles jamais écrites (archi évoluée sans doc), pas règles violées. + facteur humain : handoffs sautés → remède = petites vagues fermées. |
| D12 | Séquencement | Vague 1 (nettoyage) AVANT Vague 2 (géo) : supprimer Chroma simplifie la boucle d'ingestion que la vague 2 modifie. Une vague = un cycle complet, périmètre gelé, toute découverte → registre de dette. | Risque décroissant, terrain nettoyé avant opération, rééducation méthodo. |

**Invariants à respecter dans TOUTES les vagues** (doctrine job-search) :
- Zéro LLM au rescore — tout scoring dépendant du profil est du Python pur ; le LLM extrait les faits intrinsèques UNE fois à l'ingestion.
- La trace brute est sacrée — canonicalisation au scoring uniquement, jamais à l'ingestion.
- Gates post-scoring avec causes en liste, scores préservés.
- `alias.yaml` = source unique de canonicalisation.

---

## B. PROMPT VAGUE 1 — Nettoyage (code mort)

```
CONTEXTE
Projet job-search (pipeline Python/FastAPI/SQLite/Nuxt de scoring d'offres d'emploi).
Une cartographie factuelle exhaustive (CARTE.md, si présente dans le repo) a identifié du
code mort résiduel d'une architecture antérieure (matching par embeddings, remplacé par un
scoring déterministe). Décisions actées et validées par Grégoire : suppression totale.

RÈGLE DE SESSION
- Phase 0 OBLIGATOIRE avant toute modification : lire le code réel concerné, confirmer que
  les faits ci-dessous tiennent toujours (grep des appelants). Si un fait ne tient plus
  (ex. un nouvel appelant de similarity()), STOP et signaler — ne pas improviser.
- Périmètre GELÉ : uniquement les livrables ci-dessous. Toute découverte annexe → l'ajouter
  au registre de dette (livrable 5), ne PAS la corriger.
- Aucun changement de comportement du pipeline hors suppression des étapes mortes.

LIVRABLES
1. Suppression du bloc ChromaDB :
   - matching/embedder.py (fichier entier)
   - run.py : instanciation Embedder + embed_profile + appel add_offer (step 11b de la boucle)
   - data/chroma/ et data/profile_cache.json (+ .gitignore si référencés)
   - dépendance sentence-transformers / chromadb (pyproject ou requirements)
2. Suppression insert_stub() dans storage/dedup.py (jamais appelée).
3. Suppression purge_irrelevant() (storage/purge.py) ET ses 2 appels (run.py, rescore.py).
   Si purge.py devient vide, supprimer le fichier.
4. Suppression orchestrator/job_search/view.py (cassé sur colonnes droppées, inutilisé).
   Retirer toute référence (docs, README, commandes).
5. Registre de dette : ajouter à .claude/state/DECISIONS.md (créer la section « Dette
   acceptée » si absente) trois entrées datées, chacune avec son déclencheur de réveil :
   - Distance de recherche 30 km hardcodée (france_travail.py) — réveil : besoin >30 km.
   - Seuils catégorie 50/40 hardcodés (categorize.py) — réveil : recalibrage des catégories.
   - Chantier persistance/exposition API (dérivés recalculés à la volée, GET à effet de bord
     seen_candidat, workflow human_reviews orphelin, bugs export/filtres de vues) — réveil :
     vague 4 planifiée.

✋ VERIFY (obligatoire avant de conclure)
- pytest : les 4 fichiers de test passent.
- python -m orchestrator.job_search.run --max 5 : run complet sans erreur sur un petit
  échantillon réel ; digest produit.
- python -m orchestrator.job_search.rescore --dry-run : sans erreur, 0 appel LLM
  (facts réutilisés depuis extracted_facts_json).
- grep -rn "embedder\|chroma\|sentence_transformers\|insert_stub\|purge_irrelevant" 
  sur le projet (hors .venv, hors CARTE.md) : zéro occurrence résiduelle.
- Constat attendu : ingestion plus rapide (plus d'embedding par offre).

CLÔTURE
/review sur le diff, puis /handoff (STATE, JOURNAL, DECISIONS, IMPLEMENTATION cochés).
Ne PAS enchaîner sur la vague 2 dans cette session.
```

---

## C. PROMPT VAGUE 2 — Zones géo source unique + contract_types

```
CONTEXTE
job-search, suite de la vague 1 (nettoyage livré). Problème central constaté par
cartographie : DEUX référentiels de zones divergents — AREA_COMMUNES
(sources/france_travail.py:17, 6 zones, codes INSEE, pilote le fetch) et AREA_RULES
(scoring/filters.py:22, 5 zones, préfixes dept + keywords, pilote le hard filter).
Divergence active : nancy présent dans AREA_COMMUNES, absent d'AREA_RULES → offres
fetchées (coût API + extraction LLM) puis systématiquement rejetées au gate.
Décision actée : source unique dans le profil, une entrée par zone portant les deux faces.

RÈGLE DE SESSION
- Phase 0 OBLIGATOIRE : lire france_travail.py, filters.py, matching/profile.py,
  profiles/gregoire.yaml, run.py (build sources). Confirmer les structures actuelles.
- Périmètre GELÉ. Découvertes annexes → registre de dette.
- INVARIANT : zéro LLM au rescore. Ce chantier ne touche ni l'extraction ni le scoring —
  uniquement fetch, hard filter localisation, gate contrat.

LIVRABLES
1. Schéma zones dans profiles/gregoire.yaml :
     zones:
       strasbourg:
         insee: ["67482"]
         dept: ["67"]
         keywords: ["strasbourg", "schiltigheim", ...]
       nancy:
         insee: ["54395"]
         dept: ["54"]
         keywords: ["nancy"]
       # ... reprendre TOUTES les zones actuellement dans AREA_COMMUNES,
       # en complétant les faces manquantes (nancy n'a pas de règle filtre aujourd'hui :
       # la créer). Reporter fidèlement les valeurs existantes des deux dicts.
   Modèle Pydantic (matching/profile.py) : Zone{insee: list[str] (min 1),
   dept: list[str] (min 1), keywords: list[str]}. Zone incomplète → ValidationError.
   Conserver la clé search_criteria.locations comme liste des zones ACTIVES (les entrées
   zones sont le référentiel ; locations sélectionne).
2. Fetch : france_travail.py consomme profile.zones[*].insee. AREA_COMMUNES supprimé.
3. Hard filter : filters.py consomme profile.zones[*].dept + keywords pour les zones
   actives. AREA_RULES supprimé. Comportement remote inchangé (offer.remote ET "remote"
   dans locations).
4. Gate contrat : filters.py lit profile.search_criteria.contract_types (déjà déclaré,
   déjà rempli, actuellement ignoré) au lieu des patterns hardcodés
   alternance/stage/apprentissage/MIS. Reporter les exclusions actuelles dans le YAML
   pour comportement identique à config identique.
5. Tests unitaires :
   - zone sans dept → ValidationError Pydantic.
   - cas nancy : offre location "54 - Nancy" avec nancy active → PASSE le hard filter.
   - offre alternance avec contract_types excluant l'alternance → filtered_out.

✋ VERIFY (obligatoire)
- pytest complet vert (anciens + nouveaux tests).
- grep -rn "AREA_COMMUNES\|AREA_RULES" (hors CARTE.md) : zéro occurrence.
- python -m orchestrator.job_search.run --max 5 : run réel sans erreur.
- python -m orchestrator.job_search.rescore --dry-run --force : catégories inchangées sur
  les offres existantes (le chantier ne touche pas au scoring — toute dérive de catégorie
  est un bug à investiguer avant de conclure).
- Démonstration cible : ajouter une zone de test dans le YAML (ex. lyon si absente des
  actives), relancer, constater fetch + filtre cohérents SANS modification de code.

CLÔTURE
/review, puis /handoff. Ne pas enchaîner sur le chantier règles dans cette session.
```

---

## D. PROMPT CHANTIER 3 — Cristallisation des règles

```
CONTEXTE
job-search, vagues 1 et 2 livrées : code assaini (zéro code mort, zones en source unique,
contract_types branché). Cause racine du chantier de dette : les règles du pipeline
n'avaient jamais été écrites — l'architecture a évolué (abandon embeddings, scoring
déterministe, gates à causes) sans que .claude/rules/ suive. On cristallise MAINTENANT,
depuis le code réel stabilisé — jamais depuis l'intention.

RÈGLE DE SESSION
- Phase 0 OBLIGATOIRE : relire le pipeline réel post-vagues (run.py, rescore.py, sources/,
  scoring/, storage/) + CARTE.md si présente. Chaque règle écrite doit être VRAIE du code
  actuel — c'est un contrat descriptif-normatif, pas un vœu.
- Ce chantier n'écrit AUCUN code. Uniquement .claude/rules/ (+ mise à jour STATE/DECISIONS).

LIVRABLE : .claude/rules/pipeline.md — un contrat par étage, format fixe :
  [étage] → CONSOMME (données, config) / PRODUIT (données, où) / INVARIANTS / INTERDITS.
Étages : 1 Fetch (sources pluggables → JobOffer) · 2 Dédup (fingerprint, source_id) ·
3 Hard filters (localisation via profile.zones, contrat via contract_types) ·
4 Extraction LLM (Ollama, faits intrinsèques, trace JSONL append) ·
5 Scoring + gates + catégorisation (Python pur, causes en liste, scores préservés) ·
6 Persistance (save_offer UPSERT, offers = seule vérité).

Invariants transversaux à inscrire (payés pendant les vagues) :
- Toute variable de pilotage (zones, contrats, seuils, distances) vit dans le profil YAML ;
  le code la consomme, ne la duplique jamais en dicts internes.
- Zéro LLM au rescore : le LLM extrait une fois à l'ingestion ; tout recalcul aval est du
  Python pur sur extracted_facts_json.
- La trace brute est sacrée : canonicalisation (alias.yaml, source unique) appliquée au
  scoring seulement, jamais à l'ingestion.
- Zéro code mort résiduel : tout changement d'architecture supprime ce qu'il remplace
  (git est la mémoire) ; on ressuscite sur cas réel confirmé.
- Gates post-scoring : perimetre_causes en liste, scores calculés et préservés,
  éliminations observables.

✋ VERIFY
- Relecture croisée : chaque ligne de pipeline.md est vérifiable dans le code actuel
  (référence fichier au moins par étage). Aucune règle « souhaitée mais pas encore vraie »
  — celles-là vont dans DECISIONS.md comme dette, pas dans rules/.

CLÔTURE
/review (sur les .md), /handoff.
```

---

## E. VAGUE 4 — Persistance & exposition (PARKÉE, pas de prompt)

Pas de prompt d'implémentation : le cadrage n'est pas fait, et la doctrine l'interdit
(pas d'IMPLEMENTATION sans décision tranchée). Périmètre déjà acté en D9/D10 —
à cadrer dans une conversation Claude.ai dédiée après le chantier 3, avec en entrée :
CARTE.md (§4 sonde B, §5.4, §5.5, §7.3 trou human_reviews) + le registre de dette.
Décisions restant à trancher au cadrage : schéma exact des états persistés (mapping
couleurs → colonnes/valeurs), moment de persistance des dérivés (rescore), forme de la
route « marquer vue », sort du workflow calibration (réactiver ou supprimer R10 + table).

---

## F. RÈGLES DE CONDUITE (toutes vagues)

1. Une vague = une session Claude Code = un cycle complet : Phase 0 → implémentation →
   /review → /handoff. Jamais deux vagues dans une session, même si « ça irait vite ».
2. Périmètre gelé à l'ouverture. Toute découverte en cours de route → registre de dette,
   jamais de correction opportuniste (anti-whack-a-mole).
3. Si la Phase 0 contredit un fait de ce document → STOP, remonter à Grégoire avant d'agir.
