Jet du 28 octobre 2026 — `git rev-parse HEAD` au démarrage du tour : `cfc1d41bfccca72bd6999807088d487175c1fa45`

# Qualité du code de job-search — recon EXE-203

Toutes les commandes se lancent depuis la racine du dépôt. Chaque sortie brute est
commitée sous `docs/recon/sorties/`, un fichier par commande. Les deux scripts
d'analyse écrits pour ce tour sont sous `docs/recon/outils/`.

## Mesures

### 4. Taille

Les 20 fichiers `.py`, `.vue` et `.ts` suivis par git qui ont le plus de lignes.

Commande : `git ls-files '*.py' '*.vue' '*.ts' | xargs wc -l | grep -v ' total$' | sort -rn | head -20`
Sortie : [`sorties/taille-top20.txt`](sorties/taille-top20.txt)

| Lignes | Fichier |
| --- | --- |
| 2670 | `web/app/pages/offers/[id].vue` |
| 1568 | `orchestrator/job_search/lettre/boucle.py` |
| 1239 | `api/offers.py` |
| 1157 | `tests/test_exe99_cascade_extraction.py` |
| 1085 | `tests/test_exe175_interprete_lettre_mieux_jugee.py` |
| 930 | `orchestrator/job_search/lettre/banc.py` |
| 886 | `tests/test_exe151_jeu_banc_lettre.py` |
| 864 | `tests/test_exe147_boucle_lettre.py` |
| 863 | `api/lettre.py` |
| 825 | `tests/test_exe158_juge_ressenti_recruteur.py` |
| 816 | `tests/test_exe98_extraction_retry.py` |
| 811 | `orchestrator/job_search/lettre/service.py` |
| 797 | `tests/test_exe160_verificateur_lettre.py` |
| 789 | `tests/test_exe127_cascade.py` |
| 778 | `tests/test_exe202_navigateur.py` |
| 775 | `tests/test_exe174_trace_lettre.py` |
| 742 | `tests/test_exe162_boucle_app.py` |
| 712 | `tests/test_exe173_regenerer_depuis_ma_lettre.py` |
| 708 | `tests/test_exe164_forem.py` |
| 707 | `orchestrator/job_search/run.py` |

### 5. Racine

8 fichiers `.py` suivis par git à la racine du dépôt.

Commande : `git ls-files '*.py' | grep -v /`
Sortie : [`sorties/racine-py.txt`](sorties/racine-py.txt)

- `audit_profil.py`
- `backfill_ad_language.py`
- `backfill_description_raw.py`
- `experiment_tck200.py`
- `experiment_tck206.py`
- `experiment_tck206_cv.py`
- `experiment_tck210.py`
- `replay_traces.py`

### 6. Complexité par bloc

Blocs de rang C ou pire, par rang : 27 en C, 10 en D, 2 en E, 4 en F.

Commande : `.venv/bin/radon cc -s -n C api orchestrator`
Sortie : [`sorties/radon-cc-C.txt`](sorties/radon-cc-C.txt). Le compte par rang vient de
`grep -c " - <rang> (" docs/recon/sorties/radon-cc-C.txt`, pour C, D, E et F.

La ligne est celle de la définition (`def`), telle que radon la rend.

| Rang (score) | Bloc | Fichier:ligne |
| --- | --- | --- |
| F (69) | `list_offers` | `api/offers.py:470` |
| F (62) | `main` | `orchestrator/job_search/rescore.py:25` |
| F (57) | `resumer_config` | `orchestrator/job_search/lettre/banc.py:311` |
| F (47) | `export_offers` | `api/export.py:56` |
| E (37) | `main` | `orchestrator/job_search/run.py:228` |
| E (32) | `_format_export_md` | `api/export.py:245` |
| D (28) | `_derive_score_breakdown` | `api/offers.py:61` |
| D (28) | `rechercher_entreprise` | `orchestrator/job_search/fiche/service.py:193` |
| D (27) | `extract_facts` | `orchestrator/job_search/scoring/extractor.py:182` |
| D (25) | `run_cv` | `orchestrator/job_search/cv/service.py:147` |
| D (24) | `identify_employer` | `orchestrator/job_search/fiche/cascade.py:93` |
| D (23) | `export_calibration` | `api/export.py:380` |
| D (23) | `apply_hard_filters` | `orchestrator/job_search/scoring/filters.py:52` |
| D (23) | `ForemSource._map` | `orchestrator/job_search/sources/forem.py:157` |
| D (22) | `noeud_tamis` | `orchestrator/job_search/lettre/boucle.py:504` |
| D (22) | `ActirisSource._map` | `orchestrator/job_search/sources/actiris.py:196` |
| C (17) | `aggregate` | `orchestrator/job_search/reference/metrics.py:148` |
| C (16) | `_generate_via_boucle` | `orchestrator/job_search/lettre/service.py:274` |
| C (15) | `_tri_phase` | `orchestrator/job_search/run.py:50` |
| C (15) | `_second_pass_batches` | `orchestrator/job_search/run.py:146` |
| C (15) | `_blocs_communs_redaction` | `orchestrator/job_search/lettre/boucle.py:602` |
| C (15) | `_parser_verificateur` | `orchestrator/job_search/lettre/boucle.py:916` |
| C (14) | `carte_lettre` | `orchestrator/job_search/pieces.py:114` |
| C (14) | `run_expiration_check` | `orchestrator/job_search/expiration/service.py:43` |
| C (13) | `_annexe_passage` | `orchestrator/job_search/lettre/banc.py:583` |
| C (13) | `disagreement` | `orchestrator/job_search/calibration/disagreement.py:28` |
| C (13) | `migrate_lettres_schema` | `orchestrator/job_search/storage/db.py:418` |
| C (13) | `ensure_models_available` | `orchestrator/job_search/scoring/extractor.py:132` |
| C (13) | `apply_correction` | `orchestrator/job_search/cv/service.py:341` |
| C (12) | `_invoquer_graphe` | `orchestrator/job_search/lettre/boucle.py:1383` |
| C (12) | `migrate_lettre_versions_schema` | `orchestrator/job_search/storage/db.py:464` |
| C (12) | `ForemSource._list_all` | `orchestrator/job_search/sources/forem.py:105` |
| C (12) | `ActirisSource._list_all` | `orchestrator/job_search/sources/actiris.py:127` |
| C (12) | `ActirisSource._parse_detail` | `orchestrator/job_search/sources/actiris.py:252` |
| C (12) | `FranceTravailSource._map` | `orchestrator/job_search/sources/france_travail.py:130` |
| C (12) | `recalc_profile_after_fiche` | `orchestrator/job_search/cv/service.py:570` |
| C (11) | `get_offer` | `api/offers.py:869` |
| C (11) | `launch_lettre_if_ready` | `api/lettre.py:377` |
| C (11) | `list_traces` | `api/traces.py:119` |
| C (11) | `valider_juge_et_redaction` | `orchestrator/job_search/lettre/repertoire.py:280` |
| C (11) | `parser_config` | `orchestrator/job_search/lettre/banc.py:87` |
| C (11) | `main` | `orchestrator/job_search/lettre/banc.py:846` |
| C (11) | `_section_repertoire` | `orchestrator/job_search/fiche/prompt.py:71` |

