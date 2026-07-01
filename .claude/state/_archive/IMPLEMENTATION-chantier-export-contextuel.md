# IMPLEMENTATION — Export contextuel d'offres pour LLM

## Vue d'ensemble

Remplacer le lien statique "Export calibration" par un **export à la carte** : exporte les offres actuellement affichées (filtrées par la vue active + filtres), avec choix des champs à inclure par offre. Le texte est copié dans le presse-papier, prêt à coller dans un LLM. Le titre est toujours inclus ; les autres champs (description, techs, role, domain, catégorie, localisation, contrat, url, entreprise) sont optionnels.

L'endpoint `/export/calibration` existant **reste en place** (usage différent : calibration IA/humain).

## Schémas cibles

_Base de travail, pas contrat figé — à affiner au livrable correspondant._

### Endpoint `GET /export/offers`

Mêmes query params de filtre que `GET /offers` (remote, source, verdict, category, hors_perimetre, etat_review, q, sort, order) + param supplémentaire :

```
include: str  # comma-separated, valeurs possibles :
              # description, techs, role, domain, category, location, contract, url, company
              # défaut si absent : "company,category,techs"
```

Retourne `PlainTextResponse` (text/plain, format Markdown compact).

### Format de sortie (Markdown)

```markdown
# Export — N offre(s)

## Développeur Python IA — Acme Corp
- Catégorie : parfait
- Techs : python (core), fastapi (required), docker (nice_to_have)
- Domaine : ai_engineering
- Role : ic

[description si demandée, en bloc]

## Data Engineer Senior — BigData SA
...
```

## Phases

### Phase 1 — Backend : endpoint `/export/offers` (L1–L3)

- [x] **L1** — Endpoint `GET /export/offers` dans `api/export.py` : réutilise la logique de filtre de `list_offers` (extraction dans helper partagé ou duplication légère), jointure sur `extracted_facts_json` + `description` quand demandés par `include`. Retourne du Markdown compact.
- [x] **L2** — Formatage Markdown par offre : titre toujours, champs optionnels selon `include`. Techs formatées avec importance si disponible. Description en bloc texte (pas de troncature).
- [x] **L3** — Test manuel : `curl "localhost:8000/export/offers?category=parfait&include=techs,domain"` retourne le markdown attendu.

✋ Verify before continuing:
- [ ] `curl localhost:8000/export/offers` retourne du markdown avec les offres filtrées
- [ ] `include=techs` n'inclut que titre+entreprise+techs, pas la description
- [ ] Les filtres (category, remote, etc.) réduisent bien le résultat

### Phase 2 — Frontend : composant ExportPopover + intégration (L4–L6)

- [x] **L4** — Composant `ExportPopover.vue` : popover déclenché par un bouton "Exporter", contient des checkboxes pour chaque champ optionnel (description, techs, role, domain, catégorie, localisation, contrat, url, entreprise). État local, pas de store.
- [x] **L5** — Logique d'export : au clic "Copier", construit l'URL avec les filtres actifs du store + les champs cochés, fetch le endpoint, copie le résultat dans `navigator.clipboard.writeText()`, feedback visuel "Copié !".
- [x] **L6** — Intégration dans `index.vue` : remplacer le lien `<a>` "Export calibration" par le composant `ExportPopover`. Le lien calibration reste accessible (déplacé ou retiré du header, à voir).

✋ Verify before continuing:
- [ ] Le popover s'ouvre, les checkboxes fonctionnent
- [ ] Clic "Copier" → le markdown est dans le presse-papier
- [ ] Les filtres actifs (vue + FiltersPanel) sont respectés dans l'export
- [ ] L'ancien `/export/calibration` reste fonctionnel

## Livrables détaillés

1. **L1** — Endpoint export/offers avec filtres — done : retourne du PlainTextResponse markdown filtré — **S**
2. **L2** — Formateur markdown à la carte — done : champs inclus/exclus selon `include` — **S**
3. **L3** — Test manuel curl — done : résultat conforme aux attentes — **XS**
4. **L4** — Composant ExportPopover.vue — done : popover avec checkboxes, état local — **S**
5. **L5** — Logique fetch + clipboard — done : copie fonctionnelle avec feedback — **S**
6. **L6** — Intégration index.vue — done : bouton en place, lien calibration conservé — **XS**

## Dépendances critiques

- L4–L6 dépendent de L1–L3 (le frontend appelle le nouvel endpoint).

## Garde-fous

- Si le volume d'offres exportées dépasse ~500 et que le clipboard plante → ajouter un param `limit` côté API (pas anticipé, ajouté au besoin).
