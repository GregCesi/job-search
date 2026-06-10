# IMPLEMENTATION — Chantier traces LLM : instrumentation de `extract_facts`

> Mode **augment**. Devient le document de travail courant ; l'IMPLEMENTATION-chantier-2 reste en place (livré), non écrasé.
> Le `.claude/` structurel (rules, commands, settings) n'est PAS régénéré.
> Invariants `architecture.md` à respecter : §3 parsing défensif, §4 capture à l'ingestion uniquement (0 LLM au rescore ⇒ 0 trace au rescore), §Persistance (la trace est un canal séparé, n'écrit JAMAIS dans offers/verdicts/human_reviews).

## Vue d'ensemble

Le pipeline ne persiste aujourd'hui que la sortie parsée du seul appel LLM actif (`extract_facts`) — une **note**, pas une **trace**. Sans le prompt exact ni la réponse brute pré-parsing, l'error analysis (Husain) et l'audit du context engineering (Wyss) sont impossibles : on voit le symptôme dans la sortie propre, jamais la cause.

Ce chantier instrumente `extract_facts` pour qu'elle écrive une trace complète (entrée prompt + sortie brute + sortie parsée + métadonnées) dans un `.jsonl` à chaque appel, puis fournit un script de re-jeu pour peupler ce fichier sur 15-20 offres existantes. Livrable terminal : un `.jsonl` lisible ligne à ligne. **La lecture/error-analysis des traces est l'étape suivante, HORS de ce chantier.**

**Première phase à attaquer : Phase 0 — lecture du code réel de `extract_facts`.** Trois hypothèses risquées du cadrage se confirment ou s'infirment uniquement en lisant le corps de la fonction. Rien ne se code avant.

---

## Calage sur l'existant (à vérifier en Phase 0 — NON négociable)

Faits du cadrage à confirmer dans le repo réel avant d'écrire la moindre ligne :

- **`extract_facts` est dans `extractor.py`** (le PROSIT dit `extractor.py:127`, mais `IMPLEMENTATION-ui.md` situe l'extracteur sous `orchestrator/job_search/matching/`). Confirmer le chemin réel et le numéro de ligne après la migration physique du 1er juin (`job_search/` → `orchestrator/job_search/`).
- **Signature `-> ExtractedFacts`** et appel unique depuis `run.py`. Confirmer qu'aucun autre appelant n'existe (sinon la trace se peuple aussi depuis ces chemins — à noter, pas forcément à corriger).
- **`_score_criterion` / `score_offer` (scorer.py) sont morts** (jamais câblés dans `run.py`). HORS SCOPE — ne pas les tracer, ne pas trancher leur sort.
- **Le texte d'offre passé à `extract_facts`** : confirmer que la base stocke bien le texte non tronqué utilisé à l'ingestion (colonne `description` ajoutée le 31 mai), pour que le re-jeu reçoive le même input que la prod.

---

## Schémas cibles

> À affiner au moment du livrable correspondant — base de travail, pas contrat figé.
> Toute évolution d'un schéma cible ou de `architecture.md` = validation humaine explicite avant code (`rules/workflow.md`).

### Schéma de trace (`LLMTrace`)

```python
# Pydantic — sérialisé en une ligne JSONL par appel.
# Champs figés au cadrage. La trace est un EFFET DE BORD, jamais une valeur de retour.
class LLMTrace(BaseModel):
    offer_id: str            # id de l'offre extraite (source_id ou id DB — trancher en L1 selon ce que voit extract_facts)
    model: str               # $OLLAMA_MODEL effectif au moment de l'appel
    temperature: float       # 0.1 attendu
    prompt_system: str       # le system prompt exact envoyé
    prompt_user: str         # le user prompt exact (variable locale extractor — moitié-entrée Wyss)
    raw_response: str        # la réponse du modèle AVANT tout parsing (moitié-sortie Husain) — fidélité absolue
    parsed_facts: dict       # ExtractedFacts.model_dump() (sortie parsée finale)
    parse_failed: bool       # True si le parsing strict a échoué et qu'un fallback a comblé
    timestamp: str           # ISO8601
```

> `offer_id` : `extract_facts(text) -> ExtractedFacts` ne reçoit aujourd'hui qu'un texte, pas d'id. Deux options à trancher en L1 : (a) ajouter un param optionnel `offer_id: str | None = None` à la signature (changement mineur, l'appelant le passe) ; (b) laisser `offer_id` vide dans la trace écrite par la fonction et le réinjecter côté script de re-jeu / appelant. **(a) est préférable** : un param optionnel ne casse pas l'appelant existant et rend la trace auto-suffisante. À valider car ça touche la signature (workflow.md).