### 7. Complexité moyenne

`Average complexity: A (3.970959595959596)` — sur 792 blocs analysés (avant-dernière ligne de la même sortie).

Commande : `.venv/bin/radon cc -s -a api orchestrator`
Sortie : [`sorties/radon-cc-moyenne.txt`](sorties/radon-cc-moyenne.txt)

### 8. Maintenabilité

2 fichiers de rang B ou pire.

Commande : `.venv/bin/radon mi -s api orchestrator`
Sortie : [`sorties/radon-mi.txt`](sorties/radon-mi.txt)

| Fichier | Rang (indice) |
| --- | --- |
| `api/offers.py` | C (8.24) |
| `orchestrator/job_search/lettre/boucle.py` | B (11.16) |

### 9. Duplication

1,18 % de lignes dupliquées (357 sur 30 188), 28 clones, sur 144 fichiers. Par format :
Python 24 clones, 310 lignes (1,54 %) ; TypeScript 2 clones, 28 lignes (0,90 %) ;
HTML 2 clones, 19 lignes (1,17 %) ; Vue 0 clone.

Commande : `npx -y jscpd@5.4.2 api orchestrator web/app --min-lines 6 --reporters console,json --output docs/recon/sorties/jscpd`
Sorties : [`sorties/jscpd-console.txt`](sorties/jscpd-console.txt) (console, codes de couleur
compris) et [`sorties/jscpd/jscpd-report.json`](sorties/jscpd/jscpd-report.json).

jscpd rend chaque fichier relatif au dossier passé en argument. Les chemins ci-dessous
sont rattachés à la racine par la commande
`.venv/bin/python docs/recon/outils/clones_chemins.py`, sortie
[`sorties/jscpd-clones-chemins.txt`](sorties/jscpd-clones-chemins.txt) (0 nom ambigu).

| Premier emplacement | Second emplacement | Lignes | Format |
| --- | --- | --- | --- |
| `api/avancement.py:43-55` | `api/mail.py:59-71` | 13 | python |
| `api/cv.py:51-63` | `api/fiche.py:34-46` | 13 | python |
| `api/cv.py:131-137` | `api/fiche.py:129-135` | 7 | python |
| `api/cv.py:141-151` | `api/fiche.py:139-149` | 11 | python |
| `api/export.py:90-104` | `api/offers.py:532-546` | 15 | python |
| `api/export.py:103-128` | `api/offers.py:563-588` | 26 | python |
| `api/export.py:174-187` | `api/offers.py:656-669` | 14 | python |
| `api/export.py:186-203` | `api/offers.py:672-689` | 18 | python |
| `api/export.py:203-211` | `api/offers.py:695-702` | 9 | python |
| `api/export.py:334-345` | `api/offers.py:80-91` | 12 | python |
| `api/export.py:400-408` | `orchestrator/job_search/storage/reviews.py:61-69` | 9 | python |
| `api/lettre.py:438-447` | `api/lettre.py:499-508` | 10 | python |
| `orchestrator/job_search/cv/service.py:135-144` | `orchestrator/job_search/fiche/service.py:147-156` | 10 | python |
| `orchestrator/job_search/cv/service.py:353-361` | `orchestrator/job_search/cv/service.py:637-645` | 9 | python |
| `orchestrator/job_search/cv/service.py:355-361` | `orchestrator/job_search/cv/service.py:501-507` | 7 | python |
| `orchestrator/job_search/cv/service.py:387-396` | `orchestrator/job_search/cv/service.py:464-473` | 10 | python |
| `orchestrator/job_search/cv/service.py:597-615` | `orchestrator/job_search/cv/service.py:646-664` | 19 | python |
| `orchestrator/job_search/expiration/service.py:56-63` | `orchestrator/job_search/expiration/service.py:71-78` | 8 | python |
| `orchestrator/job_search/ingestion.py:445-456` | `orchestrator/job_search/ingestion.py:606-617` | 12 | python |
| `orchestrator/job_search/lettre/boucle.py:337-347` | `orchestrator/job_search/mail/generation.py:109-118` | 11 | python |
| `orchestrator/job_search/lettre/service.py:416-452` | `orchestrator/job_search/lettre/service.py:524-560` | 37 | python |
| `orchestrator/job_search/lettre/service.py:629-641` | `orchestrator/job_search/lettre/service.py:707-719` | 13 | python |
| `orchestrator/job_search/sources/actiris.py:300-306` | `orchestrator/job_search/sources/forem.py:204-210` | 7 | python |
| `orchestrator/job_search/suivi/storage.py:95-104` | `orchestrator/job_search/suivi/storage.py:135-144` | 10 | python |
| `web/app/components/OfferDetail.vue:567-586` | `web/app/pages/offers/[id].vue:2650-2669` | 20 | typescript |
| `web/app/pages/offers/[id].vue:552-566` | `web/app/pages/offers/[id].vue:899-931` | 15 | html |
| `web/app/pages/offers/[id].vue:629-643` | `web/app/pages/offers/[id].vue:666-680` | 15 | html |
| `web/app/pages/offers/[id].vue:2401-2410` | `web/app/pages/offers/[id].vue:2432-2441` | 10 | typescript |

