# Workflow Claude Code

- **Une étape à la fois.** Validation explicite avant la suivante, jamais d'enchaînement multi-étapes sans confirmation.
- **str_replace ciblé.** Modifier les blocs concernés uniquement, pas de réécriture de fichier sauf création.
- **Pas de préambule, pas de postambule.** Le résultat parle de lui-même.
- **Demander une validation humaine uniquement aux points de validation explicites d'IMPLEMENTATION.md** ou si une décision change CLAUDE.md / IMPLEMENTATION.md / un schéma cible. Sinon enchaîner.
- **Format des points de validation** :
  ✋ Verify before continuing:
  - [ ] critère 1
  - [ ] critère 2

  Si tout OK : "go". Sinon dis ce qui cloche.
