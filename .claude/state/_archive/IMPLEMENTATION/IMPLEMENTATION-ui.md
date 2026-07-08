# IMPLEMENTATION — Interface de pilotage (Zone A)

> Chantier UI du projet `job-search`. Plan d'exécution séquencé.
> Lecture obligatoire avant toute action. Ne jamais déroger sans validation explicite.
> Schémas ci-dessous = base de travail à affiner au livrable correspondant, pas contrat figé.

## Vue d'ensemble

Ajouter une interface web de consultation des offres au-dessus de l'orchestrateur CLI existant. Deux briques nouvelles : `api/` (FastAPI, lit `data/job_search.sqlite`, écrit verdicts + marqueur `seen`) et `web/` (Nuxt 3, consomme l'API). L'orchestrateur `job_search/` n'est PAS modifié. Finalité : balayer les offres du matin, déplier le scoring par critère, poser des verdicts — et servir de socle d'observation pour l'itération future sur l'orchestrateur.

Première phase à attaquer : **Phase 0 — schéma + setup API**, car tout le reste lit la base et l'API.

## Contrat d'entrée (état de départ vérifié AVANT toute action)

L'arborescence suivante doit exister telle quelle. Si un élément manque, STOP et le signaler — ne rien improviser.

```
job-search/
├── job_search/        # package CLI (sources/, storage/, matching/, scoring/, digest/, run.py, verdict.py, view.py)
├── data/
│   ├── job_search.sqlite     # base principale : tables offers + verdicts
│   └── chroma/               # ChromaDB — NE JAMAIS toucher directement
├── profiles/gregoire.yaml
├── requirements.txt
└── .claude/
```

Vérification : `python -m job_search.run --help` répond, et `data/job_search.sqlite` contient les tables `offers` et `verdicts`.

## Périmètre — ce qui est DANS / HORS

DANS (V1) : tableau filtrable/triable, vues prédéfinies, page détail d'une offre avec critères dépliés, pose de verdict, marqueur `seen`.

HORS (→ chantier suivant "boucle d'itération") : notation manuelle humaine vs IA, suivi de candidature avec CV/LM, évolution de l'orchestrateur, vues personnalisables/persistées, responsive mobile, déploiement, auth.

## Invariants de ce chantier

- **L'orchestrateur `job_search/` n'est jamais modifié.** L'API est un consommateur read-only du travail de l'orchestrateur.
- **L'API ne réécrit jamais ce que l'orchestrateur produit** : `score`, `criteria_json`, et toutes les colonnes d'offre sont en lecture seule côté API. L'API n'écrit QUE `verdicts` (statut humain) et `offers.seen` (marqueur d'interaction UI). Précision de la règle "lecture seule sur offers" de architecture.md : `seen` est une donnée d'interaction, pas une donnée métier de l'orchestrateur.
- **Un verdict courant unique par offre** : poser un statut fait un UPSERT, pas un INSERT cumulatif. La table `verdicts` n'accumule pas l'historique en V1.
- **Le détail du scoring vit dans la page détail, pas dans le tableau.** Le tableau reste léger (score coloré). Le `criteria_json` n'est servi que par `GET /offers/{id}`.

## Schémas cibles

### Migration SQLite (L0)
```sql
-- idempotent : ne s'exécute que si la colonne n'existe pas déjà
ALTER TABLE offers ADD COLUMN seen INTEGER NOT NULL DEFAULT 0;
```
Vérifié par : `.schema offers` montre `seen`, et les offres existantes sont à `seen=0`.

### Statuts de verdict (en dur, V1)
`favori` | `rejeté` | `candidaté` | `masqué`
- `masqué` = soft delete : l'offre disparaît des vues par défaut mais reste en base (signal d'apprentissage préservé).
- Absence de verdict = état "à traiter".

### Pydantic API (à affiner au L1)
```python
# Réponse liste (tableau) — léger, PAS de criteria_json ni description
class OfferRow(BaseModel):
    id: int
    title: str | None
    company: str | None
    location: str | None
    remote: bool
    contract_type: str | None
    score: float | None
    verdict: str | None        # statut courant ou None
    seen: bool
    fetched_at: str

# Réponse détail — complet
class CriterionScore(BaseModel):
    key: str
    score: float
    justification: str
    parse_failed: bool = False

class OfferDetail(OfferRow):
    description: str | None
    url: str | None
    source: str
    criteria: list[CriterionScore]   # criteria_json parsé

class VerdictIn(BaseModel):
    status: Literal["favori", "rejeté", "candidaté", "masqué"]
```

### Vues prédéfinies (presets de filtres, en dur)
Une vue = un préréglage de filtres sur le moteur unique. Aucune logique dupliquée.
- **À traiter** : `seen=0`, tri score décroissant
- **Top scores** : `score >= 80`, tri score décroissant
- **Favoris** : `verdict = favori`
- **Tout** : aucun filtre, filtres manuels disponibles

## Phases

### Phase 0 — Schéma + setup API (objectif : la base a `seen`, l'API démarre et lit la base)
Durée estimée : XS (~30 min)
- [x] L0 — Script de migration idempotent ajoutant `offers.seen` (check existence colonne avant ALTER). Exécuté, vérifié.
- [x] L1 — Setup `api/` : app FastAPI, module de connexion SQLite (chemin `data/job_search.sqlite`), CORS pour le front Nuxt (localhost:3000), schémas Pydantic (`OfferRow`, `OfferDetail`, `CriterionScore`, `VerdictIn`). Route `GET /health` qui répond.

✋ Verify before continuing:
- [ ] `.schema offers` montre la colonne `seen`, les 28 offres sont à `seen=0`
- [ ] `uvicorn api.main:app` démarre sans erreur, `GET /health` répond 200
- [ ] `requirements.txt` mis à jour (fastapi, uvicorn)

