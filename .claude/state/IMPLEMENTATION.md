# IMPLEMENTATION — TCK-224 Fiche entreprise sur offre retenue

## Vue d'ensemble

Ajouter sur chaque offre retenue une fiche entreprise produite par Claude (Agent SDK, headless)
à partir d'une identification en cascade de l'employeur. La fiche est présentée point par point ;
Grégoire y réagit et classe chaque point dans un tas (lettre / entretien / ne se prétend pas).
Le tas « lettre » alimente TCK-226.

Première chose à attaquer : la table `fiches_entreprise` — le reste du back et le front en dépendent.

Refs : `rules/architecture.md` §4 (frontière extraction/matching, 0 LLM au recalcul),
`rules/pipeline.md` étages 4-6.

**Écarts constatés en Phase 0 :**
- `experiment_tck206.py` appelle `claude` via `subprocess` : ce pattern est interdit en applicatif.
  L-appel passe exclusivement par `claude-agent-sdk`.
- `allowed_tools=[]` ne restreint pas les outils (anomalie constatée dans `data/experiment_tck224/test_sdk.py`).
  Lu dans `types.py` du SDK 0.2.159 : `ClaudeAgentOptions.tools` est le champ qui fixe l'ensemble
  des outils disponibles — `tools=[]` désactive tous les built-ins, `tools=["WebSearch","WebFetch"]`
  restreint à ces deux. `allowed_tools` ne contrôle que l'auto-approbation, pas la disponibilité.
  `disallowed_tools` retire un outil même s'il figure dans `tools`. Chaque appel SDK du service
  déclare `tools`, `allowed_tools` et `disallowed_tools` explicitement (aucun laissé au défaut).
- `/offers/[id].vue` a déjà une carte « Entreprise » dans `CARDS` (l. 205-209) avec un overlay vide :
  c'est le slot exact remplacé par L-écran.
- Pas de répertoire `.claude/skills/` dans le repo : L-skill va dans `.claude/commands/fiche-entreprise.md`
  (format identique aux commandes existantes `run.md`, `ingest-indeed.md`), invocable via `/fiche-entreprise`.
- Deux points d'entrée de migration coexistent :
  `orchestrator/job_search/storage/db.py:init_db()` pour les CREATE TABLE ;
  `api/main.py:_migrate_db()` pour les ALTER TABLE au démarrage API.
  `fiches_entreprise` est créée dans `init_db()` (idempotent, `IF NOT EXISTS`).
  `api/main.py:_migrate_db()` inchangé à cette phase.

---

## Schémas cibles

### Table `fiches_entreprise` (SQL — `orchestrator/job_search/storage/db.py:init_db()`)

```sql
CREATE TABLE IF NOT EXISTS fiches_entreprise (
    id                    INTEGER PRIMARY KEY,
    offer_id              INTEGER NOT NULL REFERENCES offers(id),
    statut                TEXT NOT NULL DEFAULT 'pending', -- pending|done|error
    mode                  TEXT,   -- entreprise|offre_seule
    employeur_nom         TEXT,
    employeur_entite      TEXT,
    employeur_type_source TEXT,   -- direct|agence|agregateur|inconnu
    employeur_confiance   TEXT,   -- sur|probable|non_trouve
    employeur_methode     TEXT,
    employeur_urls_json   TEXT,   -- JSON array de strings
    points_json           TEXT,   -- JSON array [{position,citation,url,reaction,tas}]
    session_id            TEXT,
    cost_usd              REAL,
    tools_called_json     TEXT,   -- JSON array des outils effectivement appelés
    api_key_source        TEXT,
    prompt_text           TEXT,   -- prompt envoyé (audit invariant)
    error_message         TEXT,
    created_at            TEXT NOT NULL,
    UNIQUE(offer_id)
);
```

### Pydantic `CascadeResult` (nouveau — `orchestrator/job_search/fiche/cascade.py`)

```python
class CascadeResult(BaseModel):
    nom: str | None
    entite: str | None
    confiance: str        # sur|probable|non_trouve
    type_source: str      # direct|agence|agregateur|inconnu
    methode: str
    etape: int            # 1|2|3 — étape identifiante
```

### Schéma JSON sortie SDK — `_FICHE_SCHEMA` (`orchestrator/job_search/fiche/service.py`)

Extension de `experiment_tck206.py:SCHEMA` avec deux changements : ajout de `mode` + `maxItems:8`.

