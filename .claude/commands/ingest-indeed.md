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

### 2. Filtrage des offres déjà connues (dédup amont)

Avant d'appeler Job Detail, filtre les offres déjà présentes en base via l'API locale :

1. Construis un JSON array à partir des résultats Job Search :
   ```json
   [{"title": "...", "company": "...", "location": "..."}, ...]
   ```
   L'ordre des éléments DOIT correspondre exactement à l'ordre des résultats Job Search.

2. Appelle l'endpoint de dédup :
   ```bash
   curl -s -X POST http://localhost:8000/offers/check-known \
     -H "Content-Type: application/json" \
     -d '[...]'
   ```

3. La réponse contient `new_indices` (positions des offres inconnues), `known_count` et `new_count`.

4. **Si l'API n'est pas accessible** (connection refused, timeout) : log un avertissement `⚠ API indisponible — fallback : Detail sur toutes les offres avec throttle`, et considère TOUTES les offres comme nouvelles. La dédup amont est une optimisation, pas un prérequis.

5. Affiche le résultat du filtrage : `🔍 Dédup amont : {known_count} offres déjà connues, {new_count} nouvelles à récupérer`.

### 3. Récupération des détails (avec throttle)

Pour chaque offre dont l'index est dans `new_indices` (ou toutes en fallback), appelle **Job Detail** pour obtenir la description complète.

**Throttle obligatoire** : attends **2-3 secondes entre chaque appel Job Detail**. Ce throttle s'applique TOUJOURS, que la dédup ait filtré ou non, y compris en fallback. C'est le dernier rempart anti rate-limit — il ne saute jamais.

Ne PAS appeler Job Detail pour les offres dont l'index n'est pas dans `new_indices` — elles sont déjà en base.

### 4. Écriture du JSONL

Écris un fichier JSONL dans `data/indeed_inbox/` avec le nom `{YYYY-MM-DD_HHMM}.jsonl` (date/heure UTC courante). Le fichier ne contient QUE les offres nouvelles (celles pour lesquelles Job Detail a été appelé).

Si aucune offre nouvelle (toutes filtrées par la dédup), ne crée pas de fichier — affiche `✅ Aucune offre nouvelle, rien à écrire.` et passe directement au résultat.

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

### 5. Résultat

Affiche :
- Le nombre d'offres trouvées par Job Search
- Le nombre d'offres filtrées (déjà connues)
- Le nombre d'offres nouvelles récupérées via Job Detail
- Le chemin du fichier JSONL produit (ou mention qu'aucun fichier n'a été créé)
- Rappelle : `python -m orchestrator.job_search.run` pour ingérer les offres dans le pipeline.

## Fréquence suggérée

1 à 2 fois par semaine, en complément du run matinal France Travail + Remotive. Les offres Indeed ne changent pas aussi vite que France Travail.

## Vérification

Pour vérifier que le JSONL est valide :
```bash
python -c "import json; [json.loads(l) for l in open('data/indeed_inbox/FICHIER.jsonl')]"
```