### 10. Code mort Python

6 lignes. Code de sortie 3.

Commande : `.venv/bin/vulture api orchestrator --min-confidence 80`
Sortie : [`sorties/vulture.txt`](sorties/vulture.txt)

```
api/ajouts.py:47: unused variable 'cls' (100% confidence)
api/ajouts.py:52: unused variable 'cls' (100% confidence)
api/offers.py:1034: unused variable 'cls' (100% confidence)
api/pieces.py:56: unused variable 'cls' (100% confidence)
api/reference.py:37: unused variable 'cls' (100% confidence)
orchestrator/job_search/sources/base.py:43: unused variable 'cls' (100% confidence)
```

### 11. Code mort du front

knip a rendu un rapport (pas une pile d'erreur), code de sortie 1 : 1 fichier,
2 dépendances et 17 types exportés non utilisés.

Commandes, dans `web/` : `npm ci` (sortie [`sorties/npm-ci.txt`](sorties/npm-ci.txt), code 0),
puis `npx -y knip@6.43.0 --no-progress`.
Sortie : [`sorties/knip.txt`](sorties/knip.txt)

```
Unused files (1)
tailwind.config.ts
Unused dependencies (2)
@tailwindcss/typography  package.json:15:6
vue-router               package.json:21:6
Unused exported types (17)
GesteEtat            interface  app/stores/offers.ts:5:18
ExpirationCheck      interface  app/stores/offers.ts:59:18
EvenementHistorique  interface  app/stores/offers.ts:79:18
FichePoint           interface  app/stores/offers.ts:115:18
FicheSource          interface  app/stores/offers.ts:124:18
CvSkillGroup         interface  app/stores/offers.ts:149:18
CvStatut             type       app/stores/offers.ts:154:13
LettreStatut         type       app/stores/offers.ts:178:13
FaitRetenu           interface  app/stores/offers.ts:180:18
Jugement             interface  app/stores/offers.ts:189:18
Releve               interface  app/stores/offers.ts:197:18
LettreEtape          interface  app/stores/offers.ts:205:18
LettreCarte          interface  app/stores/offers.ts:301:18
AvancementEtat       type       app/stores/offers.ts:332:13
OperatorView         type       app/stores/offers.ts:367:13
PieceKey             type       app/stores/pieceNotifications.ts:9:13
TraceParsedFacts     interface  app/stores/traces.ts:5:18
```

Les chemins de knip sont relatifs à `web/`.

### 12. Couches

Contrat `metier-sans-web` : 0 tenu, 1 cassé, code de sortie 1. 110 fichiers et
300 dépendances analysés. Un import interdit :

- `orchestrator/job_search/rescore.py:155` — `orchestrator.job_search.rescore -> api.view_profile`

Contrat : [`contrat-couches.toml`](contrat-couches.toml), les neuf lignes de H4, écrit sans refus.
Commande : `PYTHONPATH=. .venv/bin/lint-imports --config docs/recon/contrat-couches.toml --no-cache`
Sortie : [`sorties/lint-imports.txt`](sorties/lint-imports.txt)

### 13. Base par couche

Nombre d'occurrences de `.execute(`, fichiers à zéro exclus.

Sous `api/`, par fichier.

Commande : `grep -rno "\.execute(" api --include="*.py" | cut -d: -f1 | sort | uniq -c | sort -rn`
Sortie : [`sorties/execute-api.txt`](sorties/execute-api.txt)

| Appels | Fichier |
| --- | --- |
| 27 | `api/lettre.py` |
| 12 | `api/offers.py` |
| 10 | `api/pieces.py` |
| 10 | `api/fiche.py` |
| 10 | `api/cv.py` |
| 8 | `api/avancement.py` |
| 6 | `api/traces.py` |
| 4 | `api/mail.py` |
| 4 | `api/expiration.py` |
| 2 | `api/export.py` |
| 2 | `api/ajouts.py` |
| 1 | `api/traces_reader.py` |

Sous `orchestrator/job_search/`, par sous-dossier. Les fichiers posés
directement dans `orchestrator/job_search/` sont comptés chacun à part.

Commande : `grep -rno "\.execute(" orchestrator/job_search --include="*.py" | cut -d: -f1 | awk -F/ '{ print (NF>3 ? $1"/"$2"/"$3"/" : $0) }' | sort | uniq -c | sort -rn`
Sortie : [`sorties/execute-orchestrator.txt`](sorties/execute-orchestrator.txt)

| Appels | Sous-dossier ou fichier |
| --- | --- |
| 52 | `orchestrator/job_search/storage/` |
| 27 | `orchestrator/job_search/lettre/` |
| 24 | `orchestrator/job_search/cv/` |
| 21 | `orchestrator/job_search/suivi/` |
| 10 | `orchestrator/job_search/run.py` |
| 7 | `orchestrator/job_search/fiche/` |
| 6 | `orchestrator/job_search/ingestion.py` |
| 4 | `orchestrator/job_search/mail/` |
| 3 | `orchestrator/job_search/expiration/` |
| 2 | `orchestrator/job_search/verdict.py` |
| 2 | `orchestrator/job_search/pdf/` |
| 2 | `orchestrator/job_search/ajout/` |
| 1 | `orchestrator/job_search/rescore.py` |
| 1 | `orchestrator/job_search/reference/` |

### 14. Routes

67 routes, autant que de décorateurs comptés au démarrage du tour.
Par valeur : 22 « base directe », 7 « délègue », 32 « les deux », 6 « aucune ».

Décorateurs : `grep -rnE '@(router|app)\.(get|post|put|patch|delete)\(' api --include='*.py'`,
sortie [`sorties/decorateurs-routes.txt`](sorties/decorateurs-routes.txt), 67 lignes.

Classement : `.venv/bin/python docs/recon/outils/routes_base.py`, sortie
[`sorties/routes-base.txt`](sorties/routes-base.txt). Le script lit le code par `ast`
sans l'importer. Depuis la fonction de la route, il suit transitivement toute fonction
de `api/` ou de `orchestrator/` qu'elle appelle ou passe en argument, à travers les
imports. Une fonction touche la base si son texte contient `.execute(`. La valeur
« aucune » s'ajoute aux trois du ticket : aucune fonction atteinte ne contient `.execute(`.
Le chemin est le `prefix` de l'`APIRouter` suivi du chemin du décorateur.

| Méthode | Chemin | Fichier:ligne | Valeur |
| --- | --- | --- | --- |
| POST | `/ajouts` | `api/ajouts.py:90` | délègue |
| GET | `/ajouts` | `api/ajouts.py:109` | base directe |
| GET | `/ajouts/{ajout_id}` | `api/ajouts.py:122` | base directe |
| GET | `/offers/{offer_id}/avancement` | `api/avancement.py:98` | les deux |
| GET | `/avancement` | `api/avancement.py:114` | base directe |
| POST | `/offers/{offer_id}/cv` | `api/cv.py:151` | les deux |
| GET | `/offers/{offer_id}/cv` | `api/cv.py:170` | base directe |
| POST | `/offers/{offer_id}/cv/skills` | `api/cv.py:186` | les deux |
| PUT | `/offers/{offer_id}/cv/titre` | `api/cv.py:212` | les deux |
| PUT | `/offers/{offer_id}/cv/profil` | `api/cv.py:229` | les deux |
| POST | `/offers/{offer_id}/cv/en` | `api/cv.py:246` | les deux |
| GET | `/offers/{offer_id}/cv/pdf` | `api/cv.py:286` | les deux |
| GET | `/offers/{offer_id}/cv/corrections` | `api/cv.py:329` | base directe |
| PUT | `/offers/{offer_id}/employer-url` | `api/expiration.py:24` | les deux |
| POST | `/offers/check-expirations` | `api/expiration.py:59` | les deux |
| GET | `/export/offers` | `api/export.py:55` | les deux |
| GET | `/export/calibration` | `api/export.py:379` | base directe |
| POST | `/offers/{offer_id}/fiche` | `api/fiche.py:149` | les deux |
| GET | `/offers/{offer_id}/fiche` | `api/fiche.py:169` | base directe |
| PUT | `/offers/{offer_id}/fiche/avis` | `api/fiche.py:189` | base directe |
| POST | `/offers/{offer_id}/fiche/intermediaire` | `api/fiche.py:209` | base directe |
| PATCH | `/offers/{offer_id}/fiche/points/{point_idx}` | `api/fiche.py:273` | base directe |
| POST | `/offers/{offer_id}/fiche/points/{point_idx}/explain` | `api/fiche.py:284` | base directe |
| GET | `/offers/{offer_id}/lettre/points` | `api/lettre.py:248` | base directe |
| PUT | `/offers/{offer_id}/lettre/points` | `api/lettre.py:260` | base directe |
| POST | `/offers/{offer_id}/lettre` | `api/lettre.py:428` | les deux |
| POST | `/offers/{offer_id}/lettre/ne-pas-faire` | `api/lettre.py:466` | les deux |
| POST | `/offers/{offer_id}/lettre/revenir` | `api/lettre.py:493` | les deux |
| GET | `/offers/{offer_id}/lettre` | `api/lettre.py:527` | base directe |
| PUT | `/offers/{offer_id}/lettre/angle` | `api/lettre.py:545` | les deux |
| PUT | `/offers/{offer_id}/lettre/texte` | `api/lettre.py:562` | les deux |
| POST | `/offers/{offer_id}/lettre/regenerer` | `api/lettre.py:621` | les deux |
| POST | `/offers/{offer_id}/lettre/regenerer-depuis-ma-lettre` | `api/lettre.py:647` | délègue |
| POST | `/offers/{offer_id}/lettre/ecarter` | `api/lettre.py:674` | délègue |
| POST | `/offers/{offer_id}/lettre/remettre` | `api/lettre.py:700` | les deux |
| GET | `/offers/{offer_id}/lettre/pdf` | `api/lettre.py:760` | les deux |
| GET | `/offers/{offer_id}/lettre/mise-en-page` | `api/lettre.py:778` | les deux |
| GET | `/offers/{offer_id}/lettre/versions` | `api/lettre.py:796` | base directe |
| GET | `/offers/{offer_id}/lettre/versions/{version_id}/appels` | `api/lettre.py:852` | base directe |
| GET | `/offers/{offer_id}/mail` | `api/mail.py:75` | les deux |
| PUT | `/offers/{offer_id}/mail` | `api/mail.py:99` | délègue |
| POST | `/offers/{offer_id}/mail/generer` | `api/mail.py:110` | les deux |
| GET | `/offers/{offer_id}/mail/appel` | `api/mail.py:154` | délègue |
| GET | `/health` | `api/main.py:71` | aucune |
| GET | `/offers` | `api/offers.py:469` | les deux |
| GET | `/offers/suivi/compte-etapes` | `api/offers.py:795` | les deux |
| POST | `/offers/check-known` | `api/offers.py:838` | base directe |
| GET | `/offers/{offer_id}` | `api/offers.py:868` | les deux |
| POST | `/offers/{offer_id}/geste` | `api/offers.py:1038` | les deux |
| PUT | `/offers/{offer_id}/verdict` | `api/offers.py:1078` | les deux |
| PUT | `/offers/{offer_id}/category-review` | `api/offers.py:1127` | base directe |
| GET | `/offers/{offer_id}/review` | `api/offers.py:1175` | base directe |
| DELETE | `/offers/{offer_id}/verdict` | `api/offers.py:1198` | les deux |
| DELETE | `/offers/{offer_id}/revue` | `api/offers.py:1224` | les deux |
| GET | `/offers/{offer_id}/pieces` | `api/pieces.py:76` | les deux |
| PUT | `/offers/{offer_id}/envoyee` | `api/pieces.py:123` | délègue |
| PUT | `/offers/{offer_id}/cv/pret` | `api/pieces.py:169` | les deux |
| PUT | `/offers/{offer_id}/lettre/pret` | `api/pieces.py:197` | les deux |
| GET | `/reference` | `api/reference.py:72` | aucune |
| GET | `/reference/{entry_id}` | `api/reference.py:86` | aucune |
| PUT | `/reference/{entry_id}` | `api/reference.py:96` | aucune |
| POST | `/offers/{offer_id}/reference` | `api/reference.py:114` | délègue |
| GET | `/traces/counts` | `api/traces.py:103` | aucune |
| GET | `/traces/versions` | `api/traces.py:109` | aucune |
| GET | `/traces` | `api/traces.py:118` | base directe |
| PUT | `/traces/{trace_key}/note` | `api/traces.py:154` | base directe |
| GET | `/traces/export` | `api/traces.py:193` | base directe |

### 15. Sources

Fichiers sous `api/`, `orchestrator/` hors `orchestrator/job_search/sources/`, et `web/app/`,
suivis par git, qui nomment la source. Le motif cherche le nom en minuscules, avec
une capitale initiale ou en capitales, non précédé d'une lettre minuscule (pour ne pas
compter « heures » pour eures). Pour france_travail, il cherche aussi `FranceTravail`,
`France Travail` et `france travail`.