```json
{
  "type": "object",
  "properties": {
    "mode":      {"type": "string", "enum": ["entreprise", "offre_seule"]},
    "employeur": {
      "type": "object",
      "properties": {
        "nom":            {"type": ["string","null"]},
        "entite_precise": {"type": ["string","null"]},
        "type_source":    {"type": "string", "enum": ["direct","agence","agregateur","inconnu"]},
        "methode":        {"type": "string"},
        "confiance":      {"type": "string", "enum": ["sur","probable","non_trouve"]},
        "urls":           {"type": "array", "items": {"type": "string"}}
      },
      "required": ["nom","entite_precise","type_source","methode","confiance","urls"]
    },
    "points": {
      "type": "array",
      "maxItems": 8,
      "items": {
        "type": "object",
        "properties": {
          "position": {"type": "string"},
          "citation": {"type": ["string","null"]},
          "url":      {"type": ["string","null"]}
        },
        "required": ["position"]
      }
    }
  },
  "required": ["mode","employeur","points"]
}
```

Base de travail, pas contrat figé — à affiner au livrable correspondant.

---

## Phases

---

### Phase 1 — L-table : table `fiches_entreprise`

**Objectif** : la table existe en base après `init_db()` ; migration idempotente.

- [x] **L1 — `orchestrator/job_search/storage/db.py:init_db()`** : ajouter le `CREATE TABLE IF NOT EXISTS
  fiches_entreprise (...)` (schéma ci-dessus) après le bloc `human_reviews` dans le `executescript`.
  Done = `sqlite3 data/job_search.sqlite ".tables"` liste `fiches_entreprise`. **XS**

✋ Verify before continuing:
- [x] `sqlite3 data/job_search.sqlite ".schema fiches_entreprise"` affiche toutes les colonnes
- [x] `init_db()` appelé deux fois ne lève pas d'exception

---

### Phase 2 — L-cascade + L-skill

**Objectif** : employeur identifié en Python (3 étapes, de la moins chère à la plus chère) ;
skill `/fiche-entreprise` tourne manuellement dans Claude Code.

- [x] **L2a — `profiles/intermediaires.yaml`** (créer) : `intermediaires: [EDITX BV]` +
  commentaire indiquant d'y ajouter les cas rencontrés. Done = fichier présent, `yaml.safe_load`
  sans exception. **XS**

- [x] **L2b — `orchestrator/job_search/fiche/__init__.py`** (créer vide). **XS**

- [x] **L2c — `orchestrator/job_search/fiche/cascade.py`** (créer) :
  Fonction `identify_employer(offer_id: int, conn) -> CascadeResult`.
  Les 3 étapes s'exécutent toujours dans l'ordre ; le résultat est l'agrégat des 3.
  - Étape 1 — `offers.company` (insensible à la casse) comparé à `profiles/intermediaires.yaml`.
    Si correspondance : note `type_source=agregateur` dans `methode` et passe à l'étape 2.
    Pas de conclusion anticipée — la cascade continue.
  - Étape 2 — chercher en base les offres dont le sha256 des 500 premiers chars de
    `description_raw` (ou `description`) correspond à l'offre cible et dont la source est
    différente. Si une autre offre a un `company` non présent dans `intermediaires.yaml`, le
    relever dans `methode`. `etape=2` si une correspondance est trouvée.
  - Étape 3 — appel Ollama (`ollama.Client` du pattern `extractor.py:137`) : prompt court qui
    demande de classer `type_source` et de relever le nom de l'employeur si trouvé dans la
    description. Toujours exécutée. `etape=3` dans tous les cas.
  - `methode` trace les étapes parcourues et leurs résultats intermédiaires.
  - Retourne `CascadeResult`. Ne lève jamais — fallback
    `CascadeResult(nom=None, entite=None, confiance="non_trouve", type_source="inconnu", methode="fallback", etape=0)`.
  - Done = `identify_employer(2148, conn)` exécute les étapes 2 et 3 après avoir relevé
    EDITX BV comme intermédiaire à l'étape 1 ; `identify_employer(179, conn)` retourne sans exception. **M**

