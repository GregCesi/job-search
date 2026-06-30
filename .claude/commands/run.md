---
description: Run complet quotidien — fetch Indeed MCP → JSONL, puis pipeline orchestrator (France Travail + Remotive + Indeed fichiers → dédup → extraction → scoring → digest)
---

# Run complet quotidien

Exécute les deux phases en séquence.

## Phase 1 — Récupération des offres Indeed via MCP

### 1.1 Recherche d'offres

Appelle le MCP Indeed **Job Search** avec ces paramètres :

- **Mots-clés** : `$ARGUMENTS` (si vide, utiliser "python developer", "data engineer", "machine learning engineer")
- **Localisation** : Strasbourg, France (ou "remote")
- **Nombre** : 20-50 offres max par recherche

### 1.2 Récupération des détails

Pour chaque résultat du Job Search, appelle **Job Detail** pour obtenir la description complète.

### 1.3 Écriture du JSONL

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
- `_raw` contient la réponse MCP complète, sans tri ni exclusion.
- Ne PAS écrire en base SQLite — c'est le pipeline qui décide.
- Ne PAS filtrer ou exclure des offres à cette étape.

### 1.4 Bilan intermédiaire

Affiche le nombre d'offres récupérées et le chemin du fichier JSONL.

## Phase 2 — Pipeline orchestrator

Lance le pipeline complet (France Travail + Remotive + Indeed fichiers → dédup → extraction → scoring → digest) :

```bash
python -m orchestrator.job_search.run --profile profiles/gregoire.yaml
```

Affiche le résultat du pipeline.
