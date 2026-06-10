# IMPLEMENTATION — Chantier traces viewer : page /traces + notes + retrait du faux-juge

> Mode **augment**. Devient le document de travail courant.
> L'ancien (`IMPLEMENTATION-chantier-2.md`) est archivé dans `.claude/state/_archive/`, NON écrasé en place.
> Le `.claude/` structurel (rules, commands, settings) n'est PAS régénéré.
> Invariants `architecture.md` à respecter : §4 (0 LLM au recalcul — ce chantier n'appelle JAMAIS de LLM), §Persistance (offers/verdicts/human_reviews jamais fusionnées — `trace_notes` devient une 4ᵉ table d'interaction au même statut).

## Vue d'ensemble

Le seul appel LLM actif du pipeline (`extract_facts`) produit des traces JSONL (`data/traces/extract_facts.jsonl`, schéma `LLMTrace` 9 champs) — instrumentées au chantier traces du 9 juin. Aujourd'hui elles sont **illisibles à la main** : `prompt_user` sérialisé en une ligne avec `\n` échappés, les 3 blocs (entrée Wyss / sortie Husain / métadonnées) collés. On ajoute une **page `/traces` dédiée** pour les lire et faire de l'error analysis sur le **prompt d'extraction**.

C'est un **outil d'audit**, séparé de l'outil produit (consultation/scoring des offres). Deux étages d'audit coexistent désormais sans se confondre : `human_reviews` audite le **scoring** (Python par-dessus les faits) ; `/traces` audite l'**extraction LLM** (l'amont qui nourrit le scoring).

Le chantier ajoute aussi un espace de **notes** d'error analysis (annotation humaine par trace, persistée) et **retire** un faux-juge de la page offre.

**Première phase à attaquer : Phase 1 (route API `GET /traces`).** Le front en dépend ; rien ne s'affiche avant qu'une route serve le `.jsonl` dé-échappé.

---

## Invariant du chantier (non négociable)

**LE VIEWER LIT, NE JUGE PAS.** Aucun détecteur automatique de défaut, aucun LLM-judge, aucun scoring de qualité, aucune déduplication de traces. La route et la page dé-échappent, séparent, affichent. Point.

- La seule évaluation qui entre est celle que **Grégoire écrit à la main** dans le champ note — c'est de l'error analysis humaine, pas un jugement machine.
- **Pas de déduplication** : 3 offres ont 2 traces (replay seeds différents). Les deux traces sont conservées et affichées — leur variance sur une entrée identique est le signal d'error analysis, le masquer serait déjà juger.
- Le `.jsonl` est **lu, jamais muté** (c'est le log brut de l'orchestrateur, sacré). Les notes vont dans une table SQLite séparée `trace_notes`, même statut que `seen`/`verdicts`/`human_reviews`.
- **0 appel LLM** sur tout le chantier (§4). Une route qui lit un fichier et une page qui l'affiche n'invoquent pas de modèle.

---

## Calage sur l'existant (lu dans le repo — reconnaissance Claude Code)

Faits du repo qui conditionnent le plan. À respecter :

