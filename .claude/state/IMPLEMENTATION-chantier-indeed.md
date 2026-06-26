# IMPLEMENTATION — Chantier source Indeed (via MCP, orchestration Claude)

> Coexiste avec `IMPLEMENTATION-chantier-divergence-front.md` (chantier indépendant, en attente).
> Invariants `architecture.md` à respecter : §1 (sources pluggables, schéma neutre JobOffer), §4 (0 LLM au scoring/recalcul), §"Persistance séparée offers/verdicts/human_reviews".
> Contrainte structurante : le MCP Indeed est exclusif au connecteur Claude — pas d'adapter `Source.fetch()` autonome. La récupération est un geste orchestré par Claude, qui dépose un artefact JSONL ingéré ensuite par le pipeline via un adapter fichier.

## Vue d'ensemble

Ajouter Indeed comme source d'offres. L'API officielle est fermée depuis 2023, le scraping écarté. La seule voie légitime est le MCP Indeed officiel, restreint à Claude (claude.ai / Claude Desktop).

**Chaîne en deux temps :**
1. **Récupération** — Claude appelle le MCP Indeed (Job Search + Job Detail), écrit les données brutes dans un JSONL (`data/indeed_inbox/{date}.jsonl`).
2. **Ingestion** — `IndeedFileSource` (adapter `Source`) lit les JSONL et les fait entrer dans le pipeline existant comme France Travail ou Remotive. À partir de là, une offre Indeed est indistinguable d'une autre source.

**Première chose à attaquer : Phase 0 — test de couverture MCP Indeed.** C'est un go/no-go : si les tools Indeed ne renvoient pas assez de champs pour remplir un `JobOffer` (description complète, localisation, entreprise, URL), le chantier s'arrête.

---

## Ancrage sur le code (Phase 0 skill — relecture faite)

| Point | Constat (chemin:ligne) | Conséquence |
|---|---|---|
| Interface Source | `sources/base.py:72-75` — `fetch() -> list[JobOffer]` | L'adapter fichier implémente cette interface, pas un chemin parallèle |
| JobOffer | `sources/base.py:49-69` — 20 champs, `source`/`source_id`/`fingerprint` obligatoires | L'artefact JSONL doit couvrir ces champs ; le mapping vit dans l'adapter |
| Adapters existants | `france_travail.py` (OAuth2, `_map()`), `remotive.py` (public API, inline) | Patron : mapping interne, `_fingerprint()` réutilisable, `html_to_markdown()` disponible |
| Pipeline run.py | `run.py:64-74` — `list[Source]`, `--no-remotive` flag | Ajout naturel de `IndeedFileSource` + `--no-indeed` flag |
| Dédup | `storage/dedup.py:6-26` — `(source, source_id)` + `fingerprint` | Cross-source par fingerprint déjà opérationnel. `source="indeed"` + `source_id` = ID Indeed |
| Extraction LLM | `scoring/extractor.py:102` — `extract_facts(offer: JobOffer)` | Source-agnostic, aucune branche Indeed nécessaire |
| Persistance | `storage/offers.py:27-80` — upsert `UNIQUE(source, source_id)` | Source-agnostic, `source="indeed"` fonctionne directement |
| html_to_markdown | `sources/_clean.py:11-46` — Python pur, idempotent sur texte plat | Réutilisable si Indeed renvoie du HTML |
| DB migration | `db.py:63-109` — pattern `PRAGMA table_info` + `ADD COLUMN` | **Aucune migration nécessaire** — `source` est un TEXT libre, pas d'enum |
| criteria_json | `db.py:96-98` — **droppé** | Mort, pas de réceptacle JSON à enrichir |

---

## Schémas cibles

> Base de travail, pas contrat figé — à affiner au livrable correspondant (notamment après Phase 0 qui confirme les champs MCP réels).

### Artefact JSONL (`data/indeed_inbox/{YYYY-MM-DD_HHMM}.jsonl`)