Commande, pour chaque source : `git grep -lE '<motif>' -- api orchestrator ':!orchestrator/job_search/sources/' web/app`.
Le motif exact est en première ligne de chaque sortie.

| Source | Fichiers | Liste | Sortie |
| --- | --- | --- | --- |
| actiris | 1 | `orchestrator/job_search/run.py` | [`source-actiris.txt`](sorties/source-actiris.txt) |
| eures | 2 | `orchestrator/job_search/run.py`, `orchestrator/job_search/scoring/filters.py` | [`source-eures.txt`](sorties/source-eures.txt) |
| forem | 1 | `orchestrator/job_search/run.py` | [`source-forem.txt`](sorties/source-forem.txt) |
| france_travail | 3 | `orchestrator/job_search/run.py`, `orchestrator/job_search/scoring/filters.py`, `web/app/components/FiltersPanel.vue` | [`source-france_travail.txt`](sorties/source-france_travail.txt) |
| indeed | 4 | `orchestrator/job_search/ingestion.py`, `orchestrator/job_search/run.py`, `orchestrator/job_search/scoring/filters.py`, `web/app/components/FiltersPanel.vue` | [`source-indeed.txt`](sorties/source-indeed.txt) |
| manual | 4 | `api/ajouts.py`, `api/cv.py`, `orchestrator/job_search/ajout/service.py`, `orchestrator/job_search/cv/service.py` | [`source-manual.txt`](sorties/source-manual.txt) |
| remotive | 2 | `orchestrator/job_search/run.py`, `web/app/components/FiltersPanel.vue` | [`source-remotive.txt`](sorties/source-remotive.txt) |

