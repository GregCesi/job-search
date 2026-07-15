# Premier prompt — session refonte scoring double-axe

> À copier-coller dans Claude Code pour démarrer le cycle. Setup data uniquement, pas d'étage LLM.

---

Lis CLAUDE.md, `.claude/rules/architecture.md` (le §4 est nouveau et central), puis `.claude/state/IMPLEMENTATION.md` et `.claude/state/STATE.md`. Ce sont les documents de référence — ne jamais y déroger sans validation explicite.

On démarre la refonte du scoring : remplacer le score unique par deux axes (désirabilité + atteignabilité). Règle absolue : le LLM extrait des faits une seule fois à l'ingestion, tout le scoring dépendant du profil est calculé en Python (architecture.md §4).

Tâche de cette session : **Phase 1 — Fondations data**, en commençant par le livrable bloquant **L2**.

**L2 — Vérification du payload natif France Travail (d'abord, bloquant)**
Inspecte le code de l'adapter `FranceTravailSource` existant et un échantillon de payload réel déjà récupéré (ou la doc du schéma Offres v2). Produis une note écrite : quels faits sont déjà structurés nativement (localisation, type de contrat, expérience exigée, taille d'entreprise…) et lesquels devront être extraits par LLM. Cette note conditionne L1 et L3.

Stop après L2. Ne PAS écrire `JobOffer` étendu (L1) ni l'étage d'extraction (L3) tant que la note n'est pas validée — on a besoin de savoir ce qui est gratuit avant de décider quoi déléguer au LLM.

✋ Verify before continuing:
- [ ] La note liste clairement champs natifs vs champs à extraire
- [ ] Le verdict sur séniorité/expérience exigée est tranché (natif ou LLM ?)
- [ ] Aucun fichier de code modifié à ce stade

Si OK : "go" → on enchaîne sur L1 + L4. Sinon dis ce qui cloche.