```jsonl
{"indeed_id": "abc123", "title": "...", "company": "...", "location": "...", "description": "...", "url": "...", "job_type": "...", "remote": true, "date_posted": "...", "_raw": { ... }}
```

- Une ligne JSON par offre, champs normalisés + `_raw` = réponse MCP complète préservée (I3 — donnée brute sacrée).
- Format à confirmer après Phase 0 (les noms de champs dépendent de ce que le MCP renvoie réellement).

### Adapter `IndeedFileSource` (`sources/indeed_file.py`)

```python
class IndeedFileSource(Source):
    def __init__(self, inbox_dir: str = "data/indeed_inbox") -> None: ...
    def fetch(self) -> list[JobOffer]: ...  # lit tous les .jsonl, mappe vers JobOffer
```

- Mapping Indeed → JobOffer dans l'adapter, jamais en aval (§1).
- `source="indeed"`, `source_id` = `indeed_id` du JSONL.
- `fingerprint` via `_fingerprint(title, company, location)` (même logique que FT/Remotive).
- `description_raw` = description brute Indeed, `description` = `html_to_markdown(description_raw)` si HTML.

---

## Phases

### Phase 0 — Test de couverture MCP Indeed (go/no-go, 0 code)

Objectif : vérifier que les tools MCP Indeed renvoient assez de champs pour produire un `JobOffer` exploitable. C'est le **bloquant principal** — si la couverture est insuffisante, le chantier s'arrête.

- [ ] L0 — Connecter Indeed dans Claude (Search & Tools → Add connectors → Indeed). Lancer une vraie recherche (ex. "python developer Strasbourg"). Documenter les champs renvoyés par **Job Search** et **Job Detail** :
  - (a) Description complète disponible ? (Job Detail ou déjà dans Job Search ?)
  - (b) Entreprise, localisation, URL de l'offre ?
  - (c) Type de contrat, remote, date de publication ?
  - (d) Identifiant stable (pour `source_id` + dédup) ?
  - (e) Format de la description (HTML, texte plat, Markdown ?) → décide si `html_to_markdown` s'applique.
- [ ] L1 — Tableau de mapping Indeed → JobOffer : pour chaque champ obligatoire de `JobOffer`, quel champ Indeed le remplit (ou `None` si absent). Identifier les trous.

```
✋ Verify before continuing:
- [ ] Les 5 champs critiques sont couverts : description complète, titre, entreprise, localisation, URL
- [ ] Un identifiant stable existe pour source_id (pas un hash calculé côté client)
- [ ] Les trous identifiés sont acceptables (champs optionnels de JobOffer, pas critiques)
- [ ] Format de la description constaté → html_to_markdown applicable ou non
- [ ] Décision : go (assez de champs) ou no-go (couverture insuffisante → chantier arrêté)

Si go : "go". Si no-go : on documente pourquoi et on ferme le chantier.
```

### Phase 1 — Artefact JSONL + adapter IndeedFileSource

Objectif : l'artefact est défini, l'adapter le lit et produit des `JobOffer`. Aucune intégration pipeline encore — l'adapter est testable isolément.

- [x] L2 — Définir le format JSONL final (basé sur les champs MCP constatés en Phase 0). Créer `data/indeed_inbox/.gitkeep` pour le répertoire.
- [x] L3 — `sources/indeed_file.py` : `IndeedFileSource(Source)` qui lit tous les `.jsonl` de `data/indeed_inbox/`, mappe chaque ligne vers `JobOffer`. Mapping interne (§1), `_fingerprint()` réutilisé, `html_to_markdown()` si HTML. Défensif : skip les lignes mal formées avec `warnings.warn` (même patron que FT/Remotive).