### 16. Pièces

Fichiers sous `api/`, `orchestrator/job_search/` hors du dossier de la pièce, et `web/app/`,
suivis par git, qui nomment la pièce. Même règle de motif qu'en 15 (non précédé d'une
minuscule : « affiche » n'est pas compté pour fiche).

Commande, pour chaque pièce : `git grep -lE '<motif>' -- api orchestrator/job_search ':!orchestrator/job_search/<pièce>/' web/app`.
Le motif exact est en première ligne de chaque sortie.

**fiche — 27 fichiers** ([`sorties/piece-fiche.txt`](sorties/piece-fiche.txt)) :
`api/ajouts.py`, `api/avancement.py`, `api/cascade.py`, `api/cv.py`, `api/fiche.py`,
`api/lettre.py`, `api/mail.py`, `api/main.py`, `api/offers.py`,
`orchestrator/job_search/avancement.py`, `orchestrator/job_search/cv/profil.py`,
`orchestrator/job_search/cv/service.py`, `orchestrator/job_search/lettre/__init__.py`,
`orchestrator/job_search/lettre/boucle.py`, `orchestrator/job_search/lettre/jeu.py`,
`orchestrator/job_search/lettre/redaction.py`, `orchestrator/job_search/lettre/repertoire.py`,
`orchestrator/job_search/lettre/service.py`, `orchestrator/job_search/mail/generation.py`,
`orchestrator/job_search/paths.py`, `orchestrator/job_search/pdf/filename.py`,
`orchestrator/job_search/pieces.py`, `orchestrator/job_search/storage/db.py`,
`orchestrator/job_search/suivi/etats.py`, `web/app/pages/offers/[id].vue`,
`web/app/stores/offers.ts`, `web/app/stores/pieceNotifications.ts`.

