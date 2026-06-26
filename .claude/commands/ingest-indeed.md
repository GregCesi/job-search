---
description: Récupère des offres Indeed via MCP et dépose un JSONL dans data/indeed_inbox/
---

# Récupération d'offres Indeed via MCP

## Prérequis
- Le connecteur Indeed doit être activé dans Claude (Search & Tools → Add connectors → Indeed).
- Ce geste est **manuel par design** : l'API Indeed officielle est fermée depuis 2023, le MCP Indeed est exclusif au connecteur Claude. Il n'existe pas d'adapter `Source.fetch()` autonome pour Indeed.

## Instructions

### 1. Recherche d'offres

Appelle le MCP Indeed **Job Search** avec ces paramètres (adapte selon le besoin) :

- **Mots-clés** : `$ARGUMENTS` (si vide, utiliser "python developer", "data engineer", "machine learning engineer")
- **Localisation** : Strasbourg, France (ou "remote")
- **Nombre** : 20-50 offres max par recherche

### 2. Récupération des détails

Pour chaque résultat du Job Search, appelle **Job Detail** pour obtenir la description complète de l'offre.

### 3. Écriture du JSONL

Écris un fichier JSONL dans `data/indeed_inbox/` avec le nom `{YYYY-MM-DD_HHMM}.jsonl` (date/heure UTC courante).

Chaque ligne = un objet JSON avec ces champs :

```json
{
  "indeed_id": "identifiant stable Indeed",
  "title": "titre du poste",
  "company": "nom de l'entreprise",
  "location": "lieu de travail",
  "description": "description complète (HTML ou texte)",
  "url": "URL de l'offre sur Indeed",
  "job_type": "type de contrat si disponible",
  "remote": true,
  "date_posted": "date de publication si disponible",
  "_raw": { "... réponse MCP complète, non filtrée ..." }
}
```

**Règles critiques :**
- `_raw` contient la réponse MCP complète, sans tri ni exclusion (donnée brute sacrée).
- Ne PAS écrire en base SQLite — seul le pipeline (`python -m orchestrator.job_search.run`) décide de ce qui entre en base.
- Ne PAS filtrer ou exclure des offres à cette étape — les filtres sont en aval.

### 4. Résultat

Affiche :
- Le nombre d'offres récupérées
- Le chemin du fichier JSONL produit
- Rappelle : `python -m orchestrator.job_search.run` pour ingérer les offres dans le pipeline.

## Fréquence suggérée

1 à 2 fois par semaine, en complément du run matinal France Travail + Remotive. Les offres Indeed ne changent pas aussi vite que France Travail.

## Vérification

Pour vérifier que le JSONL est valide :
```bash
python -c "import json; [json.loads(l) for l in open('data/indeed_inbox/FICHIER.jsonl')]"
```