- [x] **L2d — `.claude/commands/fiche-entreprise.md`** (créer) : commande invocable
  `/fiche-entreprise <offer_id>`. Corps : instructions pour lire l'offre depuis DB
  (`data/job_search.sqlite`, lecture seule), lancer la cascade (Ollama local), construire le
  prompt depuis `_PROMPT_TEMPLATE` de `experiment_tck206.py` (adapté : ≤8 points), et sortir le
  JSON structuré. Le mode (`entreprise` ou `offre_seule`) est décidé par le modèle après sa
  recherche web — pas par la confiance issue de la cascade. Doit fonctionner sans le back démarré.
  Done = `/fiche-entreprise 179` produit un JSON avec clés `mode`, `employeur`, `points` (≤8). **S**

✋ Verify before continuing:
- [x] `identify_employer(2148, conn)` exécute les étapes 2 et 3 après avoir classé EDITX BV comme intermédiaire à l'étape 1 — livrable L2c — observé via le champ `methode` du résultat, qui nomme les étapes parcourues — si faux : consigner le `methode` obtenu au handoff
- [x] `identify_employer(179, conn)` → sans exception
- [x] `/fiche-entreprise 179` lancé manuellement → JSON `{mode, employeur, points}`, `len(points) <= 8` — **Écart : non lancé en slash-command ; vérifié via le même prompt (source unique commande) par `run_fiche(179)` → 8 points, JSON {mode, employeur, points}**
- [x] En mode `entreprise` : chaque point a une `url` et une `citation` non nulles
- [x] En mode `offre_seule` : aucun point ne nomme un employeur que la cascade n'a pas trouvé — **Non observé : les fiches 179 et 2148 sont en mode `entreprise` ; aucune fiche `offre_seule` produite**
- [x] Une fiche en mode `offre_seule` a au moins un outil de recherche web dans `tools_called_json` — livrable L3a — observé via `SELECT tools_called_json FROM fiches_entreprise WHERE mode='offre_seule'` — si faux : consigner l'offre au handoff — **Non observé : aucune fiche `offre_seule` en base. Les 2 fiches `entreprise` ont bien WebSearch/WebFetch dans `tools_called_json`**

---

### Phase 3 — L-appel + L-reprise

**Objectif** : le service Python appelle Claude Agent SDK, écrit la fiche en base ;
les routes API sont disponibles.

- [x] **L3a — `orchestrator/job_search/fiche/service.py`** (créer) :
  `_FICHE_SCHEMA` (dict Python, identique au schéma cible ci-dessus).
  `async def run_fiche(offer_id: int) -> None` :
  1. Ouvre connexion DB ; lit l'offre (`title`, `company`, `location`, `url`,
     `description_raw` ou `description`, `description[:12000]`).
  2. Écrit ligne `fiches_entreprise` avec `statut="pending"`, `created_at=now`.
  3. Appelle `identify_employer(offer_id, conn)` → `CascadeResult`.
  4. Charge `.claude/commands/fiche-entreprise.md` comme base du prompt ;
     n'y ajoute que les données de l'offre et le résultat de la cascade.
     Source unique du template — pas de duplication dans service.py.
  5. Appelle `claude_agent_sdk.query(prompt, ClaudeAgentOptions(
       tools=["WebSearch","WebFetch"],
       allowed_tools=["WebSearch","WebFetch"],
       disallowed_tools=["Bash","Write","Edit","NotebookEdit"],
       output_format={"type":"json_schema","schema":_FICHE_SCHEMA}))` en async for.
  6. Pendant le stream : `SystemMessage(subtype="init")` → capte `apiKeySource` ;
     messages tool_use (type à confirmer dans la doc SDK) → accumule noms dans `tools_called` ;
     `ResultMessage` → lit `structured_output`, `session_id`, `total_cost_usd`.
  7. Met à jour la fiche : `statut="done"`, tous les champs `employeur_*`, `points_json`,
     `session_id`, `cost_usd`, `tools_called_json`, `api_key_source`, `prompt_text`, `mode`.
  8. Exception → `statut="error"`, `error_message=str(exc)[:2000]`.
  - Done = `asyncio.run(run_fiche(179))` écrit une ligne `fiches_entreprise` avec
    `statut="done"`, `session_id` non nul, `cost_usd` non nul, `tools_called_json` non vide. **L**