**cv — 25 fichiers** ([`sorties/piece-cv.txt`](sorties/piece-cv.txt)) :
`api/ajouts.py`, `api/avancement.py`, `api/cascade.py`, `api/cv.py`, `api/fiche.py`,
`api/main.py`, `api/offers.py`, `api/pieces.py`, `api/schemas.py`,
`orchestrator/job_search/avancement.py`, `orchestrator/job_search/lettre/banc.py`,
`orchestrator/job_search/lettre/boucle.py`, `orchestrator/job_search/lettre/service.py`,
`orchestrator/job_search/mail/generation.py`, `orchestrator/job_search/paths.py`,
`orchestrator/job_search/pdf/__init__.py`, `orchestrator/job_search/pdf/coordonnees.py`,
`orchestrator/job_search/pdf/filename.py`, `orchestrator/job_search/pieces.py`,
`orchestrator/job_search/storage/db.py`, `orchestrator/job_search/suivi/etats.py`,
`orchestrator/job_search/suivi/storage.py`, `web/app/pages/offers/[id].vue`,
`web/app/stores/offers.ts`, `web/app/stores/pieceNotifications.ts`.

**lettre — 28 fichiers** ([`sorties/piece-lettre.txt`](sorties/piece-lettre.txt)) :
`api/ajouts.py`, `api/avancement.py`, `api/cascade.py`, `api/fiche.py`, `api/lettre.py`,
`api/mail.py`, `api/main.py`, `api/offers.py`, `api/pieces.py`, `api/schemas.py`,
`orchestrator/job_search/avancement.py`, `orchestrator/job_search/fiche/prompt.py`,
`orchestrator/job_search/fiche/service.py`, `orchestrator/job_search/mail/candidature.py`,
`orchestrator/job_search/mail/generation.py`, `orchestrator/job_search/paths.py`,
`orchestrator/job_search/pdf/__init__.py`, `orchestrator/job_search/pdf/coordonnees.py`,
`orchestrator/job_search/pdf/filename.py`, `orchestrator/job_search/pdf/lettre_html.py`,
`orchestrator/job_search/pieces.py`, `orchestrator/job_search/storage/db.py`,
`orchestrator/job_search/suivi/etats.py`, `orchestrator/job_search/suivi/storage.py`,
`orchestrator/job_search/tracking/lettre_tracing.py`, `web/app/pages/offers/[id].vue`,
`web/app/stores/offers.ts`, `web/app/stores/pieceNotifications.ts`.

### 17. Graphe

Commande : `.venv/bin/graphify update .` (6436 nœuds, 15 888 arêtes, 242 communautés,
314 fichiers). Lancée avant `npm ci` ; `web/node_modules` existait déjà dans le worktree
au démarrage du tour, ignoré par git. `GRAPH_REPORT.md` est recopié sous `sorties/`,
puis `graphify-out/` est supprimé.
Sorties : [`sorties/GRAPH_REPORT.md`](sorties/GRAPH_REPORT.md) et
[`sorties/graphify-console.txt`](sorties/graphify-console.txt)

Recopié tel quel :

```
## God Nodes (most connected - your core abstractions)
1. `init_db()` - 232 edges
2. `JobOffer` - 158 edges
3. `get_conn()` - 105 edges
4. `appliquer_geste()` - 71 edges
5. `run_lettre()` - 62 edges
6. `save_offer()` - 61 edges
7. `main()` - 58 edges
8. `ExtractedFacts` - 57 edges
9. `ReponseModele` - 49 edges
10. `Export — 48 offre(s)` - 49 edges
```

```
## Import Cycles
- None detected.
```

## Appréciations

Les constats ci-dessous sont ceux des relecteurs ECC (ECC 2.2.2), lancés comme
sous-agents en lecture seule, avec la consigne : au plus 15 constats sur la structure
(taille, responsabilités mélangées, couplage, duplication), chacun avec fichier:ligne,
pas de sécurité, pas de recommandation. Ils sont recopiés sans vérification de leurs
chiffres : un chiffre de cette partie n'est pas une mesure. Les comptes d'`execute`
cités par un relecteur diffèrent de ceux de la mesure 13.

### fastapi-reviewer — `api/`

1. fastapi-reviewer — `api/offers.py:469` — `list_offers` tient en une seule fonction de 326 lignes (469–795). Elle mêle SQL (ligne 701), filtres, tri et assemblage de la réponse.
2. fastapi-reviewer — `api/offers.py:701` — Le SQL de lecture des offres est écrit dans la couche des routes. Le fichier compte 1239 lignes et 24 appels `execute`, sans couche d'accès aux données.
3. fastapi-reviewer — `api/offers.py:868` — `get_offer` (868–985) fait elle-même le SELECT (ligne 874), puis un `UPDATE offers SET seen_candidat` (ligne 888) dans un GET, et construit le détail de l'offre dans la même fonction.
4. fastapi-reviewer — `api/offers.py:42` — Le profil, la table d'alias et le calcul du score sont chargés par `orchestrator` dans la couche web. `_load_scoring_context` garde un cache global de module, et `_derive_score_breakdown` (ligne 61) recalcule la désirabilité et l'atteignabilité côté API.
5. fastapi-reviewer — `api/export.py:338` — Le scoring (`compute_desirability`, `compute_attainability`) est rejoué dans le module d'export, avec des imports locaux dans la fonction. C'est la même logique de calcul qu'à `api/offers.py:61`.
6. fastapi-reviewer — `api/offers.py:1153` — Les routes de revue (`upsert_category_review`, ligne 1127) écrivent directement dans `offers` avec un `UPDATE` (ligne 1156) et un horodatage local. Elles ne passent pas par une couche de stockage.
7. fastapi-reviewer — `api/offers.py:1039` — Le contrôle d'existence `SELECT id FROM offers WHERE id = ?` est recopié avant l'écriture dans les routes de la plage 1038–1229 (lignes 1044, 1084, 1206, 1229, ...). Le même `SELECT id FROM offers` est repris par `fiche`, `lettre` et `cv`.
8. fastapi-reviewer — `api/lettre.py:1` — Le module fait 863 lignes. Il mêle routes, SQL (31 `execute`), tâches asyncio de génération (ligne 324), registre des exécutions en cours (ligne 94), assemblage du PDF (ligne 718) et lecture de versions (ligne 796).
9. fastapi-reviewer — `api/lettre.py:225` — La lecture de `fiches_entreprise` est faite dans `lettre.py` (lignes 205, 227, 360, 748), alors que la table appartient à `fiche.py`. `fiche.py` la lit aussi (lignes 137, 158, 173, 235, 263, 288), et elle est lue encore dans `avancement.py:48` et `mail.py:64`.
10. fastapi-reviewer — `api/fiche.py:31` — `fiche` importe `lettre` (`lettre_api`) alors que `lettre` lit les tables de la fiche. `pieces.py:33`, `avancement.py:35-37` et `cascade.py:20-21` importent eux aussi les modules de routes les uns des autres : des routeurs servent de bibliothèque interne, ce qui les couple entre eux.
11. fastapi-reviewer — `api/export.py:24` — Le module d'export importe des helpers privés de `api/offers.py` (module de routes). Les helpers de dérivation (étape, gestes, historique, lignes 200–447) vivent dans la couche web au lieu d'un module de service.
12. fastapi-reviewer — `api/offers.py:284` — La dérivation d'étape, de gestes permis et de pièces prêtes (`_derive_etape`, `_gestes_permis_depuis_row`, lignes 306–372) est faite dans l'API. Elle recoupe la table de transitions du module `suivi.etats` d'`orchestrator`, importé ligne 17.
13. fastapi-reviewer — `api/reference.py:21` — `reference` importe `_DOMAIN_VALID`, constante privée (préfixe `_`) de `orchestrator.job_search.scoring.extractor`. Le couplage passe par un détail interne d'une autre brique.
14. fastapi-reviewer — `api/db.py:5` — `api/db.py` tire son chemin de base depuis `orchestrator.job_search.paths`. Tous les modules de l'API importent `orchestrator` directement (une trentaine d'imports, cf. `api/cv.py:18-44`, `api/lettre.py:54-79`), sans interface intermédiaire. Le seul point d'ouverture de connexion est `get_conn`, appelé en `with` dans chaque handler.
15. fastapi-reviewer — `api/lettre.py:163` — `_now()` est dupliquée à l'identique dans `api/pieces.py:60`. Le même `datetime.now(timezone.utc).isoformat(...)` est aussi écrit en ligne dans `api/offers.py:1153`, `api/traces.py:66` et `api/ajouts.py:112`.

