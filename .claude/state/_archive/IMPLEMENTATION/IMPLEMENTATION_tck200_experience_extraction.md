# IMPLEMENTATION — TCK-200 Expérience extraction 6 variantes × 3 répétitions

## Vue d'ensemble

Mesurer si le manque de MLOps/MLflow dans l'extraction de l'offre 2874 est dû au modèle, au
nommage du champ `techs_required`, ou à une troncature du prompt. Un script autonome rejoue
l'appel `client.chat()` directement sur 6 variantes × 3 répétitions, sans toucher la base ni
les traces de production. Première chose à attaquer : créer `experiment_tck200.py` en appelant
`client.chat()` directement — `extract_facts()` est interdit car il écrit systématiquement
dans les traces de production via `_write_trace()` (deux branches : succès lignes 209-219,
fallback lignes 228-238 de `extractor.py`).

Refs architecture : `rules/architecture.md` §4 (0 LLM au recalcul, séparation
extraction/matching). Règles pipeline : `rules/pipeline.md` §Étage 4 (trace append-only,
sacrée).

**Écarts constatés en Phase 0 :**
- `extract_facts()` appelle `_write_trace()` dans les deux branches de sortie — le script
  expérimental NE PEUT PAS l'appeler ; il doit reproduire `client.chat()` directement.
- `LLMTrace` (tracing.py) ne capture pas `prompt_eval_count` — ce champ est lu sur
  `resp.prompt_eval_count` (`ChatResponse` de la lib ollama, disponible hors streaming).
- Ollama est passé de 0.22.0 (version des extractions en base) à 0.34.2 (actuel) — le
  `num_ctx` par défaut peut différer entre les deux versions. `num_ctx` n'est pas retourné
  dans la réponse `chat` ; il est lu une fois par modèle via `client.show(model).parameters`
  (chaîne `"num_ctx XXXX"`) avant la boucle de run. `prompt_eval_count` est le proxy
  d'exécution (tokens effectivement traités).
- `replay_traces.py` ne peut pas servir de base : il appelle `extract_facts()`, qui écrit
  dans les traces.

---

## Phases

---

### Phase 1 — Script `experiment_tck200.py`

**Objectif** : script autonome à la racine, lecture seule SQLite, 0 appel à `extract_facts`,
6 variantes × 3 répétitions, résultats dans `data/experiment_tck200/`.

- [x] **L1 — `experiment_tck200.py`** (à créer à la racine du repo) :

  **Lecture DB** — SQL direct, connexion `sqlite3` lecture seule sur
  `data/job_search.sqlite` :
  ```sql
  SELECT title, description, experience_required, rome_label, alternance
  FROM offers WHERE id = 2874
  ```
  Construire un dict `offer_row`. Aucune écriture sur la table `offers`.

  **Construction des prompts** — Importer `_SYSTEM_PROMPT` et `_FEW_SHOT` depuis
  `orchestrator.job_search.scoring.extractor` (constantes module-level). Ne pas importer
  `extract_facts`. Reconstruire `user_prompt` avec la même formule qu'`extractor.py`
  lignes 123-131 (few-shot + title + description[:8000] + hints + "Extract facts now:").

  Pour variantes C et D, définir inline dans le script :
  - `_SYSTEM_PROMPT_C` = `_SYSTEM_PROMPT` avec deux substitutions :
    `"techs_required"` → `"skills_required"` et
    `"specific technology names only"` → `"compétences techniques, outils ou pratiques"`
  - `_FEW_SHOT_C` = `_FEW_SHOT` avec `"techs_required"` → `"skills_required"` partout

  **Variantes et modèles** :
  ```python
  VARIANTS = {
      "A": ("llama3",     "current", {}),                  # prod actuelle
      "B": ("gemma4:12b", "current", {}),                  # modèle B, prompt actuel
      "C": ("llama3",     "skills",  {}),                  # prompt compétences
      "D": ("gemma4:12b", "skills",  {}),                  # modèle B + prompt compétences
      "E": ("llama3.1:8b","current", {}),                  # témoin génération suivante
      "F": ("llama3",     "current", {"num_ctx": 8192}),   # num_ctx forcé à 8192
  }
  REPS = 3
  ```

  **num_ctx et version Ollama** — lire une fois avant la boucle :
  ```python
  # Version Ollama
  ollama_version = requests.get(f"{host}/api/version").json().get("version", "unknown")

  # num_ctx déclaré par modèle (depuis client.show().parameters — str multilignes)
  def _read_num_ctx(client, model_name: str) -> str:
      try:
          params = client.show(model_name).parameters or ""
          for line in params.splitlines():
              parts = line.split()
              if len(parts) == 2 and parts[0] == "num_ctx":
                  return parts[1]
      except Exception:
          pass
      return "non déclaré"
  ```
  Appeler `_read_num_ctx` une fois par modèle distinct avant la boucle ; stocker dans un dict
  `num_ctx_by_model`.

  **Boucle de run** — pour chaque `(variant_id, rep_num)` :
  - Sélectionner `system_prompt` + `user_prompt` selon le schéma ("current"/"skills") ;
    `extra_opts` = 3e élément du tuple VARIANTS
  - `opts = {"temperature": 0.1, **extra_opts}`
  - `resp = client.chat(model=model, messages=[{"role":"system","content":system_prompt}, {"role":"user","content":user_prompt}], options=opts)`
  - Capturer `resp.message.content`, `resp.prompt_eval_count` (peut être `None` — écrire
    `null`)
  - Parser best-effort le JSON de la réponse : `json.loads(raw_stripped)`, extraire
    `data.get("techs_required") or data.get("skills_required")` → liste de noms lowercase.
    En cas d'échec : `techs = [], parse_failed = True`
  - Détecter `"mlops"`, `"mlflow"`, `"ci/cd"` par sous-chaîne sur chaque nom lowercase.
    Pour ci/cd, accepter aussi `"ci_cd"`, `"cicd"`, `"ci-cd"` (tester si l'un de ces
    tokens est contenu dans le nom)
  - Écrire une ligne JSONL dans `data/experiment_tck200/runs.jsonl` :
    ```json
    {"variant": "A", "rep": 1, "model": "llama3", "schema": "current",
     "techs": [...], "mlops_found": false, "mlflow_found": false, "cicd_found": false,
     "prompt_eval_count": 512, "num_ctx_declare_modelfile": "4096", "num_ctx_force": null,
     "ollama_version": "0.34.2", "parse_failed": false,
     "system_prompt": "...", "user_prompt": "...", "raw_response": "...", "timestamp": "..."}
    ```
    Les champs `system_prompt` et `user_prompt` permettent le grep post-run sur les prompts
    effectivement envoyés. `num_ctx_force` = valeur de l'option forcée (8192 pour F, null
    sinon).

  **Rapport** — après la boucle, écrire `data/experiment_tck200/report.md` :
  - En-tête : version Ollama, note "num_ctx non fixé dans options sauf variante F (8192) —
    valeur déclarée par modèle lue via `client.show()`"
  - Tableau Markdown (18 lignes) :

  | Variante | Rép | Modèle | Schéma | Techs extraites | mlops | mlflow | ci/cd | prompt\_eval\_count | num\_ctx\_declare\_modelfile | num\_ctx\_force | parse\_failed |
  |---|---|---|---|---|---|---|---|---|---|---|---|

  Aucune colonne interprétative (cause, conclusion, tendance). Tableau de mesures brutes.

  Done = script passe `python experiment_tck200.py --dry-run` (lecture DB + construction des
  6 prompts, 0 appel Ollama) — le dry-run affiche les compteurs de substitution pour C/D.
  **M**