```
✋ Verify before continuing:
- [ ] IndeedFileSource().fetch() retourne des JobOffer valides à partir d'un JSONL de test
- [ ] source="indeed", source_id stable, fingerprint calculé
- [ ] description_raw = brut Indeed préservé (I3), description = Markdown dérivé
- [ ] Lignes malformées skippées sans crash (warnings.warn)
- [ ] Aucun champ/branche "indeed" en aval de l'adapter (I1 — frontière JobOffer)
- [ ] 0 appel LLM dans l'adapter (I4)

Si tout OK : "go". Sinon dis ce qui cloche.
```

### Phase 2 — Intégration pipeline + dédup

Objectif : `IndeedFileSource` branché dans `run.py`, les offres Indeed traversent le pipeline identiquement aux autres sources. Dédup opérationnelle.

- [x] L4 — `run.py` : ajouter `IndeedFileSource()` à la liste `sources` (même pattern que `RemotiveSource`). Flag `--no-indeed` (miroir de `--no-remotive`). Si le répertoire `data/indeed_inbox/` est vide ou n'existe pas, la source retourne `[]` silencieusement.
- [x] L5 — `rescore.py` : vérifier que le rescore fonctionne sur les offres `source="indeed"` (a priori 0 changement — le rescore est source-agnostic, confirmé en relecture).

```
✋ Verify before continuing:
- [ ] python -m orchestrator.job_search.run ingère les offres Indeed du inbox (extract_facts + scoring + save)
- [ ] Relancer le run avec le même JSONL → 0 doublon (I5 — dédup par source+source_id)
- [ ] Une offre Indeed identique à une offre FT (même titre+entreprise+location) → dédupliquée par fingerprint (I5 — cross-source)
- [ ] Aucune branche conditionnelle "si source == indeed" dans run.py, rescore.py, ou l'aval (I1)
- [ ] extract_facts traite les offres Indeed identiquement (I4 — même chemin LLM unique à l'ingestion)
- [ ] 0 écriture directe en base par le geste de récupération (I2 — seul le pipeline écrit)

Si tout OK : "go". Sinon dis ce qui cloche.
```

### Phase 3 — Commande `/ingest-indeed` + documentation

Objectif : le geste de récupération est reproductible via une commande Claude Code documentée (I6). L'artefact produit est inspectable (I2) et préserve les données brutes (I3).

- [x] L6 — `.claude/commands/ingest-indeed.md` : commande qui instruite Claude pour :
  1. Appeler MCP Indeed Job Search (paramètres configurables : mots-clés, localisation)
  2. Pour chaque résultat, appeler Job Detail (description complète)
  3. Écrire le JSONL dans `data/indeed_inbox/{YYYY-MM-DD_HHMM}.jsonl`
  4. Afficher le nombre d'offres récupérées + chemin du fichier
  5. Rappeler de lancer `python -m orchestrator.job_search.run` pour ingérer