Si OK : "go". Sinon dis ce qui cloche.

### Phase 1 — Endpoints lecture + écriture (objectif : l'API expose offres, détail, verdict)
Durée estimée : S (~1h)
- [x] L2 — `GET /offers` : liste `OfferRow`. Supporte query params de filtrage (score_min, score_max, remote, source, verdict, seen, q texte sur title+company) et de tri (sort, order). Jointure verdict courant.
- [x] L3 — `GET /offers/{id}` : `OfferDetail` complet, `criteria_json` parsé en `list[CriterionScore]` (parsing défensif : si JSON cassé, liste vide + log, pas de crash). **Effet de bord : passe `seen=1`.**
- [x] L4 — `PUT /offers/{id}/verdict` (UPSERT) + `DELETE /offers/{id}/verdict` (retour à "à traiter").

✋ Verify before continuing:
- [ ] `GET /offers?sort=score&order=desc` renvoie les 28 offres triées
- [ ] `GET /offers/1` renvoie les 5 critères parsés + description, et l'offre passe à seen=1
- [ ] `PUT /offers/2/verdict {"status":"favori"}` puis re-PUT `rejeté` → un seul verdict courant (UPSERT vérifié en base)

Si OK : "go". Sinon dis ce qui cloche.

### Phase 2 — Setup front Nuxt + store (objectif : le front démarre et parle à l'API)
Durée estimée : S (~45 min)
- [x] L5 — Setup `web/` : Nuxt 3, Tailwind, Pinia. Config base URL API. Store Pinia : state (offers, filtres, vue active, offre ouverte), actions (fetchOffers, openDetail, setVerdict, clearVerdict).

✋ Verify before continuing:
- [ ] `npm run dev` démarre le front
- [ ] Le store fetch `/offers` au montage et log les 28 offres en console

Si OK : "go". Sinon dis ce qui cloche.

### Phase 3 — Tableau + vues + filtres (objectif : la consultation marche)
Durée estimée : M (~1h30)
- [x] L6 — Composant tableau : colonnes title, company, contract_type, location/remote, **score coloré** (vert ≥70 / orange 40-69 / rouge <40 — seuils PROVISOIRES, à recalibrer à l'usage), fetched_at, badge verdict, indicateur seen. Tri par colonne (défaut : score desc). Clic sur une ligne → ouvre le détail.
- [x] L7 — Barre de vues rapides : À traiter / Top scores / Favoris / Tout. Chaque vue applique un preset de filtres sur le store.
- [x] L8 — Panneau de filtres manuels (actif en vue "Tout") : fourchette score, remote, statut verdict, recherche texte title+company.

✋ Verify before continuing:
- [ ] La vue "À traiter" masque les offres déjà consultées
- [ ] Le score s'affiche avec la bonne couleur
- [ ] Un filtre manuel (ex. score_min=50) réduit bien la liste

Si OK : "go". Sinon dis ce qui cloche.

### Phase 4 — Page détail offre (objectif : tout voir sur une offre + agir)
Durée estimée : M (~1h)
- [x] L9 — Page/panneau détail (au clic) : `description` retranscrite, les 5 critères dépliés avec score + justification (transparence totale — on voit lesquels déraillent), lien vers l'annonce web (`url`), boutons de verdict (favori/rejeté/candidaté/masqué + retirer). **Zone réservée V2 présente mais vide** (placeholder commenté : note perso, CV/LM, compétences entretien) — pour matérialiser que la page grandira.

✋ Verify before continuing:
- [ ] Ouvrir une offre affiche les 5 critères avec leurs justifications
- [ ] Poser "favori" met à jour le badge dans le tableau sans recharger la page
- [ ] "masqué" fait disparaître l'offre des vues par défaut, mais elle reste filtrable en vue "Tout"

Si OK : "go". Sinon dis ce qui cloche.

## Livrables détaillés

- **L0** — Migration `seen` — done si `.schema` montre la colonne et offres à 0 — XS
- **L1** — Setup API + Pydantic + /health — done si uvicorn démarre et /health=200 — XS
- **L2** — `GET /offers` filtrable/triable — done si renvoie les 28 offres avec verdict joint — S
- **L3** — `GET /offers/{id}` + effet seen — done si critères parsés + seen passe à 1 — S
- **L4** — verdict UPSERT + DELETE — done si re-poser un statut remplace l'ancien — S
- **L5** — Setup Nuxt + Pinia + store — done si fetch /offers visible en console — S
- **L6** — Tableau trié + score coloré + clic détail — done si les 28 lignes s'affichent triées — M
- **L7** — Vues rapides — done si les 4 vues filtrent correctement — S
- **L8** — Filtres manuels — done si chaque filtre réduit la liste — M
- **L9** — Page détail + verdicts + zone V2 vide — done si critères visibles + verdict réactif — M

## Dépendances critiques
- L0 bloque tout (la colonne seen est lue partout)
- L1 bloque L2, L3, L4 (pas d'API sans setup)
- L2 bloque L6 (pas de tableau sans données)
- L5 bloque L6, L7, L8, L9 (pas de front sans setup)

## Garde-fous
- Si le parsing de `criteria_json` échoue sur plusieurs offres (L3) → ne pas crasher, liste de critères vide + flag visible côté UI. Noter combien d'offres sont concernées (signal pour le tuning prompt côté orchestrateur, chantier suivant).
- Si Phase 3 (tableau) déborde largement → livrer le tableau + vues (L6, L7), reporter les filtres manuels (L8) au besoin. Le tableau + vues seul est déjà utilisable.
- Seuils de couleur score (L6) : PROVISOIRES. Ne pas les graver comme une décision — ils se recalibreront à l'usage réel, dans le chantier d'itération.