Le relecteur a rendu 16 constats ; le seizième (`api/cv.py:94`, conversions ligne vers
dict écrites module par module) n'est pas recopié, plafond de 15.

### python-reviewer — `orchestrator/job_search/`

1. python-reviewer — `orchestrator/job_search/lettre/boucle.py:1` — Ce fichier fait 1568 lignes. Il mêle le graphe d'états LangGraph, les nœuds, les appels à Ollama et à claude-agent-sdk, la construction des prompts et un point d'entrée en ligne de commande.
2. python-reviewer — `orchestrator/job_search/lettre/boucle.py:184` — `raison_appel_echoue` s'étend sur environ 126 lignes. C'est un gros bloc de messages d'erreur dans un module de logique de graphe.
3. python-reviewer — `orchestrator/job_search/lettre/boucle.py:1508` — `generer_lettre_boucle` exécute du SQL brut (`offers` et `fiches_entreprise`) dans le module du graphe. La lecture en base n'est pas isolée dans un fichier de stockage.
4. python-reviewer — `orchestrator/job_search/lettre/boucle.py:1552` — Le module porte son propre `main()` (la CLI) à côté de la logique de la boucle.
5. python-reviewer — `orchestrator/job_search/lettre/banc.py:846` — Ce fichier fait 930 lignes. `main` est un point d'entrée à ce niveau du module, au milieu de la préparation du jeu, du rejeu, du rapport et du suivi MLflow.
6. python-reviewer — `orchestrator/job_search/lettre/service.py:31` — Le service importe symboles et constantes depuis `lettre.boucle`. Le service (811 lignes) et la boucle (1568 lignes) sont fortement couplés.
7. python-reviewer — `orchestrator/job_search/lettre/service.py:125` — Même variante de `_now()` redéfinie dans ce module.
8. python-reviewer — `orchestrator/job_search/cv/service.py:72` — Même redéfinition de `_now()`. Elle existe aussi dans `fiche/service.py:128`, `mail/generation.py:70`, `suivi/storage.py:24` et `ajout/service.py:32`, soit six copies.
9. python-reviewer — `orchestrator/job_search/cv/service.py:147` — `run_cv` fait environ 193 lignes. Il enchaîne dans une seule fonction asynchrone l'appel du modèle, le parsing, le calcul et la persistance.
10. python-reviewer — `orchestrator/job_search/cv/service.py:341` — `apply_correction` fait environ 104 lignes. Ce service de 678 lignes mêle persistance SQL, orchestration du modèle et recalcul du profil.
11. python-reviewer — `orchestrator/job_search/run.py:228` — `main()` fait environ 479 lignes, sur un fichier de 707. Il rassemble l'analyse des arguments, le pull, le tri, la seconde passe, le digest et le suivi dans une seule fonction.
12. python-reviewer — `orchestrator/job_search/run.py:146` — `_second_pass_batches` fait environ 81 lignes. La logique de seconde passe est répartie entre `run.py` et `ingestion.py`, avec `resolve_category_second_pass`.
13. python-reviewer — `orchestrator/job_search/ingestion.py:424` — `run_tri` fait environ 131 lignes. Ce module de 692 lignes combine nettoyage de texte, extraction, catégorisation et persistance.
14. python-reviewer — `orchestrator/job_search/rescore.py:155` — Import différé de `api.view_profile.build_view_clauses`. L'orchestrateur dépend de la brique `api/`, alors que CLAUDE.md fait des deux briques des pairs autour de la base.
15. python-reviewer — `orchestrator/job_search/suivi/etats.py:227` — Ce module « Python pur » de 660 lignes cite dans ses docstrings `api/offers.py` (lignes 227, 261 et 568), signe d'une règle d'affichage partagée avec l'API et non portée uniquement par le module d'états.

