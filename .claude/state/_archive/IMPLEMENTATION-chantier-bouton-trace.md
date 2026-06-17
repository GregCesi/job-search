# IMPLEMENTATION — Bouton "voir la trace" sur le side panel offre

> Chantier S. Ajoute dans la meta bar d'`OfferDetail.vue`, à côté du lien France Travail,
> un bouton qui ancre vers le groupe de traces de l'offre dans `/traces`.
> Bouton grisé + tooltip "aucune trace" si l'offre n'en a pas.
> Mode : `augment`. Ne pas régénérer l'infra `.claude/`.

## Nœud d'archi unique (déjà tranché)

La page détail manipule l'`id` SQLite (int). Les traces sont clés par `source_id` (string).
La jointure passe par la table `offers`. **Le front ne connaît pas `source_id` aujourd'hui.**
→ Tout le chantier découle de : exposer `source_id` au front + un endpoint bulk de comptage.

Décisions verrouillées :
- Ancrage vers le **groupe** de traces de l'offre (pas une trace unique), via `/traces#offer-{source_id}`.
- Bouton **grisé + tooltip** si 0 trace (pas masqué — l'absence reste visible).
- Comptage : endpoint **bulk** `GET /traces/counts → {source_id: int}`, parsé 1× du JSONL, mis en cache store.
  Le panel ne lit que `count > 0`. Count exact gardé en réserve (badge futur, gratuit).
- Aucun état dérivé persisté : le count se recalcule à la lecture du JSONL, jamais stocké en base.

---

## Phase 1 — Back : exposer `source_id` + endpoint counts

### L1 — `source_id` dans le schéma `OfferDetail`
- [x] `schemas.py` : ajouter `source_id: str` au modèle `OfferDetail`.
- [x] `api/offers.py` (`GET /offers/{offer_id}`) : inclure `source_id` dans le SELECT et le mapping.
- [x] Vérifier qu'aucun autre appelant de `OfferDetail` ne casse (champ ajouté, non retiré → safe).

### L2 — Endpoint `GET /traces/counts`
- [x] `api/traces_reader.py` : fonction `count_traces_by_offer() -> dict[str, int]`.
      Parse le JSONL une fois, groupe par `offer_id` (= `source_id`), renvoie `{source_id: count}`.
      Lecture défensive identique à l'existant (depuis `__file__`, try/except, fichier absent → `{}`).
- [x] `api/traces.py` : route `GET /traces/counts` qui renvoie le dict.
- [x] Read-only strict. Aucune écriture. Aucun LLM.

**Validation Phase 1** : `curl /traces/counts` renvoie un dict non vide ; `curl /offers/{id}` contient `source_id`.

---

## Phase 2 — Front : store + bouton + ancrage

### L3 — Store : charger les counts une fois
- [x] `stores/offers.ts` : state `traceCounts: Record<string, number>` (clé = `source_id`).
- [x] Action `fetchTraceCounts()` : `GET /traces/counts`, remplit `traceCounts`. Appelée au montage de la liste (`index.vue`), une seule fois.
- [x] Getter ou helper : `hasTraces(sourceId: string): boolean` → `(traceCounts[sourceId] ?? 0) > 0`.

### L4 — Bouton dans la meta bar `OfferDetail.vue`
- [x] Juste après le `<a>` France Travail (ligne ~38), ajouter le bouton "Voir la trace".
- [x] Actif si `hasTraces(offer.source_id)` → `<NuxtLink :to="'/traces#offer-' + offer.source_id">`.
- [x] Inactif sinon → `<span>` grisé (`text-gray-300 cursor-not-allowed`) + `title="Aucune trace pour cette offre"` (tooltip natif suffit, pas de lib).
- [x] Style cohérent avec le lien voisin (même taille, `font-medium`). Gérer le `ml-auto` :
      le déplacer sur un wrapper `<div class="ml-auto flex items-center gap-3">` englobant les deux,
      plutôt que sur le seul lien France Travail.

### L5 — Ancrage cible dans `traces.vue`
- [x] Sur le `<div v-for="group in groups">` (ligne ~27) : ajouter `:id="'offer-' + group.offer_id"`.
- [x] `onMounted` : lire `useRoute().hash`. Si présent (`#offer-XXX`) :
      1. **déplier d'abord** le groupe ciblé (forcer l'état d'expansion de CE groupe — sinon scroll vers accordéon fermé),
      2. puis `scrollIntoView({ behavior: 'smooth', block: 'start' })` sur l'élément.
      Séquencer le scroll après le tick de dépliage (`await nextTick()`), sinon la hauteur change pendant le scroll.
- [x] Si le hash pointe vers un `offer_id` absent (offre sans trace, lien forcé à la main) → no-op silencieux, pas d'erreur.

**Validation Phase 2** :
- Offre avec trace → bouton actif → clic → `/traces` scrolle sur le bon groupe, déplié.
- Offre sans trace → bouton grisé, tooltip au hover, non cliquable.
- Rechargement de `/traces#offer-XXX` direct → scroll + dépliage au montage.

---

## Garde-fous

- **Ne pas dédupliquer** les traces multiples d'une offre — la variance multi-seed est le signal (principe acté). Le groupe affiche ses N traces, point.
- **Pas de nouvelle vue** : on réutilise `traces.vue` tel quel + une ancre. Zéro duplication.
- Le `count` ne sort jamais du JSONL vers SQLite. Recalculé à la lecture.
- Si `source_id` se révèle déjà présent dans `OfferRow` à l'implémentation (à confirmer), L1 se réduit à un mapping — ne pas ajouter de colonne en double.

## Hors scope (reporté, adossé ici)

- Badge "N traces" sur le bouton (le count est déjà chargé, c'est purement cosmétique → plus tard si besoin).
- Filtres / recherche dans `traces.vue`.
- Lien retour trace → offre (sens inverse).