- [x] **L3b — `api/fiche.py`** (créer) : `APIRouter(prefix="/offers")` avec 4 routes :
  - `POST /{offer_id}/fiche` (async) : vérifie que l'offre a un verdict `retenu` dans
    `verdicts` — sinon HTTP 409. Insère/reset une ligne pending, lance
    `asyncio.create_task(run_fiche(offer_id))`, retourne `{"statut": "pending"}` HTTP 202.
  - `GET /{offer_id}/fiche` : retourne la ligne `fiches_entreprise` ou HTTP 404.
  - `PATCH /{offer_id}/fiche/points/{point_idx}` : lit `points_json`, met à jour
    `reaction` et/ou `tas` du point à l'index `point_idx`, écrit en base.
    0 appel SDK / Ollama dans cette route. Retourne 200.
  - `POST /{offer_id}/fiche/points/{point_idx}/explain` (async) : lit `fiche.session_id`,
    appelle `query(prompt, ClaudeAgentOptions(resume=session_id, max_turns=2,
    tools=[], allowed_tools=[],
    disallowed_tools=["WebSearch","WebFetch","Bash","Write","Edit","NotebookEdit"]))`.
    Écrit le texte de l'explication dans `points_json[point_idx].explication` sans toucher
    `position`, `citation`, `url`, `reaction` ni `tas`. Retourne le texte.
  - Done = POST 179 retourne 202 ; GET 179 après ~2 min retourne `statut="done"`. **M**

- [x] **L3c — `api/main.py`** : importer `fiche_router` depuis `api.fiche` et
  `app.include_router(fiche_router)` (pattern identique aux autres routers). Done = diff 2 lignes. **XS**

✋ Verify before continuing:
- [x] `grep -rn "subprocess" api/ orchestrator/job_search/fiche/` → 0 résultat hors `experiment_*`
- [x] `grep -rn '"claude"' api/ orchestrator/job_search/fiche/` → 0 résultat hors `experiment_*`
- [x] Fiche 179 en base : `api_key_source = "none"`, `session_id` non nul, `tools_called_json` liste au moins un outil
- [x] `prompt_text` de la fiche 179 contient le résultat cascade (étape identifiante) + la description de l'offre
- [x] `PATCH /offers/179/fiche/points/0 {reaction:"d_accord"}` → GET fiche → `points_json[0].reaction="d_accord"` ; aucun appel SDK dans le chemin (vérification statique : `PATCH` handler ne contient ni `query` ni `run_fiche`)
- [x] `POST /offers/179/fiche/points/0/explain` → texte reçu et écrit dans `points_json[0].explication` ; GET fiche → `points_json[0].reaction`, `position`, `citation`, `url`, `tas` inchangés
- [x] `grep -rn "resume" api/ orchestrator/job_search/fiche/` → uniquement dans `api/fiche.py` route explain
- [x] Aucun appel SDK n'a `disallowed_tools` vide ; Bash, Write et Edit y figurent dans run_fiche et dans explain, et les fiches réelles de 179 et 2148 n'enregistrent aucun de ces outils dans `tools_called_json` — livrable L3b — observé via grep de `disallowed_tools` et `SELECT tools_called_json FROM fiches_entreprise` — si faux : consigner l'appel et l'outil au handoff

---

### Phase 4 — L-écran

**Objectif** : la carte « Entreprise » sur `/offers/[id]` est interactive ;
les fiches de 179 et 2148 existent en base produites depuis le bouton.

- [x] **L4a — types TS dans `web/app/stores/offers.ts`** : ajouter après `OfferDetail` :
  ```typescript
  export interface FichePoint {
    position: string
    citation: string | null
    url: string | null
    reaction: 'd_accord' | 'pas_d_accord' | 'je_ne_connais_pas' | 'sonnerait_faux' | null
    tas: 'lettre' | 'entretien' | 'ne_se_pretend_pas' | null
    explication: string | null
  }
  export interface FicheEntreprise {
    statut: 'pending' | 'done' | 'error'
    mode: 'entreprise' | 'offre_seule' | null
    employeur_nom: string | null
    employeur_confiance: string | null
    points: FichePoint[]
    session_id: string | null
    cost_usd: number | null
    error_message: string | null
  }
  ```
  Étendre `OfferDetail` avec `fiche?: FicheEntreprise | null`. Done = `tsc --noEmit` sans erreur. **XS**

