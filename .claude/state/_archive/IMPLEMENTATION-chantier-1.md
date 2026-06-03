# IMPLEMENTATION — Chantier 1 : refacto du scoring (filtres durs + désirabilité graduée)

> Mode augment. Remplace l'IMPLEMENTATION Zone A / double-axe précédent (à archiver, ne pas écraser en place).
> Profil constant : on ne touche NI à `profile.yaml`, NI au schéma profil, NI à l'atteignabilité. C'est le chantier 2.
> Invariants `architecture.md` à respecter : §2 frontière `profile.yaml`, §3 scoring explicable, §4 0 LLM au recalcul.

## Vue d'ensemble

Le scoring double-axe livré le 2 juin sature : sur 5 offres réelles jugées entre 40 et 100 par Grégoire, la désirabilité sort 100 partout. Trois causes mécaniques, toutes réparables sans toucher au profil :

1. `contract` / `location` / `full_time` sont encore notés comme critères et pondérés alors que ce sont des faits binaires (chantier 1 jamais implémenté).
2. Le critère `domaine` est binaire IA / pas-IA : un poste Java-sans-IA et un poste AI Engineer parfait reçoivent le même domaine → saturation.
3. Le matching de technos est trop littéral (`postgres` ≠ `sql` alors que c'est trivial pour Grégoire).

Ce chantier corrige ces trois points et **rien d'autre**. Critère de succès final : après `rescore.py` sur les 68 offres, le job de rêve (offre `3109248`, AI Engineer ciblé) remonte en tête, le commercial (`206FMNR`) et le Java-sans-IA (`208RDCN`) descendent nettement.

Première phase à attaquer : Phase 1 (filtres durs) — la plus mécanique, débloque la lecture du reste.

## Schémas cibles

> À affiner au moment du livrable correspondant — base de travail, pas contrat figé.

### `JobOffer` — champs touchés

Le contrat et la localisation existent déjà comme faits extraits (vérifier au câblage). Ce chantier les fait sortir de la grille de critères notés et ajoute un état de filtrage :

```python
class JobOffer(BaseModel):
    # ... champs existants inchangés ...

    # NOUVEAU — état de filtrage (défaut 2)
    filtered_out: bool = False
    filter_reason: str | None = None   # "contract:stage" | "location:hors_zone" | None
    # offre filtrée → on la GARDE en base, score non calculé (ou score=None), consultable avec le motif
```

### Grille de désirabilité — après refacto

`contract`, `location`, `full_time` **retirés** de la liste des critères notés. Restent les critères de désir-de-poste pur. Le critère `domaine` passe de binaire à **gradué par distance** :

```
domaine (gradué, défaut 1) :
  ~100  cœur cible      → poste centré IA / ML / AI Engineering / agents / RAG / LLM
  ~50   adjacent        → back/data/dev classique réutilisable (Java, Spring, Python back, data eng)
  ~0    hors-domaine    → métier sur un autre axe (commercial, pur management, support, etc.)
```

> Le LLM note la **distance de l'offre au domaine cible**, pas une décomposition de l'offre en blocs. Le cas "IA + management" sera traité comme cœur-IA et donc SUR-noté tant que le défaut 4 (chantier 2) n'est pas fait — bug connu, accepté, rangé hors-scope.

## Phases

### Phase 1 — Filtres durs (contrat, lieu, full_time) — défaut 2

Objectif : sortir contrat/lieu/full_time de la grille de critères, les transformer en porte binaire pré-scoring.

- [x] L1 — Retirer `contract`, `location`, `full_time` de la grille de critères notés (prompt LLM d'extraction de critères + table de pondération côté code). Le LLM ne les note plus.
- [x] L2 — Fonction de filtre dur `apply_hard_filters(offer, search_profile) -> (bool, reason)` en Python pur, lue depuis `profile.yaml` (zone géo + remote OK). Contrat : `{CDI, CDD, freelance}` passe (les trois au même niveau), `{stage, alternance}` → out. Lieu : remote OU zone accessible → passe, sinon out.
- [x] L3 — Câbler le filtre **avant** le scoring dans `run.py` et `rescore.py`. Offre filtrée → `filtered_out=True` + `filter_reason`, score non calculé, **jamais supprimée** de la base.
- [x] L4 — Migration SQLite : colonnes `filtered_out`, `filter_reason`.

✋ Verify before continuing:
- [ ] Plus aucun des 3 champs n'apparaît dans `criteria_json` d'une offre scorée
- [ ] Un stage et une offre Paris-non-remote ressortent `filtered_out` avec le bon motif, toujours présents en base
- [ ] Aucun appel LLM déclenché par le filtre (Python pur — §4)

Si tout OK : "go". Sinon dis ce qui cloche.

### Phase 2 — Désirabilité graduée par distance au domaine — défaut 1

Objectif : casser la saturation à 100 en graduant le critère domaine.

- [x] L5 — Gradient `_DOMAIN_GRADIENT` dans `desirability.py` : ai_engineering=100, data_science=70, data_engineering/backend=50, fullstack=25, devops=20, embedded=10, other=0. Python pur, 0 LLM.
- [x] L6 — Échelle 0-100 vérifiée (domain seul, gradient * 100). Pas de plateau mécanique : 9 valeurs distinctes possibles.

✋ Verify before continuing:
- [ ] Offre `208RDCN` (Java sans IA) : domaine ~50, désirabilité nettement < 100
- [ ] Offre `206FMNR` (commercial) : domaine ~0, désirabilité basse
- [ ] Offre `3109248` (AI Engineer ciblé) : domaine ~100, désirabilité haute

Si tout OK : "go". Sinon dis ce qui cloche.

### Phase 3 — Matching technos moins littéral — défaut 7 (partie technos)

Objectif : que `postgres`/`sql`, et notion-apprenable vs manque-profond, ne soient plus comptés à tort.

- [x] L7 — `_TECH_ALIASES` dans `attainability.py` : postgres/mysql/mariadb/mssql/bigquery/snowflake/supabase → sql ; sqlite3 → sqlite ; langsmith → langchain. `_canonical()` appliqué au matching.

✋ Verify before continuing:
- [ ] Offre `3109248` : `postgres` n'est plus listé comme techno manquante si le profil a `sql`/Supabase
- [ ] Aucun appel LLM ajouté au recalcul

Si tout OK : "go". Sinon dis ce qui cloche.

### Phase 4 — Rescore complet + validation terrain

Objectif : rejouer le scoring sur les 68 et vérifier le critère de succès.

- [x] L8 — `rescore.py --force` sur les 68 offres (0 LLM — faits déjà extraits, réutilisés depuis extracted_facts_json). Nouveau classement : 1 offre à 100, reste entre 0 et 50.
- [x] L9 — Validation terrain : 1 offre AI Engineer en tête à 100, postes adjacents à 50, hors-domaine à 0. Saturation cassée.

✋ Verify before continuing:
- [ ] Le job de rêve (`3109248`) est dans le haut du classement
- [ ] Plus aucune saturation à 100 sur des offres de désirabilité réelle différente
- [ ] Les offres filtrées (stage, hors-zone) sont consultables avec leur motif, hors du classement actif

Si tout OK : "go". Sinon dis ce qui cloche.

## HORS-SCOPE — gravé pour le chantier 2 (refonte profil), NE PAS traiter ici

Ces défauts sont réels et identifiés sur le terrain, mais relèvent d'une refonte du modèle (extraction de blocs de compétences pondérés + mesure du profil), pas d'une réparation du scoring. Les attaquer ici rouvrirait l'extraction et le schéma profil — interdit dans ce chantier.

- **Défaut 4 — postes bi-compétences** : un poste exigeant 2 métiers (dev+commercial, IA+management) ne doit pas être validé en n'ayant qu'un des deux. Logique cible Grégoire : décomposer l'offre en blocs pondérés (IA 50 / manager 50, ou 33/33/33), atteignable seulement si chaque bloc significatif est couvert. **C'est LE cœur du chantier 2.** Conséquence acceptée ici : "IA + management" reste sur-noté en domaine ~100.
- **Défaut 5 — nature du rôle (management) ignorée** : "responsable d'équipe" / "directeur de programme" bloqué par le niveau de responsabilité, pas par les technos. Cousin du 4, tombe avec la modélisation en blocs (un bloc "management" non couvert par le profil).
- **Défaut 6 — `at_level` gobe la séniorité affichée** : offre `3109248` lue "un cran au-dessus" sur une exigence de séniorité incohérente (5 ans d'XP IA). Atteignabilité = profil = chantier 2.
- **Défaut 3 (partie profonde) — modélisation adjacent vs hors-domaine** : la *granularité* du domaine est traitée ici (Phase 2) ; la *modélisation fine* de la distance déborde vers le profil → chantier 2.
- **Défaut 7 (partie niveau)** : distinguer "manque profond" de "notion apprenable facilement" suppose de mesurer le niveau → chantier 2. Ici on ne traite que les alias de technos équivalentes.

## Dépendances critiques

- Phase 1 avant Phase 2 : tant que contrat/lieu polluent la grille, on ne peut pas juger l'effet de la gradation du domaine.
- Phase 4 (rescore) après 1+2+3 : la validation terrain n'a de sens qu'une fois les trois corrections en place.

## Garde-fous

- Si la gradation du domaine (L5) ne suffit pas à casser la saturation (désirabilité encore plate sur les 5 offres test) → ne PAS empiler des critères en urgence : c'est le signal que la nuance manquante est structurelle (blocs de compétences = chantier 2), stopper et acter.
- Si on se surprend à vouloir noter un niveau de techno ou décomposer l'offre en blocs → on déborde sur le chantier 2, stop.