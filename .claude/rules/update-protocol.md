# Protocole de mise à jour de l'état du projet

Après chaque livrable terminé, AVANT d'attendre validation humaine :

1. **Cocher le livrable** dans `.claude/state/IMPLEMENTATION.md` (str_replace `- [ ]` → `- [x]`)
2. **Mettre à jour `.claude/state/STATE.md`** : sections "Dernière action" et "Prochaine action"
3. **Si décision architecturale prise** : ajouter une ligne datée dans `.claude/state/DECISIONS.md`

Sans ces 3 étapes, le livrable n'est PAS considéré terminé. Le `/handoff` de fin de session refusera de clôturer si IMPLEMENTATION.md et STATE.md ne sont pas alignés avec le code.
