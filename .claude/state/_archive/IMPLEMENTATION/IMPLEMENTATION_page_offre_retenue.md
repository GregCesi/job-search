# IMPLEMENTATION — Page offre retenue (emplacements phase 2)

## Vue d'ensemble

Créer la première route paramétrée du projet (`/offers/[id]`) : une page plein-écran par offre retenue qui montre des données réelles à gauche et trois emplacements vides à droite (Entreprise, CV, Lettre). But exclusif : rendre visible la composition de la phase 2 avant de la bâtir. Aucun process de remplissage n'est construit ici. Le chantier touche uniquement `web/app/` — 0 modification côté `api/` et `orchestrator/`.

Première chose à attaquer : créer la route et le layout plein-écran (Phase 1), condition sans laquelle rien d'autre ne s'intègre.

## Schémas cibles

Aucun schéma Python/SQL touché. Le front consomme `GET /offers/{id}` existant — réponse `OfferDetail` qui expose déjà tous les champs nécessaires. Aucun champ à ajouter.

Type TS à créer dans la page : aucun nouveau type — `OfferDetail` est déjà exporté depuis `stores/offers.ts`.

## Phases

---

### Phase 1 — Route paramétrée + layout plein-écran

**Objectif** : la page `/offers/[id]` s'affiche, fetche l'offre, structure deux colonnes à hauteur fixe sans scroll de page.

- [x] Créer `web/app/pages/offers/[id].vue`
- [x] `onMounted` : `$fetch<OfferDetail>(\`${apiBase}/offers/${id}\`)` → état local `offer`
- [x] Layout : `h-screen overflow-hidden flex flex-col` — en-tête fixe, corps `flex-1 overflow-hidden flex`
- [x] En-tête : titre du poste, entreprise, lien `offer.url` « Voir l'annonce ↗ », bouton/lien retour (`router.back()`)
- [x] Corps : colonne gauche `flex flex-col gap-4 overflow-hidden` (2/3 de largeur), colonne droite `flex flex-col gap-3` (1/3)
- [x] État de chargement (`v-if="offer"` / skeleton ou spinner sinon)

✋ Verify before continuing:
- [ ] `git diff orchestrator/job_search/storage/db.py` est vide
- [ ] La page s'affiche sur `/offers/123` (id valide) sans scroll de page, les deux colonnes occupent toute la hauteur disponible

Si tout est OK : "go". Sinon dis ce qui cloche.

---

### Phase 2 — Colonne gauche : frise de statut + synthèse + annonce

**Objectif** : bloc résumé en haut (frise + extraction), bloc annonce en bas avec scroll interne uniquement.

- [x] **Frise de statut** — quatre étapes ordonnées : `Retenue → Prête à l'envoi → Candidature envoyée → Entretien à préparer`. Étape courante toujours `Retenue` (hardcodé). Aucun `@click` sur les étapes — attribut `tabindex="-1"` et pas de handler. Étape active mise en avant par couleur (indigo/blue, cohérent avec le reste du projet). Les trois autres en gris neutre.
- [x] **Synthèse d'extraction** — dans un bloc `rounded-lg border bg-gray-50` :
  - Lieu + remote (`offer.remote` → badge teal "Remote", sinon `offer.location`)
  - Contrat (`offer.contract_type`)
  - Séniorité (`offer.extracted_facts?.seniority_required`)
  - Rôle (`offer.extracted_facts?.role_level`)
  - Domaine (`offer.extracted_facts?.domain`)
  - Technos requises avec importance — même badges que `OfferDetail.vue` (`techBadgeClass`) splitées matchées / manquantes via `offer.techs_matched` / `offer.techs_missing`
  - Catégorie (`offer.category` / `offer.categorie_finale`), date (`offer.fetched_at`), source (`offer.source`)
- [x] **Bloc annonce** — `flex-1 overflow-y-auto` avec `v-html="renderedDescription"` (DOMPurify + marked, même pattern que `OfferDetail.vue:240-242`)

✋ Verify before continuing:
- [ ] Cliquer sur chacune des quatre étapes de la frise n'a aucun effet visible ni réseau
- [ ] Sur une offre dont la description dépasse la hauteur de l'écran : seul le bloc annonce scrolle, la page ne scrolle pas

Si tout est OK : "go". Sinon dis ce qui cloche.

---

### Phase 3 — Colonne droite : cartes vides + bouton Envoyer

**Objectif** : trois cartes « à produire » cliquables + overlay plein-écran vide + bouton Envoyer inerte.

- [x] **Trois cartes** `Entreprise`, `CV`, `Lettre de motivation` — chacune : titre, badge/label « à produire », état visuellement vide (ex. zone grisée avec icône ou texte italique). `cursor-pointer`.
- [x] Au clic sur une carte : overlay `fixed inset-0 z-50 bg-white flex flex-col` avec en-tête (titre de la carte + bouton fermer) et corps vide (message « Aucun contenu — à produire »). Fermeture via le bouton ou clic sur le fond.
- [x] **Bouton Envoyer** — `@click` handler qui ne fait rien (`() => {}`), pas d'appel réseau. Style cohérent avec les autres boutons d'action du projet.
- [x] Aucun `$fetch`, `useFetch`, `axios` ni mutation de store dans le handler Envoyer.