### Fichier de traces

- Chemin : `data/traces/extract_facts.jsonl` (à côté de `data/job_search.sqlite`).
- `data/traces/*.jsonl` ajouté au `.gitignore` (traces = données locales, même statut que la SQLite).
- Mode append, une ligne = une trace, `json.dumps(..., ensure_ascii=False)` sans indentation.

---

## Phases

### Phase 0 — Lecture du code réel (0 écriture)
Objectif : confirmer/infirmer les 3 hypothèses risquées avant de coder. Aucune modification de fichier.

- [x] L0 — Lire le corps de `extract_facts` (chemin réel, n° de ligne, locales `user_prompt` / `raw`) + son appel dans `run.py`. Produire une note de 5-8 lignes répondant à : (a) **point de sortie unique ou multiple** ? (b) le **fallback est-il distinguable** d'un parse réussi (peut-on renseigner `parse_failed` honnêtement) ? (c) la base **stocke-t-elle le texte non tronqué** passé à l'extraction ?

```
✋ Verify before continuing:
- [ ] Chemin + signature réels de extract_facts confirmés (vs extractor.py:127 du cadrage)
- [ ] Réponse tranchée sur les 3 points (a/b/c) — si (b) tombe (fallback indistinguable), ajuster L3 avant de continuer
- [ ] Aucun fichier modifié

Si tout est OK : "go". Sinon dis ce qui cloche.
```

### Phase 1 — Schéma + helper d'écriture (testés isolément, AVANT de toucher extract_facts)
Objectif : `LLMTrace` figé et `_write_trace` écrit une ligne JSONL valide sans jamais propager d'erreur.

