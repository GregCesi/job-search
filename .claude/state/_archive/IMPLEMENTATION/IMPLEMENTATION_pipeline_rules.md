# IMPLEMENTATION — Cristallisation rules/pipeline.md

## Vue d'ensemble

Les règles du pipeline n'ont jamais été écrites — l'architecture a évolué (abandon embeddings, scoring déterministe, gates à causes, zones en source unique) sans que `.claude/rules/` suive. Ce chantier cristallise le contrat descriptif-normatif du pipeline depuis le code stabilisé (vagues 1-2 livrées), pas depuis l'intention.

Livrable unique : `.claude/rules/pipeline.md`. Zéro code écrit.

## Phases

### Phase 1 — Rédaction de `.claude/rules/pipeline.md` (contrat 6 étages + invariants transversaux)

Format par étage : `CONSOMME / PRODUIT / INVARIANTS / INTERDITS`, avec référence fichier.

- [x] L1 — Étage 1 Fetch : sources pluggables → `list[JobOffer]`. Réf : `sources/base.py` (interface `Source`), `sources/france_travail.py`, `sources/remotive.py`, `sources/indeed_file.py`, `run.py:55-70`. Zones résolues depuis `profile.zones` + `search_criteria.locations`. Mapping natif→`JobOffer` vit exclusivement dans l'adapter. `description_raw` préservé, `description` = Markdown propre (via `_clean.py`).
- [x] L2 — Étage 2 Dédup : fingerprint cross-source + `(source, source_id)`. Réf : `storage/dedup.py`, `sources/fingerprint.py`. Guard intra-batch.
- [x] L3 — Étage 3 Hard filters : localisation (zone dept/keywords ou remote) + contrat (alternance/stage → out, `contract_types` whitelist). Réf : `scoring/filters.py`, profil YAML (`search_criteria.locations`, `search_criteria.contract_types`, `zones`). Offre filtrée → `save_offer(filtered_out=True, filter_reason=...)`, jamais supprimée.
- [x] L4 — Étage 4 Extraction LLM : Ollama, 1 appel/offre, température 0.1, 3 few-shots. Réf : `scoring/extractor.py`, `scoring/tracing.py`. Produit `ExtractedFacts` (seniority, techs w/ importance, domain, role_level, langues_requises, parse_failed). Trace JSONL append (`data/traces/extract_facts.jsonl`). Parsing défensif : retry 2×, fallback `parse_failed=True`, ne crashe jamais.
- [x] L5 — Étage 5 Scoring + gates + catégorisation : Python pur. Réf : `scoring/desirability.py`, `scoring/attainability.py`, `scoring/hors_perimetre.py`, `scoring/categorize.py`, `scoring/aliases.py`. Canonicalisation via `alias.yaml` appliquée au scoring seulement (jamais à l'ingestion). Gate hors-périmètre APRÈS d/a (scores conservés intacts). `perimetre_causes` en liste. 4 catégories via 2 seuils (d>50, a>40).
- [x] L6 — Étage 6 Persistance : `save_offer` UPSERT `ON CONFLICT(source, source_id)`. Réf : `storage/offers.py`, `storage/db.py`. `offers` = seule table de vérité du scoring. `extracted_facts_json`, `category`, `techs_matched/missing_json`, `perimetre_causes` persistés. `verdicts` / `human_reviews` = données d'interaction, jamais intrants de recalcul.
- [x] L7 — Invariants transversaux : 5 invariants payés pendant les vagues, inscrits en section dédiée avec explication courte.
- [x] L8 — Relecture croisée : chaque ligne vérifiable dans le code actuel. Aucune règle « souhaitée mais pas encore vraie ».

✋ Verify before continuing:
- [x] Chaque étage cite au moins un fichier de référence vérifiable dans le code
- [x] Aucune règle n'est un vœu — tout est vrai du code actuel (relecture croisée faite)
- [x] Les 5 invariants transversaux sont inscrits et correspondent au comportement réel
- [x] `architecture.md` n'est pas dupliqué — `pipeline.md` pointe vers les invariants partagés quand pertinent

### Phase 2 — Mise à jour STATE + DECISIONS

- [x] L9 — Mettre à jour `STATE.md` : sections "Dernière action" et "Prochaine action"
- [x] L10 — Ajouter une ligne datée dans `DECISIONS.md` : cristallisation du contrat pipeline dans rules/

✋ Verify before continuing:
- [x] `STATE.md` reflète le chantier terminé
- [x] `DECISIONS.md` a une entrée datée pour la cristallisation

## Livrables détaillés

1. **L1-L6** — 6 blocs d'étage dans `pipeline.md`, format `CONSOMME/PRODUIT/INVARIANTS/INTERDITS` — XS chacun
2. **L7** — Section invariants transversaux — XS
3. **L8** — Relecture croisée (pas de fichier produit, vérification) — XS
4. **L9** — Mise à jour `STATE.md` — XS
5. **L10** — Entrée `DECISIONS.md` — XS

## Dépendances critiques

- L8 (relecture croisée) bloque la validation de Phase 1 — pas de /review avant.

## Garde-fous

- Si une règle décrit un comportement souhaité mais pas encore implémenté → elle va dans `DECISIONS.md` comme dette, pas dans `rules/pipeline.md`.