- **`data/traces/extract_facts.jsonl`** : 23 lignes, 20 `offer_id` distincts (3 offres à 2 traces). Schéma `LLMTrace` 9 champs confirmé : `offer_id, model, temperature, prompt_system, prompt_user, raw_response, parsed_facts, parse_failed, timestamp`.
- **Chemin du `.jsonl`** : `tracing.py` le résout depuis le **CWD** (`Path("data/traces/...")`, fragile). La route API **ne touche pas** `tracing.py` (code orchestrateur, hors scope) — elle résout le chemin **depuis `__file__`** comme `api/db.py` le fait déjà (`Path(__file__).parent.parent / "data" / "traces" / "extract_facts.jsonl"`).
- **API** : `api/main.py` (app + CORS + montage routers), `api/offers.py` (offres/verdicts/reviews), `api/export.py` (markdown), `api/db.py` (connexion SQLite résolue depuis `__file__`), `api/schemas.py` (Pydantic). Aucune lecture hors-SQLite existante → la lecture fichier de `GET /traces` est un pattern neuf, à isoler proprement.
- **Lien offre↔trace** : `offers.source_id` présent, 60/60 distincts, 0 null. Join `traces.offer_id == offers.source_id` fiable → on enrichit chaque trace de `{title, company}`.
- **Front** : une seule page `web/app/pages/index.vue` (SPA à tabs). `/traces` exige une **nouvelle page** `web/app/pages/traces.vue` + un lien header. Store Pinia `web/app/stores/offers.ts` ($fetch + `config.public.apiBase`), composant liste `OffersTable.vue` (v-for sur `store.offers`) = patterns de référence à suivre.
- **Faux-juge en page offre** : `OfferDetail.vue:133-138` affiche les faits extraits bruts (`domain · seniority · techs`) **avec un badge `parse_failed ⚠`**. Le badge pose un verdict de qualité aveugle (le flag ne détecte que le crash JSON, pas la qualité d'extraction — confirmé le 9 juin). **Retrait du badge uniquement** ; les faits restent comme repère produit.

---

## Schémas cibles

> À affiner au moment du livrable correspondant — base de travail, pas contrat figé.
> Toute évolution d'un schéma cible ou de `architecture.md` = validation humaine explicite avant code (`rules/workflow.md`).

### Réponse API `GET /traces` (Pydantic, `api/schemas.py`)

```python
class TraceParsedFacts(BaseModel):
    # reflet de parsed_facts tel quel — NON jugé, NON normalisé
    seniority_required: str | None = None
    techs_required: list = []            # forme brute (str ou objets), affichée telle quelle
    domain: str | None = None
    role_level: str | None = None
    parse_failed: bool = False

class TraceOut(BaseModel):
    # clé synthétique (le JSONL n'a pas d'id de trace)
    trace_key: str                       # f"{offer_id}::{timestamp}"
    offer_id: str
    # enrichissement read-only depuis offers (join source_id) — repère, pas jugement
    offer_title: str | None = None
    offer_company: str | None = None
    # métadonnées (bloc 1)
    model: str
    temperature: float
    timestamp: str
    # entrée Wyss (bloc 2) — DÉ-ÉCHAPPÉES côté API (vrais \n)
    prompt_system: str
    prompt_user: str
    # sortie Husain (bloc 3)
    raw_response: str                    # dé-échappée
    parsed_facts: TraceParsedFacts
    parse_failed: bool
    # note d'error analysis (jointe depuis trace_notes, vide si absente)
    note: str | None = None
```

> Le dé-échappement (`\n` → vrais retours, suppression des `\` parasites) se fait **côté API en Python**. Le front reçoit du texte propre, il n'a aucun nettoyage à faire.
> `parsed_facts` est un **reflet** de ce qu'a gardé le code — affiché tel quel à côté du `raw_response`. La route ne le compare pas, ne le score pas.

### Table `trace_notes` (SQLite)

```sql
CREATE TABLE IF NOT EXISTS trace_notes (
    trace_key   TEXT PRIMARY KEY,        -- f"{offer_id}::{timestamp}" — annote UNE trace précise
    offer_id    TEXT NOT NULL,           -- redondant mais pratique pour requêter
    note        TEXT NOT NULL DEFAULT '',
    updated_at  TEXT NOT NULL            -- ISO8601, écrasé à chaque upsert
);
```

- Clé = `trace_key` (`offer_id + timestamp`), **pas** `offer_id` : les 2 traces d'une même offre ont chacune leur note, puisque c'est leur variance qu'on annote.
- Même statut que `seen`/`verdicts`/`human_reviews` : donnée d'interaction, jamais un intrant de recalcul, jamais fusionnée avec `offers`.

### Réponse note (`PUT /traces/{trace_key}/note`)

```python
class TraceNoteIn(BaseModel):
    note: str                            # peut être vide (= effacer la note)
```

---

## Phases

### Phase 1 — Route API `GET /traces` (read-only, dé-échappe, join offre)
Objectif : une route sert les 23 traces en JSON propre, sans dédup, triées, enrichies du titre d'offre.

- [x] L1 — Module de lecture traces (`api/traces_reader.py`) : ouvre le `.jsonl` (chemin résolu depuis `__file__`), parse ligne par ligne en **défensif** (ligne corrompue → sautée + `log.warning`, jamais de crash). Fichier absent → liste vide, pas d'erreur.
- [x] L2 — Dé-échappement + construction `TraceOut` : `\n` → vrais retours (déjà gérés par json.loads), `trace_key = offer_id::timestamp`, `parsed_facts` reflété tel quel (non jugé). Schemas `TraceParsedFacts`/`TraceOut`/`TraceNoteIn` ajoutés à `api/schemas.py`.
- [x] L3 — Enrichissement offre : join `offer_id → offers.source_id` (lecture SQLite via `api/db.py`) pour `offer_title`/`offer_company`. Offre introuvable → champs `None`, pas d'erreur.
- [x] L4 — Route `GET /traces` montée dans `api/main.py` (`api/traces.py`) : renvoie **toutes** les traces (aucune dédup), triées par `offer_id` puis `timestamp`. Jointure note défensive depuis `trace_notes` (table absente → None silencieux).

```
✋ Verify before continuing:
- [ ] GET /traces renvoie 23 objets (pas 20 — aucune dédup)
- [ ] prompt_user revient avec de vrais retours à la ligne (plus de \n littéraux)
- [ ] Les 3 offres à 2 traces ont leurs 2 traces présentes, groupées, trace_key distincts
- [ ] offer_title rempli quand l'offre existe en base ; None sans crash sinon
- [ ] 0 appel LLM, 0 écriture (offers/verdicts/human_reviews intacts)

Si tout OK : "go". Sinon dis ce qui cloche.
```

### Phase 2 — Persistance des notes (`trace_notes` + routes)
Objectif : une note par trace, persistée, rechargée à l'ouverture. Aucune écriture hors `trace_notes`.

- [x] L5 — Migration idempotente `CREATE TABLE IF NOT EXISTS trace_notes` (clé `trace_key`). + helpers `_upsert_note` / `_fetch_notes` dans `api/traces.py`. Appelée au démarrage du module.
- [x] L6 — `PUT /traces/{trace_key}/note` (upsert, écrit `updated_at`) + jointure note dans `GET /traces` opérationnelle. Note vide = effacement. Écrit UNIQUEMENT dans `trace_notes`.

```
✋ Verify before continuing:
- [ ] La migration tourne deux fois de suite sans erreur (idempotente)
- [ ] PUT note écrit UNIQUEMENT dans trace_notes (offers/verdicts/human_reviews/le .jsonl strictement intacts)
- [ ] GET /traces remonte la note sur la bonne trace (la 2e trace d'une offre garde sa propre note)
- [ ] Une note vide efface proprement (pas de ligne fantôme bloquante)

Si tout OK : "go". Sinon dis ce qui cloche.
```

### Phase 3 — Page `/traces` (front Nuxt)
Objectif : balayer les traces, déplier une carte, lire (3 blocs, 2/3 droite) et annoter (1/3 gauche, auto-save).

- [x] L7 — Store + setup : `web/app/stores/traces.ts` (fetchTraces + saveNote), page `web/app/pages/traces.vue` (squelette), lien "Traces LLM" dans le header de `index.vue`.
- [x] L8 — Liste de cartes repliables, groupées par `offer_id`. En-tête : facts · model · t° · timestamp · pastille si note. Repliée par défaut.
- [x] L9 — Carte dépliée, layout 1/3 note / 2/3 trace. Bloc 1 métadonnées · Bloc 2 prompt system+user monospace · Bloc 3 raw_response vs parsed_facts. Auto-save textarea au blur, indicateur "enregistré" 2s.

```
✋ Verify before continuing:
- [ ] /traces liste les 23 traces, groupées par offre, repliées par défaut
- [ ] Déplier montre la note à gauche (1/3) et la trace à droite (2/3)
- [ ] prompt_system / prompt_user / raw_response lisibles (vrais retours, monospace), few-shot vs offre réelle distinguables
- [ ] Écrire une note + quitter le champ la persiste (auto-save) ; recharger la page la recharge sur la bonne trace
- [ ] Aucun détecteur/score auto nulle part — la page ne juge pas

Si tout OK : "go". Sinon dis ce qui cloche.
```

### Phase 4 — Retrait du faux-juge en page offre
Objectif : retirer le badge `parse_failed` de la page offre, garder les faits comme repère produit.

- [x] L10 — `OfferDetail.vue:137` : badge `⚠ parse_failed` retiré. `domain · seniority_required · techs_required` conservés. Aucune autre modification.

```
✋ Verify before continuing:
- [ ] Le badge parse_failed a disparu de la page offre
- [ ] domain/seniority/techs toujours affichés (repère produit conservé)
- [ ] Le bloc calibration human_reviews et le badge catégorie/atteignabilité inchangés

Si tout OK : "go". Sinon dis ce qui cloche.
```

### Phase 5 — Clôture
Objectif : non-régression légère + fermeture propre.

- [x] L11 — `/handoff` : IMPLEMENTATION coché, STATE/JOURNAL/DECISIONS à jour, `IMPLEMENTATION-chantier-2.md` archivé dans `_archive/` (déjà en place).

```
✋ Verify before continuing:
- [ ] GET /offers et GET /offers/{id} répondent toujours (API non régressée)
- [ ] DECISIONS.md : trace_key, table trace_notes, chemin .jsonl depuis __file__, retrait badge tracés
- [ ] IMPLEMENTATION-chantier-2.md déplacé dans _archive/

Si tout OK : "go". Sinon dis ce qui cloche.
```

---

## Livrables détaillés

1. **L1 — Lecture défensive du `.jsonl`** — ouvre depuis `__file__`, ligne corrompue sautée + log, fichier absent → vide. `S`
2. **L2 — Dé-échappement + `TraceOut`** — vrais `\n`, `trace_key`, `parsed_facts` reflété non jugé. `S`
3. **L3 — Enrichissement offre** — join `offer_id→source_id`, titre/company, `None` sans crash. `S`
4. **L4 — Route `GET /traces`** — 23 traces sans dédup, triées par offre+timestamp, note jointe. `M`
5. **L5 — Table `trace_notes` + helpers** — migration idempotente clé `trace_key`, upsert/get. `S`
6. **L6 — `PUT /traces/{trace_key}/note`** — upsert, note vide = effacement, écrit que `trace_notes`. `S`
7. **L7 — Store + page + lien header** — action fetch, `pages/traces.vue`, nav vers /traces. `S`
8. **L8 — Liste cartes repliables groupées** — en-tête repère + pastille note, repliée par défaut. `M`
9. **L9 — Carte dépliée 1/3 note ⁄ 2/3 trace** — 3 blocs lecture seule + textarea auto-save. `L`
10. **L10 — Retrait badge `parse_failed`** — page offre, faits conservés. `XS`
11. **L11 — Handoff & archivage** — state à jour, chantier-2 archivé. `XS`

---

## Dépendances critiques

- L1 → L2 → L3 → L4 (la route s'assemble en couches : lecture → dé-échappe → enrichit → expose).
- L5 bloque L6 (pas de note sans table) et conditionne la jointure note de L4.
- L4 + L6 bloquent L7→L9 (le front ne s'affiche/n'annote qu'avec les routes prêtes).
- L10 est indépendant (peut se faire à tout moment, rangé en Phase 4 pour ne pas mélanger avec le viewer).

Chemin critique : `L1 → L2 → L4 → L5 → L6 → L7 → L8 → L9`.

---

## Hors-scope — explicitement reporté

- **Export traces + notes** (markdown collable dans un chat frais, façon `/export/calibration`). N'a de valeur qu'une fois des notes accumulées → prochaine feature, adossée aux notes.
- **Filtres** (par `role_level`, `domain`, "a une note", `parse_failed=true`) → prochaine feature, une fois le balayage vécu.
- **Pagination serveur** : 23 traces, inutile. Lazy-expand côté UI suffit. À revoir seulement si le volume explose (plusieurs centaines).
- **Toute correction des 3 défauts d'extraction** (few-shot mid-prompt, dégradations silencieuses, troncature `[:1500]`) — c'est ce que l'error analysis VA piloter, pas ce chantier. On lit d'abord.
- **`tracing.py`** (chemin CWD fragile côté orchestrateur) — pas touché ici. La route API résout son propre chemin depuis `__file__`.

---

## Garde-fous

- **"Lit, ne juge pas" sacré** : si on se surprend à coder un détecteur de trace suspecte, un highlight auto de divergence raw/parsed, ou un quelconque score de qualité → violation de l'invariant, stop. La seule évaluation est la note humaine.
- **Pas de dédup** : si on se surprend à vouloir "ne garder que la dernière trace par offre" → on jette le signal de variance, stop. 23 traces affichées, toujours.
- **`.jsonl` immuable** : aucune écriture sur le fichier de traces. Les notes vont dans `trace_notes`. Si un livrable veut écrire dans le `.jsonl`, frontière violée, stop.
- **Frontière offre** : Phase 4 retire UNIQUEMENT le badge `parse_failed`. Si on se surprend à retirer aussi les faits, ou à toucher la calibration / l'atteignabilité → hors-scope, stop.
- **0 LLM** : tout le chantier est de la lecture de fichier + affichage + persistance de notes. Aucun appel modèle, nulle part (§4).