- [x] L1 — Schéma `LLMTrace` Pydantic (9 champs). Trancher `offer_id` : param optionnel sur `extract_facts` (préféré) vs réinjection côté appelant. Décision tracée dans DECISIONS.md.
- [x] L2 — Helper `_write_trace(trace: LLMTrace, path: Path)` : sérialise + append en JSONL, encapsulé dans un `try/except` **non bloquant** (une erreur d'écriture logge mais ne lève pas). Créé dans le même module que `extract_facts` ou un petit `tracing.py` à côté (trancher en L2).

```
✋ Verify before continuing:
- [ ] LLMTrace valide un exemple fabriqué à la main, model_dump_json() produit 1 ligne
- [ ] _write_trace appelé avec une trace factice écrit 1 ligne JSONL relisable (json.loads round-trip)
- [ ] Une erreur d'écriture simulée (path invalide) ne lève PAS — l'appel retourne normalement
- [ ] data/traces/ dans .gitignore

Si tout est OK : "go". Sinon dis ce qui cloche.
```

### Phase 2 — Instrumentation interne de `extract_facts`
Objectif : insérer la capture avant le `return`, type de retour inchangé, `run.py` tourne sans modification.

- [x] L3 — Construire la `LLMTrace` depuis les locales (`user_prompt`, `raw`, faits parsés, flag de parse) et appeler `_write_trace` **avant chaque point de sortie** (un seul si Phase 0 l'a confirmé ; sinon un appel par branche). `parse_failed` renseigné selon le verdict de Phase 0(b). Signature/retour inchangés.

```
✋ Verify before continuing:
- [ ] Un appel réel à extract_facts sur 1 offre écrit 1 ligne dans data/traces/extract_facts.jsonl
- [ ] La ligne contient les 9 champs renseignés (raw_response non vide, prompt_user non vide)
- [ ] Le type de retour est inchangé (ExtractedFacts) — run.py tourne sur 1-2 offres sans modif ni erreur
- [ ] parse_failed reflète la réalité (forcer une offre au parsing douteux si possible pour le vérifier)

Si tout est OK : "go". Sinon dis ce qui cloche.
```

### Phase 3 — Script de re-jeu + corpus peuplé
Objectif : peupler le `.jsonl` de 15-20 traces depuis des offres existantes, sans muter la base.

- [x] L4 — `replay_traces.py` à la **racine du repo** (instrument d'audit, hors package prod ; lancé via `python -m` ou avec `sys.path` ajusté). Lit `data/job_search.sqlite` (SELECT id + texte d'offre), tire N offres par **échantillonnage aléatoire seed-fixe** (reproductible), appelle `extract_facts` sur chacune. **N'écrit RIEN dans `offers`.** Arg `--n` (défaut 20), `--seed` (défaut fixe).
- [x] L5 — Exécuter `python replay_traces.py --n 20` → `data/traces/extract_facts.jsonl` peuplé. Vérifier 15-20 lignes valides à 9 champs.

```
✋ Verify before continuing:
- [ ] Re-jeu de 2-3 offres d'abord : data/traces/extract_facts.jsonl gagne 2-3 lignes, offers INCHANGÉE (vérifier en DB : count + un score au hasard)
- [ ] Lancement complet --n 20 : 15-20 lignes JSON valides, chacune 9 champs renseignés
- [ ] Le tirage est reproductible (même seed → mêmes offer_id)
- [ ] verdicts / human_reviews / criteria_json strictement intacts

Si tout est OK : "go". Sinon dis ce qui cloche.
```

### Phase 4 — Clôture
Objectif : fermeture propre. **Pas de lecture des traces ici** (étape suivante, autre session/chat).

- [x] L6 — `/handoff` : IMPLEMENTATION coché, STATE/JOURNAL/DECISIONS à jour. STATE pointe la suite = « lire les 15-20 traces à la triple grille (réappropriation / Wyss entrée / Husain sortie) en chat ».

```
✋ Verify before continuing:
- [ ] data/traces/extract_facts.jsonl existe, 15-20 lignes, ouvrable à la main
- [ ] DECISIONS.md : décision offer_id (signature) + emplacement script tracés
- [ ] Aucun défaut repéré n'a été "corrigé" en passant (texte au milieu / fallback silencieux / [:1500] intacts — ils se traitent APRÈS lecture)

Si tout est OK : "go". Sinon dis ce qui cloche.
```

---

## Livrables détaillés

1. **L0 — Note de lecture `extract_facts`** — 3 hypothèses (sortie unique, fallback distinguable, texte non tronqué) tranchées par lecture du code. `XS`
2. **L1 — Schéma `LLMTrace`** — Pydantic 9 champs, décision `offer_id` actée. `XS`
3. **L2 — Helper `_write_trace`** — append JSONL, `try/except` non bloquant, testé isolément. `S`
4. **L3 — Instrumentation `extract_facts`** — capture interne avant `return`, signature inchangée, `run.py` intact. `S`
5. **L4 — `replay_traces.py`** — racine, lecture seule SQLite, tirage seed-fixe, n'écrit pas `offers`. `S`
6. **L5 — `.jsonl` peuplé** — 15-20 traces valides à 9 champs. `XS`
7. **L6 — Handoff** — state à jour, suite = lecture des traces (hors chantier). `XS`

---

## Dépendances critiques

- L0 bloque tout : si une hypothèse risquée tombe (notamment fallback indistinguable), L3 change de forme.
- L1 bloque L2 (le helper sérialise le schéma) et L3 (l'instrumentation construit le schéma).
- L2 testé bloque L3 (ne pas toucher `extract_facts` avant que l'écriture soit sûre et non bloquante).
- L3 bloque L4 (le re-jeu ne produit des traces que si la fonction est instrumentée).
- L4 bloque L5 (le corpus est la sortie du script).

Chemin critique : `L0 → L1 → L2 → L3 → L4 → L5`.

---

## Garde-fous

- **§4 sacré** : la capture est interne à `extract_facts` (ingestion). Aucune capture au rescore. Si on se surprend à vouloir tracer un recalcul de score profil-dépendant → frontière violée, stop.
- **Fidélité du `raw`** : capturer la réponse brute AVANT tout strip/regex/parse. Si on est tenté de nettoyer le `raw` "pour qu'il soit lisible" → c'est exactement ce qui re-cache le bug, stop.
- **Effet de bord non bloquant** : une panne d'écriture de trace ne doit JAMAIS faire échouer une extraction. Le `try/except` de `_write_trace` est obligatoire.
- **Canal séparé** : la trace n'écrit que dans `data/traces/*.jsonl`. Jamais dans `offers`, `verdicts`, `human_reviews`. Le re-jeu ne mute pas la base.
- **Anti scope-creep** : pas de correction des défauts (texte au milieu, fallback silencieux, `[:1500]`), pas de refonte, pas d'eval auto, pas de LLM-judge, pas de dashboard, pas de décision sur l'appel B mort. Le chantier s'arrête à : traces capturées + lisibles. Si on se surprend à "reconceptualiser intégralement" → Distraction (Wyss) + légiférer avant error analysis (Husain), stop.
- **Schéma cible / architecture.md** : toute évolution (dont le param `offer_id` sur la signature) = validation humaine explicite avant code (`rules/workflow.md`).