✋ Verify before continuing:
- [ ] Les trois cartes affichent un état vide — aucune donnée métier (pas de `offer.extracted_facts`, `offer.description`, ni aucun champ de l'offre dans ces cartes)
- [ ] Clic sur Envoyer : onglet réseau du navigateur ne montre aucune requête, le store n'est pas muté
- [ ] `grep -E "ollama|extract|generate" <(git diff)` sur le diff de ce chantier à ce stade est vide

Si tout est OK : "go". Sinon dis ce qui cloche.

---

### Phase 4 — Comportements existants modifiés

**Objectif** : bouton Retenir navigue au lieu de toggler ; onglet Retenues ouvre la page ; action Retirer disponible sur la page.

**Fichiers touchés** : `web/app/components/OfferDetail.vue`, `web/app/pages/index.vue`, `web/app/pages/offers/[id].vue` (déjà créé).

- [x] **`OfferDetail.vue` — bouton Retenir** (mode candidat, section Verdicts) :
  - Remplacer `toggleVerdict('retenu')` par un handler `handleRetenir()` :
    - Si `offer.verdict !== 'retenu'` → `await store.setVerdict(offer.id, 'retenu')` puis `router.push(\`/offers/\${offer.id}\`)`
    - Si `offer.verdict === 'retenu'` → `router.push(\`/offers/\${offer.id}\`)` sans PUT (déjà retenu)
  - Le bouton ne toglle plus : clic en tout cas navigue vers la page. Libellé : « Retenir → » (ou « Voir la page → » si déjà retenu).
- [x] **`index.vue` — `handleSelect`** : si `store.activeView === 'retenues'` → `router.push(\`/offers/\${offer.id}\`)` ; sinon → `await store.openDetail(offer.id)` (comportement actuel). Les onglets Cibles, Gaps, Filet ouvrent toujours le drawer.
- [x] **`offers/[id].vue` — action « Retirer des retenues »** : bouton dans l'en-tête ou sous la frise → `await $fetch(\`${apiBase}/offers/${offer.id}/verdict\`, { method: 'DELETE' })` puis `router.back()`. Libellé : « Retirer des retenues ».

✋ Verify before continuing:
- [x] Clic sur "Retenir" depuis un drawer (onglet Cibles) sur une offre non retenue : PUT déclenché, navigation vers `/offers/{id}` — vérifiable via onglet réseau + URL
- [x] Recliquer sur "Retenir" depuis un drawer sur une offre **déjà retenue** : aucun DELETE déclenché, navigation seulement — le toggle a disparu
- [x] Depuis la page `/offers/{id}`, aucun geste ne retire l'offre de la liste des retenues ni ne provoque un splice silencieux — l'offre reste accessible par router.back()
- [x] Clic sur une ligne dans l'onglet Retenues : ouvre `/offers/{id}` (pas le drawer)
- [x] Clic sur une ligne dans les onglets Cibles, Gaps, Filet : ouvre toujours le drawer (comportement inchangé)
- [x] Clic "Retirer des retenues" sur la page : DELETE déclenché, retour vers la liste — vérifiable via onglet réseau + URL
- [x] `git diff api/` est vide (0 fichier api/ modifié)
- [x] `git diff orchestrator/job_search/storage/db.py` est vide
- [x] `grep -E "ollama|extract|generate" <(git diff)` sur le diff complet du chantier est vide

Si tout est OK : "go". Sinon dis ce qui cloche.

---

## Livrables détaillés

1. **`web/app/pages/offers/[id].vue` (création)** — route + layout + fetch. Done = la page s'affiche sur un id valide, hauteur fixe, 0 scroll de page. **S**
2. **Frise de statut** — 4 étapes, aucune interactive. Done = clic sur chacune → 0 effet. **XS**
3. **Bloc synthèse extraction** — tous les champs listés dans la Phase 2, même badges techs que `OfferDetail.vue`. Done = affichage correct sur une offre avec `extracted_facts`. **S**
4. **Bloc annonce** — scroll interne uniquement. Done = la page ne scrolle pas quand la description déborde. **XS**
5. **Trois cartes + overlay plein-écran** — état vide, aucune donnée métier. Done = aucun champ de l'offre dans les cartes, overlay s'ouvre et se ferme. **S**
6. **Bouton Envoyer inerte** — 0 appel réseau, 0 mutation. Done = l'onglet réseau reste vide au clic. **XS**
7. **Modification bouton Retenir** (`OfferDetail.vue`) — perd toggle, navigue. Done = PUT + navigation vérifiés via réseau. **S**
8. **Modification `handleSelect`** (`index.vue`) — Retenues → page, autres → drawer. Done = comportement conditionnel vérifié par onglet. **S**
9. **Action Retirer des retenues** (`offers/[id].vue`) — DELETE + retour. Done = DELETE + router.back() vérifiés. **XS**

## Dépendances critiques

- Livrable 1 (route + layout) bloque tous les autres — rien ne s'intègre sans la page.
- Livrable 3 (synthèse) dépend de la présence de l'en-tête + layout (livrable 1).
- Livrable 9 (Retirer) vit dans `offers/[id].vue` — dépend de la création du fichier (livrable 1).

## Garde-fous

- Si la DOMPurify sanitization produit un `v-html` sans sanitize → stop et remonte : même pattern que `OfferDetail.vue:241` (`DOMPurify.sanitize(marked(...))` uniquement).
- Si le test de scroll révèle que le layout laisse déborder la page → réexaminer la chaîne `h-screen overflow-hidden` → `flex-1 overflow-hidden` → `overflow-y-auto` sur le bloc annonce ; le problème vient d'un maillon de la chaîne qui n'a pas `overflow-hidden`.
- Règle absolue : `git diff api/` et `git diff orchestrator/job_search/storage/db.py` doivent rester vides à chaque ✋. Si non vide → stop immédiat.
