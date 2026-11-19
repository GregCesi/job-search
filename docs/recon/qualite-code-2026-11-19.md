Relevé du 19 novembre 2026, sur `main` à `59f0df8`. Complément du rapport du 28 octobre 2026 (`qualite-code.md`, mesuré sur `cfc1d41`). Ticket : TCK-364. Commandes tapées par Grégoire dans son terminal, sauf mention contraire.

Ce rapport ne recopie pas celui du 28 octobre. Il dit ce qui a changé depuis, et pourquoi le reste vaut toujours.

## Mesures

### 1. Validité des mesures du 28 octobre

Commande : `git diff --stat cfc1d41 main -- api orchestrator web/app profiles`
Sortie : vide.

Le code de l'application n'a pas changé entre `cfc1d41` et `main`. Les deux commits intermédiaires sont `b76cab3` (le rapport) et `59f0df8` (le cliquet de la barre).

Reproduction de trois mesures du rapport du 28 octobre, sur `main` :

| Mesure du 28 octobre | Commande | Résultat le 19 novembre |
| --- | --- | --- |
| 4. Taille | `git ls-files '*.py' '*.vue' '*.ts' \| xargs wc -l \| grep -v ' total$' \| sort -rn \| head -20 \| diff -w - docs/recon/sorties/taille-top20.txt && echo IDENTIQUE` | `IDENTIQUE` |
| 7. Complexité moyenne | `.venv/bin/radon cc -s -a api orchestrator \| tail -1` | `Average complexity: A (3.970959595959596)` |
| 9. Duplication | `npx -y jscpd@5.4.2 api orchestrator web/app --min-lines 6 --reporters console \| grep -E 'Total\|Found'` | 144 fichiers, 30188 lignes, 28 clones, 357 lignes dupliquées (1.18%) |

### 2. Branches

Avant nettoyage (relevé par le chat à l'ouverture du ticket, `integration/jet-52` checkoutée) :

| | Local | origin |
| --- | --- | --- |
| Total (`git branch \| wc -l`, `git branch -r \| wc -l`) | 56 | 55 |
| Fusionnées (`git branch --merged main \| wc -l`, `git branch -r --merged origin/main \| wc -l`) | 49 | 49 |
| Non fusionnées (`git branch --no-merged main`, `git branch -r --no-merged origin/main`) | 7 | 6 |

Gestes :

- 48 branches locales fusionnées supprimées : `git branch --merged main | grep -v 'main$' | xargs git branch -d`.
- 47 branches distantes fusionnées supprimées : `git branch -r --merged origin/main | grep 'origin/integration/' | sed 's#origin/##' | xargs git push origin --delete`.
- 6 branches `arret/` supprimées (dont `arret/jet-18/EXE-117`, locale seulement), après vérification que chaque fiche a son commit dans `main` : `for n in 99 106 108 117 198 67; do echo "== EXE-$n"; git log --oneline main -E --grep="EXE-$n([^0-9]|$)"; done`. Commits trouvés : a4e0b89 (EXE-99), 213a5f7 (EXE-106), c84a4dd (EXE-108), 22426cc (EXE-117), cb2f51e (EXE-198), 56ea59d (EXE-67).

Après (`git branch`, `git branch -r`) :

| Local | origin |
| --- | --- |
| `main`, `integration/jet-52` | `origin/HEAD -> origin/main`, `origin/main`, `origin/integration/jet-52` |

`integration/jet-52` (EXE-205, commit f2e696e du 2 novembre) est gardée, non fusionnée.

### 3. Code mort

Python, commande : `.venv/bin/vulture api orchestrator --min-confidence 80`. 6 lignes, identiques au 28 octobre.

Front, commande (dans `web/`) : `npx -y knip@6.43.0 --no-progress`. 1 fichier, 2 dépendances, 17 types exportés, identiques au 28 octobre.

| Signalé | Où | Verdict | Motif |
| --- | --- | --- | --- |
| `unused variable 'cls'` × 6 | `api/ajouts.py:47`, `:52`, `api/offers.py:1034`, `api/pieces.py:56`, `api/reference.py:37`, `orchestrator/job_search/sources/base.py:43` | faux positif, gardé | premier paramètre d'un `@classmethod` exigé par `@field_validator` / `@model_validator` de Pydantic ; lignes 47 et 43 lues, les 4 autres portent le même nom |
| fichier `tailwind.config.ts` | `web/` | faux positif, gardé | chargé par convention de nom par le module `@nuxtjs/tailwindcss` déclaré dans `nuxt.config.ts` |
| dépendance `@tailwindcss/typography` | `web/package.json:15` | faux positif, gardé | importée par `tailwind.config.ts` ; fournit les classes `prose` (`grep -rn "prose" app` : 3 composants) |
| dépendance `vue-router` | `web/package.json:21` | retirable | jamais importée par le projet ; Nuxt la déclare dans ses propres dépendances, même plage `^5.0.7` |
| 17 types exportés | 15 dans `web/app/stores/offers.ts`, 1 dans `pieceNotifications.ts`, 1 dans `traces.ts` | retirable | le type sert dans son fichier, seul le mot `export` est en trop ; sans effet à l'exécution |

Retrait différé, décision de Grégoire : porté par TCK-374.

### 4. Barre sur `main`

Commande : `bash scripts/barre.sh 2>&1 | grep -E '^[1-7] |^BARRE|-->'`

| # | Critère | Résultat |
| --- | --- | --- |
| 1 | `ruff check` | rouge, 19 constats |
| 2 | `ruff format --check` | rouge, 4 fichiers sur 199 |
| 3 | `python -m pytest` | vert, 1424 passés |
| 4 | aucun TODO / FIXME / XXX introduit | vert |
| 5 | web : `npm ci` + `npm run build` | vert |
| 6 | reconstructibilité | vert |
| 7 | cliquet + contrats de couches | vert, `execute` hors stockage 190/190 |

Les constats des critères 1 et 2 sont tous dans `experiment_tck200.py`, `experiment_tck206.py`, `experiment_tck206_cv.py` et `experiment_tck210.py`, à la racine, ajoutés par `dc3214a` du 28 septembre.

Base retenue par la barre : `97fabfb` du 22 septembre, première entrée du reflog de `main`. La barre ne contrôle que les fichiers changés depuis sa base ; sur une branche de jet, ces 4 scripts ne le sont pas.

## Appréciations

- Le dépôt a peu de code mort : sur 26 signalements, 1 dépendance en doublon et 17 mots `export` en trop. Les 8 autres sont des faux positifs d'analyse statique, que l'outil ne peut pas trancher seul (conventions de Nuxt et de Pydantic).
- Les mesures du 28 octobre se reproduisent à l'identique sur trois commandes relancées par Grégoire.
- Ce qui est commité hors de la boucle échappe à la barre : les 4 scripts `experiment_*` n'avaient jamais été contrôlés. Leur sort (formater ou retirer) est porté par TCK-374.
