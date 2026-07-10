# STATE — job-search

## Maintenant
- Dernière action : Implémentation staleness + séparation avis IA/humain (L1→L9). Backend : `_derive_review_fields()` enrichi (`suggestion_actuelle`, `review_stale`, état `a_revoir`), filtre SQL `a_revoir` dans list_offers + export. Frontend : bloc "Avis IA" read-only, bloc "Mon avis" éditable, bandeau stale, preset `a_traiter` inclut `a_revoir`.
- Prochaine action : Vérifier manuellement (API + front) — onglet "À traiter" montre les offres stale, bandeau visible, re-confirmation fonctionne.
- Bloquant : aucun

## Phase en cours
- Staleness + séparation avis IA/humain — en vérification manuelle

## Mémoire
- Dernière /memory-update : 2026-06-02 (refonte scoring double-axe livrée)
- Convs post-update à traiter : session chantier 2 complète

## Sessions récentes
- Zone A : sourcing & tri auto livrée (voir `_archive/IMPLEMENTATION-zone-a.md`)
- Cockpit web Zone A livré (Nuxt 4, read-only)
- Refonte scoring double-axe : LIVRÉE ✓ (2026-06-02, L1→L13, 68 offres scorées)
- Rituel calibration : LIVRÉ ✓ (2026-06-03, C-1→C-4, L1→L12)
- Chantier 2 profil + catégorisation : LIVRÉ ✓ (2026-06-03, L1→L16+L18)
- Chantier traces viewer : LIVRÉ ✓ (2026-06-10, L1→L11)
- Chantier hors-périmètre : LIVRÉ ✓ (2026-06-12, L0→L8, 9 offres gatées)
- Chantier review humaine : LIVRÉ ✓ (2026-06-15, L1→L12, scoring supprimé + review catégorie + facts/badges)
- Adapter Remotive + multi-source : LIVRÉ ✓ (2026-06-16, L1→L3, 2e source pluggée)
- Chantier bouton trace : LIVRÉ ✓ (2026-06-17, L1→L5, lien offre→traces avec ancrage)
- Chantier HTML→Markdown : LIVRÉ ✓ (2026-06-17, L0→L9, descriptions Remotive nettoyées, rendu MD front)
- Chantier canonicalisation techs : LIVRÉ ✓ (2026-06-18, L0→L8, alias.yaml externe, canonicalize() deux côtés, rapport unmatched, 108 offres rescorées)
- Chantier divergence front : LIVRÉ ✓ (2026-06-25, L0→L7, back source unique matching techs, profil retiré du front)
- Chantier source Indeed : LIVRÉ ✓ (2026-06-26, L2→L9, adapter fichier + commande MCP, 60 offres Indeed)
- Chantier dédup amont Indeed : LIVRÉ ✓ (2026-06-26, L0→L2, fingerprint partagé, endpoint check-known, skill v2 throttle+dédup)
- Chantier export contextuel : LIVRÉ ✓ (2026-06-30, L1→L6, endpoint export/offers + ExportPopover front)
