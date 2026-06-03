# IMPLEMENTATION — Rituel de calibration humain↔IA

## Vue d'ensemble

Phase de calibration : confronter la notation humaine à celle de l'IA, critère par critère, pour exposer les défauts systématiques du scoring et piloter son tuning. Le désaccord est le signal exploitable. On greffe sur le cockpit web existant (Nuxt 4) un bloc d'avis en page détail, on persiste les avis dans une table dédiée `human_reviews`, on calcule une distance de désaccord par axe, et on exporte un markdown trié par désaccord décroissant — collable dans un chat frais pour l'analyse de biais.

Construit **en parallèle** du chantier scoring (chantier 2 profil) : la décision de figer le `criteria_json` IA à l'instant de chaque review (`ai_snapshot_json`) rend chaque avis auto-portant et survit aux évolutions du scoring. C'est la condition qui autorise C2 (construire maintenant plutôt qu'après stabilisation).

Premier chantier à attaquer : la table `human_reviews` (bloque tout l'aval).

---

## Invariant respecté

`architecture.md §"Persistance"` étendu : `human_reviews` est une **troisième** table d'interaction humaine, orthogonale à `offers` (score IA) et `verdicts` (statut favori/rejeté/candidaté). Écriture exclusive dans `human_reviews`. **Jamais** d'écriture sur `offers.criteria_json`, `offers.score`, ni recalcul du scoring depuis un avis humain. Même statut que `seen`/`verdicts` : donnée d'interaction, pas intrant de recalcul. Les trois tables ne fusionnent jamais — leur écart est le signal d'apprentissage.

---

## Schémas cibles

> À affiner au moment du livrable correspondant — base de travail, pas contrat figé.

### Table `human_reviews` (SQLite)

```sql
CREATE TABLE IF NOT EXISTS human_reviews (
    offer_id          TEXT PRIMARY KEY,           -- clé = 1 review par offre (upsert)
    ratings_json      TEXT NOT NULL,              -- {nom_critère: {note: int|null, justif: str|null}}
    ai_snapshot_json  TEXT NOT NULL,              -- copie figée du criteria_json IA à l'instant T
    global_audit_text TEXT,                       -- audit libre par-dessus les critères (nullable)
    global_score      INTEGER,                    -- note chiffrée globale optionnelle (nullable)
    seen_at_review    INTEGER NOT NULL DEFAULT 0, -- 0/1 : l'offre était-elle vue au moment de la review
    created_at        TEXT NOT NULL               -- ISO8601, écrasé à chaque upsert
);
```

Notes de conception :
- `ratings_json` : seuls les critères que l'humain a notés y figurent (ou tous, avec `null` pour non-renseigné — à trancher au livrable 1, mais la métrique ignore les `null` dans les deux cas).
- `ai_snapshot_json` : forme attendue = liste `[{nom, note, justif, axe}]`, copie verbatim du `criteria_json` de l'offre. Rend la review comparable à l'IA *du moment*, immune au chantier 2.
- Pas de colonne par critère (invariant : critères mouvants → zéro migration à chaque évolution scoring).

### Payload distance (objet calculé, non persisté)

```python
class DisagreementScore(BaseModel):
    offer_id: str
    distance_desirability: float | None   # moyenne |note_h - note_ia| sur critères co-notés axe désir, None si aucun
    distance_attainability: float | None  # idem axe atteignabilité
    distance_total: float                 # agrégat des deux axes (None traités comme absents)
    n_criteria_rated: int                 # couverture — métadonnée de lecture, n'influence PAS le calcul
    created_at: str
```

---

## Chantiers

### Chantier C-1 — Stockage `human_reviews`
**Objectif :** table dédiée créée, migration idempotente, jamais de colonne par critère.
**Durée estimée :** ~0.5 j

- [x] L1 — Schéma table `human_reviews` (migration idempotente `CREATE TABLE IF NOT EXISTS`)
- [x] L2 — Helpers d'accès `human_reviews` (upsert, get par `offer_id`) côté package persistance

```
✋ Verify before continuing:
- [ ] La migration tourne deux fois de suite sans erreur (idempotente)
- [ ] offers / verdicts / criteria_json strictement intacts après migration
- [ ] upsert + get round-trip un avis fictif correctement

Si tout est OK : "go". Sinon dis ce qui cloche.
```

### Chantier C-2 — Capture en page détail (cockpit)
**Objectif :** le bloc avis s'affiche sous les critères IA, formulaire généré dynamiquement, sans critère codé en dur.
**Durée estimée :** ~1.5 j

- [x] L3 — Lecture `criteria_json` de l'offre courante → liste `{nom, note IA, justif IA, axe}` (côté API ou front selon où vit déjà le détail)
- [x] L4 — Rendu des critères IA en lecture seule (nom + note + justif, aucun champ IA éditable)
- [x] L5 — Champs avis par critère (note + justif, optionnels, vides par défaut) en regard de chaque critère IA
- [x] L6 — Bloc audit global (textarea libre + champ note globale optionnel) par-dessus les critères

```
✋ Verify before continuing:
- [ ] Une offre affiche tous ses critères IA correctement parsés
- [ ] Le formulaire est 100% dérivé de criteria_json (changer un critère côté scoring le reflète sans patch front)
- [ ] Aucun champ ne permet de modifier la note/justif IA

Si tout est OK : "go". Sinon dis ce qui cloche.
```

### Chantier C-3 — Persistance & garde-fou
**Objectif :** sauvegarder une review (snapshot figé), recharger, signaler offre non vue. Invariant §Persistance tenu.
**Durée estimée :** ~1 j

- [x] L7 — Endpoint + persistance review (upsert dans `human_reviews`, capture `ai_snapshot_json` à l'instant T, écrit `created_at`)
- [x] L8 — Hydratation : rouvrir une offre notée recharge notes/justifs/audit dans les champs
- [x] L9 — Garde-fou offre non consultée : si `seen` absent → warning visuel + `seen_at_review=0` persisté. Pas de blocage.

```
✋ Verify before continuing:
- [ ] Sauvegarder une review écrit UNIQUEMENT dans human_reviews (offers.criteria_json/score inchangés — vérifier en DB)
- [ ] ai_snapshot_json contient bien le criteria_json figé, pas une référence
- [ ] Rouvrir une offre notée recharge tout ; warning visible sur offre non vue sans bloquer la saisie

Si tout est OK : "go". Sinon dis ce qui cloche.
```

### Chantier C-4 — Désaccord & export
**Objectif :** distance par axe sur critères co-notés, export markdown trié/paginé collable dans un chat frais.
**Durée estimée :** ~1.5 j

- [x] L10 — Fonction pure `disagreement(review) -> DisagreementScore` : ne retient que les critères co-notés, moyenne des écarts absolus par axe, `n_criteria_rated` en métadonnée (n'influence pas le tri)
- [x] L11 — Bouton export dans le cockpit (déclencheur génération markdown)
- [x] L12 — Génération markdown : offres notées uniquement, triées par `distance_total` décroissante, paginé par lots de 15, inclut écarts par critère + audit global + date + couverture

```
✋ Verify before continuing:
- [ ] Une review partielle (2 critères notés sur 6) donne une distance cohérente — les non-renseignés sont ignorés, jamais comptés 0
- [ ] L'export end-to-end (noter 3-4 offres → export → coller dans un chat frais) produit une analyse de biais exploitable
- [ ] Le tri est bien par désaccord décroissant ; la couverture est visible mais ne réordonne pas

Si tout est OK : "go". Sinon dis ce qui cloche.
```

---

## Livrables détaillés

1. **L1 — Schéma `human_reviews`** — table créée via migration idempotente, aucune colonne par critère. `XS`
2. **L2 — Helpers accès `human_reviews`** — `upsert_review()` / `get_review(offer_id)` testés en round-trip. `XS`
3. **L3 — Parse `criteria_json` page détail** — l'offre courante expose une liste `{nom, note IA, justif IA, axe}`. `XS`
4. **L4 — Rendu critères IA lecture seule** — chaque critère IA affiché, aucun champ IA éditable. `S`
5. **L5 — Champs avis par critère** — note + justif optionnelles en regard de chaque critère, vides par défaut. `S`
6. **L6 — Bloc audit global** — textarea libre + note globale optionnelle. `S`
7. **L7 — Persistance review (upsert + snapshot)** — écrit dans `human_reviews`, capture `ai_snapshot_json`, ne touche jamais `offers`. `M`
8. **L8 — Hydratation review existante** — réouverture recharge tout le formulaire. `S`
9. **L9 — Garde-fou offre non consultée** — warning visuel + `seen_at_review` persisté, pas de blocage. `S`
10. **L10 — Distance par axe** — fonction pure, critères co-notés uniquement, couverture en métadonnée. `M`
11. **L11 — Bouton export cockpit** — déclencheur génération markdown. `XS`
12. **L12 — Génération markdown trié + paginé** — offres notées, tri désaccord décroissant, lots de 15, format chat-ready. `L`

---

## Dépendances critiques

- **L1 bloque tout l'aval** (capture, persistance, métrique, export).
- **C-2 (capture) est le go/no-go d'hypothèse** : valider à la fin de L3/L4 que la *structure* de `criteria_json` (forme `[{nom, note, justif, axe}]`) est stable avant d'investir C-3/C-4. Si le chantier 2 profil change la structure (pas juste les critères), réaligner le parse ici avant de continuer.
- **L7 (snapshot) bloque L10** : pas de distance sans données figées.
- **L10 (métrique) bloque L12** : l'export trie sur la distance.

Chemin critique : L1 → L3 → L7 → L10 → L12.

---

## Garde-fous

- **Si C-2 révèle que `criteria_json` n'a pas d'axe lisible par critère** → la distance par axe (L10) est impossible telle que spécifiée. Stop, remonter au scoring pour exposer le rattachement axe, ou rabattre L10 sur une distance globale unique en attendant.
- **Si le volume de snapshots devient un problème** (improbable à l'échelle dizaines/centaines d'offres) → envisager une dédup des snapshots identiques. Ne pas optimiser prématurément.
- **Invariant §Persistance** : à chaque livrable touchant la DB, vérifier en fin de livrable que `offers` et `verdicts` sont intacts. Une écriture accidentelle sur `criteria_json` corrompt le dataset d'apprentissage.