### vue-reviewer — `web/app/`

1. vue-reviewer — `web/app/pages/offers/[id].vue:1` — Le fichier fait 2670 lignes. Le template va de la ligne 1 à 1259 et le script de 1261 à 2670, dans un seul composant de page.
2. vue-reviewer — `web/app/pages/offers/[id].vue:1270` — La page mêle sept domaines (offre, fiche entreprise, CV, lettre, mail, suivi d'envoi, aperçus). Chacun a son état local (`ref`), ses chargements, son polling et ses actions. Aucun n'est extrait en composable ni en sous-composant.
3. vue-reviewer — `web/app/pages/offers/[id].vue:1291` — La page appelle `$fetch` avec `config.public.apiBase` à la main, une trentaine de fois. Elle ne passe par aucun store ni couche d'accès à l'API. Les stores Pinia n'en portent que les offres, les ajouts, les traces et les notifications.
4. vue-reviewer — `web/app/pages/offers/[id].vue:1397` — Cinq mécanismes de polling écrits à la main, chacun avec son timer, son start et son stop : fiche (1397), avancement (1634), CV (1999), lettre (2311) et les copies temporisées (1916, 2209). Le cycle de vie est nettoyé à la main dans `onBeforeUnmount` (1296).
5. vue-reviewer — `web/app/pages/offers/[id].vue:1288` — Le `onMounted` enchaîne séquentiellement une dizaine de chargements dépendants et le démarrage des pollings. L'orchestration de l'initialisation vit dans la page.
6. vue-reviewer — `web/app/pages/offers/[id].vue:1544` — `cardBadge` et `cardPreview` (1568) calculent libellés et classes d'état des cartes en croisant fiche, pièces, avancement et CV, par comparaison de titres de cartes en chaîne. C'est de la logique d'état d'affichage dans la page.
7. vue-reviewer — `web/app/pages/offers/[id].vue:1789` — `stepActive` apparie des libellés (`ETAPE_CANDIDATURE_LABELS`, 1771) avec `etapes_acquises` pour décider de l'étape active. Le front reconstruit une correspondance code→libellé→étape que l'API fournit déjà sous forme de codes.
8. vue-reviewer — `web/app/pages/offers/[id].vue:1280` — `ficheAvertissement` fabrique des phrases d'avertissement à partir de `mode` et `employeur_confiance`. Les règles métier sont dans la page, pas fournies par l'API.
9. vue-reviewer — `web/app/pages/offers/[id].vue:2631` — `ownedTechs` et `missingTechs` recroisent `techs_matched` et `techs_missing` avec `extracted_facts.techs_required`. C'est un recouvrement de listes calculé dans le composant, ensuite passé en props à `OfferSidePanel`.
10. vue-reviewer — `web/app/pages/offers/[id].vue:2658` — `categoryLabel` et `categoryBadgeClass` (2662) dupliquent `CATEGORY_LABELS`, `categoryLabel` et `categoryBadgeClass` de `web/app/components/OfferDetail.vue:567-579`. Une troisième variante, avec des libellés différents, est dans `OffersTable.vue:249`.
11. vue-reviewer — `web/app/components/OfferSidePanel.vue:46` — `techBadgeClass` est copiée à l'identique depuis `pages/offers/[id].vue:2643` et `components/OfferDetail.vue:588`. Trois exemplaires du même mapping importance→classes.
12. vue-reviewer — `web/app/components/OfferDetail.vue:1` — Le composant fait 594 lignes. Il mêle l'affichage de l'offre, le formulaire d'écartement (470), la revue de catégorie, la sauvegarde (380) et les appels de store suivis d'un `fetchOffers()` puis d'un `emit('close')`.
13. vue-reviewer — `web/app/pages/offers/[id].vue:1981` — `formatDateFr` et `formatDateHeure` (1986) sont locaux à la page. D'autres formateurs de date sont réimplémentés ailleurs : `traces.vue:328` (`fmtTs`), `NotificationsPanel.vue:83`, et les `slice(0, 10)` de `OffersTable.vue:160`, `OfferDetail.vue:33` et `[id].vue:193`.
14. vue-reviewer — `web/app/pages/offers/[id].vue:1599` — Quatre extracteurs de message d'erreur d'API coexistent : `errorDetail` (1599), `messageErreurCv` (2085), `messageErreurLettre` (2333), `OfferDetail.vue:400` (`extractDetail`) et `stores/ajouts.ts:220` (`messageErreur`).
15. vue-reviewer — `web/app/stores/offers.ts:5` — Le store `offers` (592 lignes) regroupe les types du domaine, la liste, le détail, les verdicts, les revues de catégorie, les compteurs de traces et de suivi, et les filtres de vue. Les types de la fiche entreprise (115-129) y sont mêlés à ceux des offres.

Le relecteur a rendu 17 constats ; les deux derniers (`web/app/pages/reference.vue:146`,
`web/app/stores/ajouts.ts:65`) ne sont pas recopiés, plafond de 15.

## Hypothèse de Grégoire

H3, citée de la fiche EXE-203 : « Hypothèse de Grégoire, dite le 28 octobre 2026 : il
manque un vrai backend qui tienne la structure et les états ; le code doit permettre
d'ajouter ou de retirer une brique facilement. Le rapport ne la tranche pas
(critère 19) : l'arbitrage est humain. »

Mesures qui la touchent :

- « un vrai backend qui tienne la structure et les états » : mesures 12 (couches),
  13 (base par couche), 14 (routes et accès à la base), 17 (nœuds les plus reliés),
  et 4, 6, 8 pour la taille et la complexité de `api/offers.py` et `api/lettre.py`.
- « ajouter ou retirer une brique facilement » : mesures 15 (sources nommées hors de
  leur dossier), 16 (pièces nommées hors de leur dossier), 12 et 17 (dépendances entre
  briques), 9 (clones entre modules).

Ce rapport ne dit pas si l'hypothèse est vraie.