- [x] L7 — Documentation du geste dans la commande elle-même : contrainte MCP (pourquoi c'est manuel), prérequis (Indeed connecté dans Claude), fréquence suggérée, et comment vérifier que ça a marché.

```
✋ Verify before continuing:
- [ ] /ingest-indeed exécutable par Claude, produit un JSONL valide dans data/indeed_inbox/
- [ ] Le JSONL contient _raw (réponse MCP complète, I3 — donnée brute préservée)
- [ ] La commande documente le pourquoi du geste manuel (I6 — reproductibilité)
- [ ] Aucune écriture en base par la commande (I2 — séparation récupération/ingestion)
- [ ] Un tiers reprenant le projet peut reproduire le geste en lisant la commande seule (I6)

Si tout OK : "go". Sinon dis ce qui cloche.
```

### Phase 4 — Validation end-to-end + clôture

Objectif : la chaîne complète fonctionne (récupération → artefact → ingestion → scoring → cockpit). Clôture propre.

- [x] L8 — Validation end-to-end : `/ingest-indeed` → JSONL produit → `python -m orchestrator.job_search.run` → offres Indeed visibles dans le cockpit avec catégorie, facts, badges techs. Indistinguables d'une offre FT/Remotive dans l'affichage.
- [x] L9 — Clôture : IMPLEMENTATION coché, STATE.md à jour, décision (MCP deux temps, artefact JSONL, adapter fichier) gravée dans DECISIONS.md.

```
✋ Verify before continuing:
- [ ] Offres Indeed visibles dans le cockpit, catégorisées, avec facts et badges
- [ ] GET /offers et GET /offers/{id} répondent pour les offres Indeed (API non régressée)
- [ ] Relancer /ingest-indeed + run → 0 doublon (I5)
- [ ] DECISIONS.md : chaîne MCP deux temps, artefact JSONL, adapter fichier IndeedFileSource
- [ ] STATE.md à jour

Si tout OK : "go". Sinon dis ce qui cloche.
```

---

## Livrables détaillés

1. **L0 — Test couverture MCP Indeed** — champs renvoyés par Job Search + Job Detail documentés. `XS` (go/no-go)
2. **L1 — Tableau de mapping** — Indeed → JobOffer, trous identifiés. `XS`
3. **L2 — Format JSONL défini** — spec basée sur les champs MCP réels + `.gitkeep`. `XS`
4. **L3 — IndeedFileSource adapter** — `sources/indeed_file.py`, Source implémenté, mapping interne. `S`
5. **L4 — Intégration run.py** — source ajoutée, flag `--no-indeed`. `XS`
6. **L5 — Vérification rescore** — offres Indeed rescorables sans changement. `XS`
7. **L6 — Commande /ingest-indeed** — `.claude/commands/ingest-indeed.md`, orchestration MCP. `S`
8. **L7 — Documentation du geste** — prérequis, contrainte MCP, reproductibilité. `XS`
9. **L8 — Validation end-to-end** — chaîne complète testée sur des offres réelles. `S`
10. **L9 — Clôture** — STATE, DECISIONS à jour. `XS`

---

## Dépendances critiques

- **L0/L1 bloquent tout** : si la couverture MCP est insuffisante, rien ne se code.
- L2 (format JSONL) dépend de L0/L1 (champs réels constatés).
- L3 (adapter) dépend de L2 (format défini).
- L4 (pipeline) dépend de L3 (adapter fonctionnel).
- L6 (commande) dépend de L2 (format JSONL défini) mais indépendant de L4 (peut se faire en parallèle de l'intégration pipeline).
- L8 (validation) après L4 + L6 (chaîne complète nécessaire).

Chemin critique : `L0 → L2 → L3 → L4 → L8`.

---

## Garde-fous

- **Go/no-go Phase 0** : si les tools MCP Indeed ne renvoient pas de description complète ou d'identifiant stable → chantier arrêté, pas contourné. Ne pas inventer de scraping ou de wrapper.
- **Frontière JobOffer sacrée (I1)** : si une branche `if source == "indeed"` apparaît dans le pipeline aval (dedup, extract, score, save, API, front) → frontière violée, stop. Le mapping vit dans l'adapter, nulle part ailleurs.
- **Artefact inspectable (I2)** : la commande écrit un JSONL lisible par un humain. Le pipeline seul décide de ce qui entre en base. Si la commande écrit directement en SQLite → séparation violée, stop.
- **Donnée brute sacrée (I3)** : le JSONL contient `_raw` (réponse MCP complète). Pas de tri, pas d'exclusion, pas de transformation destructive à la récupération. Les filtres restent en aval.
- **0 LLM au scoring (I4)** : aucun appel LLM dans l'adapter fichier ni dans le mapping. `extract_facts` s'applique identiquement. Si on se surprend à appeler un modèle dans le chemin Indeed → stop.
- **Dédup existante (I5)** : pas de logique de dédup parallèle propre à Indeed. `filter_new()` fait le travail via `(source, source_id)` + `fingerprint`.
- **Geste documenté (I6)** : la commande est auto-suffisante. Si un tiers doit lire DECISIONS.md ou CLAUDE.md pour comprendre comment récupérer des offres Indeed → documentation insuffisante.