✋ Verify before continuing:
- [x] `extractor.py`, `base.py` et le schéma `ExtractedFacts` sont inchangés dans le diff final — observé via `git diff orchestrator/job_search/scoring/extractor.py orchestrator/job_search/sources/base.py` — si faux : consigner le diff au handoff
- [x] Chaque substitution de C est effectivement appliquée : le `--dry-run` affiche que `"specific technology names only"` apparaît exactement 1 fois dans `_SYSTEM_PROMPT` avant remplacement, que `_SYSTEM_PROMPT_C != _SYSTEM_PROMPT`, et que `"techs_required"` apparaît 0 fois dans `_SYSTEM_PROMPT_C` et dans `_FEW_SHOT_C` — si faux : consigner la chaîne introuvable et le prompt obtenu au handoff
- [x] `grep "extract_facts" experiment_tck200.py` → 0 résultat (aucun import ni appel de la fonction)

Si tout est OK : "go". Sinon dis ce qui cloche.

---

### Phase 2 — Exécution et tableau récapitulatif

**Objectif** : 18 appels Ollama exécutés, `report.md` produit, invariants vérifiés.

- [x] **L2 — Exécution** : relever `wc -l data/traces/extract_facts.jsonl` AVANT, lancer
  `python experiment_tck200.py`, relever `wc -l` APRÈS. Inspecter
  `data/experiment_tck200/report.md`.

✋ Verify before continuing:
- [x] `data/traces/extract_facts.jsonl` a le même nombre de lignes avant et après — observé via `wc -l` avant/après — si faux : consigner les lignes ajoutées au handoff
- [x] 0 écriture dans `job_search.sqlite` — observé via `SELECT extracted_facts_json FROM offers WHERE id=2874` avant et après, identiques, ET mtime inchangé — si faux : consigner la table et la ligne touchées au handoff
- [x] Le livrable final est un tableau de mesures, sans conclusion sur la cause — observé via relecture de `data/experiment_tck200/report.md` — si faux : consigner le passage retiré au handoff
- [x] Pour les runs C et D, ni `system_prompt`, ni la partie few-shot de `user_prompt` (tout ce qui précède "Title:") ne contiennent « mlops », « mlflow » ou « proximus » — livrable L2 — observé via lecture de `data/experiment_tck200/runs.jsonl` après exécution — si faux : consigner le prompt concerné au handoff

Si tout est OK : "go". Sinon dis ce qui cloche.

---

## Livrables détaillés

1. **L1 — `experiment_tck200.py`** (racine) — lecture seule DB, 6 variantes × 3 reps, prompts
   C/D définis inline, num_ctx lu via `client.show()`, rapport dans
   `data/experiment_tck200/`. Done = `--dry-run` passe sans erreur, 6 prompts construits.
   **M**
2. **L2 — Exécution + `data/experiment_tck200/report.md`** — 18 runs, tableau 18 lignes,
   invariants respectés. Done = `wc -l` avant=après, tableau existant sans colonne
   interprétative. **S**

## Dépendances critiques

- L2 bloque sur L1.

## Garde-fous

- Si `resp.prompt_eval_count` est `None` pour un run : écrire `null` dans le JSONL, laisser
  la cellule vide dans le rapport — ne pas crasher.
- Si un modèle n'est pas disponible (Ollama retourne une erreur) : logguer le run comme
  `parse_failed=True` avec le message d'erreur dans `raw_response`, continuer les autres
  variantes.
- Si `client.show(model).parameters` ne contient pas `num_ctx` : noter `"non déclaré"` dans
  `num_ctx_declare_modelfile`. Pour la variante F, `num_ctx_force` = 8192 est toujours
  renseigné indépendamment de `client.show()`.
- Blocage ou imprévu à l'exécution : trancher, continuer, consigner l'écart au handoff.
  L'exécution ne s'arrête jamais.
