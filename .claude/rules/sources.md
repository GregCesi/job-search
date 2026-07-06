---
paths: ["orchestrator/**"]
---

# Sources — contrat adapter & fingerprint

## Contrat fingerprint

Toute source **doit** produire son fingerprint via la fonction partagée `sources/fingerprint.py:fingerprint()`. Jamais de réimplémentation locale du hash — la dédup cross-source repose sur l'unicité de la formule. Voir `docs/CODEMAP.md` §Dédup pour le pointeur.

## Checklist nouvelle source

1. Implémenter `Source` (ABC dans `sources/base.py`) : méthode `fetch() -> list[JobOffer]`
2. Mapping brut → `JobOffer` dans une méthode `_map()` **interne à l'adapter**. Aucun champ natif ne fuit dans le pipeline aval (cf. `architecture.md` §1)
3. Description : stocker `description_raw` (brut immuable) + `description` (Markdown via `html_to_markdown()` si HTML source). Nettoyage HTML spécifique à la source dans l'adapter, pas de passe générique aval
4. Fingerprint : appeler `fingerprint(title, company, location)` — ne pas recalculer le hash
5. `source_id` : identifiant stable propre à la source (ID natif si disponible, hash fallback sinon)
6. Ajouter l'appel dans `run.py` (bloc fetch, lignes ~66-79)
