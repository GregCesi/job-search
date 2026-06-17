# IMPLEMENTATION — Chantier HTML→Markdown : nettoyage dans l'adapter Remotive

> Mode **augment**. Devient le document de travail courant.
> L'ancien (`IMPLEMENTATION-chantier-bouton-trace.md`) est archivé dans `.claude/state/_archive/`, NON écrasé en place.
> Le `.claude/` structurel (rules, commands, settings) n'est PAS régénéré.
> Invariants `architecture.md` à respecter : §1 (le HTML est un format source-spécifique — il NE franchit JAMAIS la frontière de l'adapter), §4 (0 LLM — nettoyage Python pur à l'ingestion ; aucun appel modèle nulle part), §Persistance (offers/verdicts/human_reviews jamais fusionnées — on ajoute une colonne donnée sur `offers`, on ne touche à aucune table d'interaction).

## Vue d'ensemble

La source Remotive renvoie une `description` en HTML brut (balises + CSS inline + classes Google `OOyDTc`/`ejCXj` + pixel de tracking `<img src="...track...blank.gif">`). Aujourd'hui cette `description` est persistée telle quelle et lue brute partout : par le viewer (`OfferDetail.vue`), illisible à l'œil, et par l'extraction LLM (`extract_facts`), où le balisage est du **context rot** (tokens parasites au sens Wyss) qui dégrade l'extraction.

Ce chantier fait **une seule chose** : chaque adapter garantit que `JobOffer.description` sort en **Markdown propre**. Le bruit spécifique à une source meurt dans son adapter ; l'aval (DB, extraction, viewer) ne voit que du Markdown homogène, quelle que soit la source. Le HTML brut est **conservé** dans une colonne `description_raw` (source de vérité immuable), pour pouvoir auditer la conversion et la rejouer si la fonction de nettoyage s'améliore.

**Principe directeur (tranché en chat) :** *le nettoyage est spécifique à la source, la cible est universelle.* Il n'existe PAS une fonction de nettoyage générique appliquée partout — France Travail renvoie déjà du texte à peu près propre, le nettoyer comme du HTML l'abîmerait. Chaque `Source` nettoie SON bruit vers une cible partagée (Markdown).

**Première phase à attaquer : Phase 0 — lecture de l'état réel.** Trois hypothèses du cadrage ne se confirment qu'en lisant le repo. Rien ne se code avant.

---

## Invariant du chantier (non négociable)

**`description_raw` EST LA SOURCE DE VÉRITÉ. `description` EST UN DÉRIVÉ RÉGÉNÉRABLE.** Le HTML brut entre une fois (à l'ingestion), n'est jamais réécrit. Le Markdown propre se recalcule depuis le brut — c'est de la dérivation déterministe (la source ne bouge pas), pas du jugement réversible.

- **Le HTML ne franchit jamais la frontière de l'adapter (§1).** Si on se surprend à laisser une balise transiter dans le pipeline aval, ou à mettre un `html_to_markdown()` générique APRÈS la frontière adapter (dédup/scoring/persistance), l'invariant §1 est violé — stop. La conversion est DANS l'adapter, avant le mapping → `JobOffer`.
- **Brut conservé, propre dérivé.** On ne jette jamais le HTML. Raison gravée par l'expérience troncature `[:1500]` : on juge une transformation par comparaison entrée/sortie, jamais dans l'absolu. Sans le brut, la conversion est inauditable (« comment je sais qu'il a été bien enlevé ? » — l'objection de Grégoire est exactement l'argument pour garder le brut).
- **0 LLM (§4).** `html2text` est du Python pur. Aucun appel modèle pour nettoyer, nulle part.
- **Pas de filtre générique destructeur.** Une source dont la description est déjà propre (France Travail) ne passe PAS par la conversion HTML — son adapter fait au plus un `.strip()`/collapse de sauts de ligne. Imposer `html2text` à du texte plat n'abîme en pratique pas grand-chose, mais le principe reste : chaque adapter décide de SON nettoyage.

---

## Décisions de cadrage (prises en chat, gravées ici)

| Décision | Valeur tranchée | Raison | Écarté |
|---|---|---|---|
| Format cible | **Markdown** via `html2text` | Conserve titres (`**…**`) + listes (`-`), scannable à l'œil ; un LLM le digère mieux que du HTML | Texte plat `get_text()` (écrase la hiérarchie de l'offre) ; `v-html` du HTML brut (XSS sur source tierce + garde le bruit) |
| Stockage | **`description_raw` (HTML brut) + `description` (Markdown dérivé)** | Auditabilité de la conversion, réversibilité si `html2text` rate un cas | Écraser `description` (trou noir d'audit, impossible de rejouer) |
| Emplacement du nettoyage | **Dans l'adapter, par source** | §1 : le bruit source-spécifique meurt dans l'adapter, cible universelle en sortie | Passe générique en aval (fait fuiter le HTML hors de l'adapter, viole §1) |
| Rendu front | **Composant Markdown Nuxt** (`@nuxtjs/mdc` candidat) | Sinon les `**`/`-` s'affichent en toutes lettres, pire que du texte plat | `<pre>` brut (annule le bénéfice du Markdown) |

---

## Calage sur l'existant (à VÉRIFIER en Phase 0 — NON négociable)

Faits du repo à confirmer dans le code réel avant d'écrire la moindre ligne :

- **`RemotiveSource` existe** (`sources/remotive.py`, livré 2026-06-16). Localiser le point exact du mapping payload Remotive → `JobOffer` où `description` est affectée. C'est LE point d'insertion de la conversion + de la capture du brut.
- **Le bruit est-il isolé à `description` ?** Vérifier si `title`/`company` peuvent aussi porter du HTML selon Remotive. Si isolé → chantier `S`. Sinon le nettoyage de l'adapter s'élargit (mais reste dans l'adapter).
- **`JobOffer` (schéma neutre, §1)** : ajouter `description_raw: str | None`. Confirmer qu'aucun consommateur aval ne casse sur un champ ajouté (ajout, pas retrait → safe). Le mapping de CHAQUE source devra peupler `description_raw` (pour Remotive = le HTML d'origine ; pour France Travail = la description native telle quelle, qui fait déjà office de « brut »).
- **Migration SQLite** : pattern maison `ADD COLUMN IF NOT EXISTS` / check existence, idempotent, appelé au module-load (cf. `db.py`, chantiers précédents). Pas d'Alembic. Colonne `description_raw` sur `offers`.
- **Migration des données existantes (~134 offres)** : elles n'ont PAS de `description_raw`. Décision sûre (à confirmer en Phase 0) : pour les anciennes, **traiter l'actuel `description` comme le `raw`** (il contient déjà du HTML pour les offres Remotive, du texte pour FT) et **dériver le Markdown par-dessus** via une passe one-shot. Aucune perte, aucun re-pull (offres expirées préservées). Re-puller serait fragile (offres disparues côté source).
- **Le front lit `description` où ?** `OfferDetail.vue` l'affiche (cf. chantiers traces/review). Confirmer le composant/binding exact à remplacer par le rendu Markdown.
- **`@nuxtjs/mdc` ou `marked`+sanitize ?** Vérifier ce qui est déjà présent dans `web/package.json`. Si rien, `@nuxtjs/mdc` est le choix Nuxt-natif. Décision finale en L (front).

> Note de méthode : la Phase 0 distingue ce chantier `S` d'un `M`. Si le bruit est isolé à `description` et que le point d'insertion adapter est net, le code utile tient en ~5-6 livrables. Lire d'abord.

---

## Schémas cibles

> À affiner au moment du livrable correspondant — base de travail, pas contrat figé.
> Toute évolution d'un schéma cible ou de `architecture.md` = validation humaine explicite avant code (`rules/workflow.md`).

### `JobOffer` — champ ajouté (schéma neutre, §1)

```python
class JobOffer(BaseModel):
    # ... champs existants inchangés ...
    description: str                       # CHANGÉ de sémantique : désormais Markdown propre (dérivé)
    description_raw: str | None = None     # NOUVEAU — contenu source brut (HTML pour Remotive),
                                           # source de vérité immuable, jamais relu par viewer/LLM
```

> `description` garde son nom et son type (pas de cascade de renommage dans tout l'aval) ; seule sa **garantie** change : c'est maintenant du Markdown propre. `description_raw` est le nouveau réceptacle du brut. Chaque adapter peuple les deux.

### Fonction de conversion partagée (cible universelle, appelée PAR les adapters)

```python
# Vit dans un module utilitaire partagé (ex. sources/_clean.py ou utils/), PAS dans le pipeline aval.
# C'est un OUTIL que les adapters appellent, pas une étape de pipeline générique.
def html_to_markdown(raw: str) -> str:
    """HTML brut -> Markdown propre. Supprime le tracking pixel et le balisage parasite.
    Python pur, 0 LLM. Idempotent sur du texte déjà propre (à vérifier)."""
    ...
```

Points de conception :
- **Tracking pixel** (`<img src="...blank.gif?source=public_api">`) : c'est de la surveillance, pas du contenu → supprimé explicitement, pas juste délesté de ses balises.
- **`html2text`** configuré pour : garder titres en `**gras**`, listes en `-`, ignorer les images (`ignore_images=True` couvre le pixel + toute image décorative), pas de wrapping de ligne artificiel (`body_width=0`).
- L'adapter Remotive appelle `html_to_markdown(payload_html)`. L'adapter France Travail N'appelle PAS cette fonction (son texte est déjà propre — au plus un `.strip()`).

### Migration SQLite

```sql
-- idempotent (check existence colonne avant ADD), appelée au module-load comme l'existant
ALTER TABLE offers ADD COLUMN description_raw TEXT;   -- nullable, NULL pour les offres pré-migration jusqu'au backfill
```

---

## Phases

### Phase 0 — Lecture de l'état réel (0 écriture)
Objectif : confirmer le point d'insertion adapter, l'isolation du bruit à `description`, le pattern migration, le binding front. Aucune modification de fichier.

- [x] L0 — Note de lecture (6-8 lignes) répondant, chemins + n° de ligne réels : (a) **point exact** du mapping Remotive → `JobOffer` où `description` est affectée (`sources/remotive.py`) ; (b) **le bruit est-il isolé à `description`** ou `title`/`company` en portent-ils aussi ? ; (c) **pattern de migration** confirmé (où vivent les `ADD COLUMN IF NOT EXISTS`, comment appelés) ; (d) **binding front** exact qui affiche `description` dans `OfferDetail.vue` ; (e) **dépendance Markdown** déjà présente dans `web/package.json` ou à ajouter ? ; (f) **les ~134 offres** : `description` actuelle = bien le brut récupérable comme `description_raw` pour le backfill ?

```
✋ Verify before continuing:
- [ ] Réponses tranchées (a)-(f), chemins + lignes réels
- [ ] Verdict : bruit isolé à `description` (chantier S) OU élargi à d'autres champs (préciser)
- [ ] Stratégie backfill confirmée : actuel `description` → `description_raw`, Markdown dérivé par-dessus
- [ ] Aucun fichier modifié

Si tout OK : "go". Sinon dis ce qui cloche.
```

### Phase 1 — Fonction de conversion partagée (testée isolément, AVANT de toucher l'adapter)
Objectif : `html_to_markdown` propre, testée sur l'offre réelle du chantier, AVANT toute intégration.

- [x] L1 — Ajouter `html2text` aux dépendances (`requirements.txt`). Créer `html_to_markdown(raw)` dans un module utilitaire partagé (emplacement tranché en L1 selon Phase 0 — `sources/_clean.py` pressenti). Config : `ignore_images=True`, `body_width=0`, gras/listes conservés. Suppression explicite du tracking pixel si `ignore_images` ne suffit pas.
- [x] L2 — Tests unitaires sur l'échantillon réel (l'offre « Assistant Accounts Payable » du chantier) + 2-3 autres descriptions Remotive : titres `**…**` présents, listes `-` présentes, AUCUNE balise résiduelle, AUCUN `blank.gif`, AUCUNE classe `OOyDTc`/`ejCXj`. Vérifier l'idempotence sur du texte déjà propre (entrée FT-like → sortie ≈ identique, pas d'explosion).

```
✋ Verify before continuing:
- [ ] L'offre HTML du chantier ressort en Markdown lisible (titres, listes, zéro balise, zéro pixel)
- [ ] Idempotent / inoffensif sur du texte déjà propre
- [ ] Fonction Python pure, 0 LLM, 0 dépendance réseau
- [ ] Module placé hors du pipeline aval (c'est un outil d'adapter, pas une étape générique)

Si tout OK : "go". Sinon dis ce qui cloche.
```

### Phase 2 — Schéma `JobOffer` + intégration adapter Remotive
Objectif : Remotive produit `description` (Markdown) + `description_raw` (HTML). Le HTML meurt dans l'adapter.

- [x] L3 — `JobOffer` : ajouter `description_raw: str | None = None`. Vérifier qu'aucun consommateur aval ne casse (champ ajouté → safe).
- [x] L4 — `RemotiveSource` : au point de mapping, `description_raw = payload_html` (verbatim) et `description = html_to_markdown(payload_html)`. Le HTML n'apparaît plus nulle part ailleurs que dans `description_raw`.
- [x] L5 — `FranceTravailSource` : peupler `description_raw` avec la description native telle quelle (elle fait office de brut). `description` reste sa valeur actuelle (au plus `.strip()`/collapse — PAS de passage `html2text`). Garantit que TOUTE source remplit le contrat `{description Markdown/propre, description_raw brut}`.

```
✋ Verify before continuing:
- [ ] Un fetch Remotive : description = Markdown propre, description_raw = HTML d'origine intact
- [ ] Aucune balise HTML ne sort de RemotiveSource dans `description`
- [ ] FranceTravailSource peuple description_raw, description inchangée (texte propre, pas dégradé par html2text)
- [ ] 0 appel LLM (§1 + §4 respectés)

Si tout OK : "go". Sinon dis ce qui cloche.
```

### Phase 3 — Migration SQLite + persistance + backfill
Objectif : la colonne existe, les nouvelles offres la peuplent, les ~134 anciennes sont rétro-dérivées.

- [x] L6 — Migration idempotente `ADD COLUMN description_raw` sur `offers` (pattern maison, check existence, module-load). Persistance (`save_offer` / écriture run) écrit `description_raw` ET `description`.
- [x] L7 — Script de backfill one-shot (racine, hors package prod, façon `replay_traces.py`) : pour chaque offre existante, `description_raw = description actuelle` (le brut récupérable), puis `description = html_to_markdown(description_raw)`. **N'appelle aucun LLM, ne re-pull aucune source.** Idempotent (ré-exécutable sans double conversion — détecter via présence de balises ou flag). Arg `--dry-run` pour inspecter avant d'écrire.

```
✋ Verify before continuing:
- [ ] Migration tourne deux fois de suite sans erreur (idempotente)
- [ ] Une nouvelle offre Remotive ingérée a description (MD) + description_raw (HTML) en base
- [ ] Backfill --dry-run montre la conversion attendue sur quelques offres Remotive anciennes
- [ ] Backfill réel : les offres Remotive anciennes ont un Markdown propre ; les FT anciennes ne sont pas dégradées
- [ ] verdicts / human_reviews / criteria_json / colonnes review strictement intacts
- [ ] 0 appel LLM, 0 re-pull source

Si tout OK : "go". Sinon dis ce qui cloche.
```

### Phase 4 — Rendu Markdown front
Objectif : `OfferDetail.vue` rend `description` en Markdown lisible (plus de balises ni de `**`/`-` en clair).

- [x] L8 — Ajouter le rendu Markdown côté Nuxt (`@nuxtjs/mdc` si absent, sinon réutiliser l'existant). Remplacer le binding brut de `description` dans `OfferDetail.vue` par le composant de rendu Markdown. Le viewer lit TOUJOURS `description` (le propre), JAMAIS `description_raw`.

```
✋ Verify before continuing:
- [ ] Une offre Remotive s'affiche en Markdown rendu (titres en gras, listes à puces), zéro balise, zéro `**` littéral
- [ ] Une offre France Travail s'affiche correctement (texte propre, pas cassé par le rendu MD)
- [ ] description_raw n'est jamais affiché à l'utilisateur (réservé audit/debug)
- [ ] L'eval humaine d'une offre est désormais lisible (objectif du chantier atteint)

Si tout OK : "go". Sinon dis ce qui cloche.
```

### Phase 5 — Clôture
Objectif : non-régression légère + fermeture propre.

- [x] L9 — `/handoff` : IMPLEMENTATION coché, STATE/JOURNAL/DECISIONS à jour, `IMPLEMENTATION-chantier-bouton-trace.md` archivé dans `_archive/`.

```
✋ Verify before continuing:
- [ ] GET /offers et GET /offers/{id} répondent (API non régressée)
- [ ] L'extraction sur une prochaine ingestion Remotive recevra du Markdown propre (vérifiable via une trace : prompt_user sans balises)
- [ ] DECISIONS.md : nettoyage par-source/cible-universelle (§1), description_raw brut + description dérivé, html2text, rendu MD Nuxt — tracés
- [ ] IMPLEMENTATION-chantier-bouton-trace.md déplacé dans _archive/

Si tout OK : "go". Sinon dis ce qui cloche.
```

---

## Livrables détaillés

1. **L0 — Note de lecture Phase 0** — point d'insertion adapter, isolation du bruit, pattern migration, binding front, dépendance MD, backfill confirmé. `XS`
2. **L1 — `html_to_markdown` + dépendance** — `html2text`, config gras/listes/no-image/no-wrap, module hors pipeline aval. `S`
3. **L2 — Tests conversion** — sur l'offre réelle + échantillon, zéro balise/pixel, idempotence sur texte propre. `S`
4. **L3 — `JobOffer.description_raw`** — champ ajouté au schéma neutre, aval non cassé. `XS`
5. **L4 — Intégration RemotiveSource** — description = MD, description_raw = HTML, HTML mort dans l'adapter. `S`
6. **L5 — FranceTravailSource peuple description_raw** — contrat uniforme toutes sources, pas de html2text sur FT. `S`
7. **L6 — Migration + persistance** — colonne idempotente, écriture des deux champs. `S`
8. **L7 — Backfill one-shot** — 134 offres rétro-dérivées, 0 LLM, 0 re-pull, --dry-run, idempotent. `M`
9. **L8 — Rendu Markdown front** — composant MD dans OfferDetail.vue, lit description, jamais le raw. `M`
10. **L9 — Handoff & archivage** — state à jour, bouton-trace archivé. `XS`

---

## Dépendances critiques

- L0 bloque tout : si le bruit n'est PAS isolé à `description` (b), L4/L5 s'élargissent ; si le backfill (f) ne peut pas réutiliser l'actuel `description` comme brut, L7 change de forme.
- L1 bloque L2 (les tests valident la fonction) et L4/L5/L7 (tous appellent la fonction).
- L3 bloque L4/L5 (le mapping écrit un champ qui doit exister au schéma).
- L6 bloque L7 (pas de backfill sans colonne) et la persistance des nouvelles offres.
- L4 (Remotive produit du MD) bloque la valeur de L8 côté Remotive ; L8 indépendant du backend pour le câblage mais n'a de sens visuel qu'avec du MD en base.

Chemin critique : `L0 → L1 → L3 → L4 → L6 → L7 → L8`.

---

## Hors-scope — explicitement reporté

- **Correction des autres défauts d'extraction** (few-shot mid-prompt, fallback silencieux, troncature `[:8000]`) — ce chantier nettoie l'ENTRÉE de l'extraction (retire le bruit HTML), il ne touche PAS le prompt ni le parsing. Si on se surprend à modifier le prompt d'`extract_facts` → hors-scope, stop. (Le bénéfice extraction est un effet de bord gratuit du nettoyage, pas un objectif à poursuivre activement ici.)
- **Re-extraction LLM des 134 offres** sur les nouvelles descriptions propres — séparé. Le backfill ne fait QUE re-dériver le Markdown (Python pur). Re-lancer `extract_facts` sur les descriptions nettoyées (pour mesurer le gain Wyss) est un chantier d'observation distinct, décidé après coup. Ne PAS l'embarquer ici (rouvrirait §4 au volume).
- **Normalisation d'autres champs** (dates, salaires, types de contrat hétérogènes entre sources) — autre sujet, autre chantier. Ici : `description` uniquement.
- **3e source / nouvel adapter** — hors sujet. Le contrat « chaque adapter nettoie son bruit vers Markdown » est posé pour que le prochain adapter l'hérite, mais aucun nouvel adapter n'est créé ici.

---

## Garde-fous

- **HTML mort dans l'adapter (§1)** : si une balise HTML apparaît dans `description` en aval de l'adapter, ou si un `html_to_markdown` générique est branché APRÈS la frontière adapter (dédup/scoring/persistance) → §1 violé, stop. La conversion est DANS l'adapter.
- **Brut jamais jeté** : si on se surprend à écraser `description` sans conserver `description_raw`, ou à supprimer `description_raw` « parce que le HTML est inutile » → on se rend aveugle à sa propre conversion (cf. troncature `[:1500]`), stop. Le brut reste.
- **`description` Markdown, `description_raw` brut — jamais inversés** : le viewer et le LLM lisent `description` (propre). `description_raw` ne sort que pour l'audit/debug. Si un consommateur produit lit `description_raw` → erreur, stop.
- **Pas de html2text sur source déjà propre** : si on se surprend à passer la description France Travail dans `html_to_markdown` « par symétrie » → on risque d'abîmer du texte propre, stop. Chaque adapter nettoie SON bruit ; FT n'a pas de bruit HTML.
- **0 LLM (§4)** : tout le chantier est Python pur (conversion) + migration + front. Aucun appel modèle. Si le backfill veut « ré-extraire pour profiter du texte propre » → hors-scope, frontière violée, stop.
- **Backfill non destructif** : `--dry-run` d'abord. Le backfill ne re-pull aucune source (offres expirées préservées), ne touche aucune table d'interaction. Idempotent.
- **Schéma cible / architecture.md** : toute évolution = validation humaine explicite avant code (`rules/workflow.md`).