- [x] **L4b — `web/app/pages/offers/[id].vue`** : remplacer le bloc de la carte « Entreprise »
  dans `CARDS` + son branch dans l'overlay par :
  - `fiche` : `ref<FicheEntreprise | null>(null)` chargé via `GET /offers/{id}/fiche` dans
    `onMounted` (404 → `fiche=null`).
  - Le bouton « Préparer la fiche » n'est visible que si `offer.verdict === 'retenu'`.
  - **Si `!fiche` ou `fiche.statut === "error"`** : affiche le bouton (+ message d'erreur si error).
    Clic → `POST /offers/{id}/fiche` → `fiche={statut:"pending"}` → lance `startPolling()`.
  - **`startPolling()`** : `setInterval(GET .../fiche, 5000)` jusqu'à `statut !== "pending"`,
    puis `clearInterval`.
  - **Si `statut === "pending"`** : spinner + "Recherche en cours…".
  - **Si `statut === "done"`** : liste des `fiche.points` avec pour chaque point :
    - Texte `position` + `citation` (si non null) + lien `url` (si non null).
    - 4 boutons radio réaction : `d_accord` / `pas_d_accord` / `je_ne_connais_pas` /
      `sonnerait_faux` → `PATCH /offers/{id}/fiche/points/{idx} {reaction: ...}`.
    - 3 boutons radio tas : `lettre` / `entretien` / `ne_se_pretend_pas` →
      `PATCH /offers/{id}/fiche/points/{idx} {tas: ...}`.
    - Bouton « Expliquer » visible si `point.reaction === "je_ne_connais_pas"` →
      `POST /offers/{id}/fiche/points/{idx}/explain` → affiche la réponse en regard du point.
  - Done = offre 179 : bouton → spinner → fiche ; clic réaction → GET → réaction persistée. **L**

✋ Verify before continuing:
- [x] La réaction et le tas d'un point sont écrits en base tels que saisis — aucun appel SDK ou Ollama entre le clic et l'écriture (`PATCH` route ne contient ni `run_fiche` ni `query` ni appel `ollama`)
- [x] `resume` absent du handler `PATCH` et de l'`onMounted`
- [x] `SELECT offer_id, mode, cost_usd, json_array_length(points_json) FROM fiches_entreprise WHERE offer_id IN (179, 2148)` → 2 lignes, `cost_usd` non nul, `json_array_length` ≤ 8 pour les deux ; contenu des fiches rapporté au handoff tel quel

---

### Corrections après essai (post-livraison, 2026-09-28)

**Objectif** : après essai réel par Grégoire (offres 155, 2074 produites depuis le bouton), trois corrections
directes, sans repasser par `/implementation`.

- [x] **Tri d'un point à un seul choix** : `tas ∈ {lettre, entretien, rien}`. La réaction (`d_accord` /
  `pas_d_accord` / `je_ne_connais_pas` / `sonnerait_faux`) disparaît de l'écran et de la route PATCH
  (`PointPatch` n'accepte plus que `tas`, `extra="forbid"` — un champ `reaction` renvoie 422). Migration
  de données : `tas="ne_se_pretend_pas"` → `"rien"` sur les fiches existantes (`migrate_fiches_entreprise_schema`,
  idempotente, appelée depuis `init_db()`). Les champs `reaction` déjà en JSON restent en base, non purgés,
  simplement plus lus ni écrits.
- [x] **« Expliquer » disponible sur tous les points** — le bouton n'est plus conditionné à
  `reaction === 'je_ne_connais_pas'` (ce filtre disparaît avec la réaction). Route explain inchangée côté API.
- [x] **Paragraphe `presentation`** : nouveau champ texte produit dans le même appel SDK que les points
  (`_FICHE_SCHEMA`, colonne `fiches_entreprise.presentation`, migration `ALTER TABLE` idempotente). Consigne
  ajoutée à `.claude/commands/fiche-entreprise.md` (source unique du prompt) : tiré des pages ouvertes pendant
  la recherche, jamais de la connaissance générale ; en mode `offre_seule`, décrit ce que l'annonce laisse
  savoir de l'employeur sans le nommer ; jamais de paragraphe de lettre ou de candidature. Affiché en tête de
  la fiche côté écran, masqué si vide (`v-if="fiche.presentation"`).

✋ Verify before continuing:
- [x] PATCH d'un tas écrit la valeur telle que saisie, sans appel SDK ni Ollama — `PATCH /offers/179/fiche/points/1 {tas:"rien"}` → 200, GET fiche confirme `tas="rien"` ; handler `patch_point` ne contient ni `query` ni `run_fiche` ni appel `ollama`
- [x] PATCH avec une valeur hors {lettre, entretien, rien} → 422 ; PATCH avec `reaction` → 422 (`extra_forbidden`)
- [x] Explain sur un point sans `tas` fonctionne ; `position`, `citation`, `url`, `tas` inchangés après — vérifié sur le point 2 de la fiche 179
- [x] Fiche neuve sur 155 depuis le bouton (navigateur) : `presentation` non vide (paragraphe sur Reboot Conseil), 8 points, mode `entreprise`, outils appelés `["WebSearch","WebFetch",...,"StructuredOutput"]` — **écart consigné, non jugé** : la cascade avait directement trouvé le nom de l'entreprise (« Reboot Conseil », néo-cabinet de conseil, pas d'employeur masqué), donc mode `entreprise` et non `offre_seule` malgré l'attente initiale sur cette offre
- [ ] Si 155 sort en `offre_seule` : non applicable — 155 est sortie en mode `entreprise` (voir écart ci-dessus). Aucune fiche `offre_seule` observée à ce jour, ni sur cette offre ni sur les autres.
- [x] Fiches 179 et 2148 : écran affiché sans erreur avec `presentation` vide (bloc masqué, aucune erreur console)
- [x] `.claude/commands/fiche-entreprise.md` reste la seule source du prompt — `prompt.py` ne fait que charger ce fichier et y concaténer offre + cascade, aucun texte de consigne ajouté en Python

---

## Livrables détaillés

1. **L1 — `orchestrator/job_search/storage/db.py:init_db()`** : CREATE TABLE `fiches_entreprise`. Done = table présente. **XS**
2. **L2a — `profiles/intermediaires.yaml`** : liste EDITX BV. Done = YAML valide. **XS**
3. **L2b — `orchestrator/job_search/fiche/__init__.py`** : fichier vide. Done = module importable. **XS**
4. **L2c — `orchestrator/job_search/fiche/cascade.py`** : `CascadeResult` + `identify_employer`, 3 étapes, fallback. Done = 2148 → étape 1 non_trouve ; 179 → sans exception. **M**
5. **L2d — `.claude/commands/fiche-entreprise.md`** : `/fiche-entreprise <offer_id>` manuel. Done = JSON ≤8 points sur 179. **S**
6. **L3a — `orchestrator/job_search/fiche/service.py`** : `run_fiche()` async, cascade → prompt → SDK → fiche en base. Done = fiche 179 `statut=done`. **L**
7. **L3b — `api/fiche.py`** : 4 routes (POST génération, GET fiche, PATCH point, POST explain). Done = POST 202 ; GET fiche ; PATCH sans SDK. **M**
8. **L3c — `api/main.py`** : +2 lignes router fiche. Done = diff 2 lignes. **XS**
9. **L4a — `web/app/stores/offers.ts`** : types `FichePoint`, `FicheEntreprise`, extension `OfferDetail`. Done = `tsc --noEmit` vert. **XS**
10. **L4b — `web/app/pages/offers/[id].vue`** : carte Entreprise interactive, polling, annotation, relance. Done = 179 et 2148 produites depuis le bouton. **L**

## Dépendances critiques

- L1 bloque L3a, L3b (écriture/lecture en base), L4a, L4b (types + fetch fiche).
- L2a, L2c bloquent L3a (`run_fiche` appelle `identify_employer`).
- L2d bloque L3a : `run_fiche()` charge `.claude/commands/fiche-entreprise.md` comme source
  unique du prompt — pas de duplication du template dans service.py.
- L3a, L3b, L3c bloquent L4b (routes API requises avant appels front).
- L4a bloque L4b (types TS).

## Garde-fous

- Anomalie `allowed_tools=[]` : si `tools_called_json` est vide sur une fiche réelle, consigner au handoff (l'invariant exige que les outils appelés soient enregistrés).
- `ANTHROPIC_API_KEY` dans l'env : `run_fiche` fonctionne sans elle (SDK passe par le login Claude). Si la clé est présente au démarrage, `api_key_source` ne sera pas `"none"` — consigner au handoff.
- Polling front : si `statut="error"`, arrêter le polling immédiatement et afficher `error_message`.
- Blocage ou imprévu à l'exécution : trancher, continuer, consigner l'écart au handoff. L'exécution ne s'arrête jamais.
