# IMPLEMENTATION — job-search-zone-a

## Vue d'ensemble

Run matinal de sourcing & tri auto d'offres d'emploi. Pull France Travail (Strasbourg+rayon OR remote) → dédup → scoring LLM explicable offre↔profil → persistance verdict+statut → digest matinal. Objectif d'apprentissage : scoring LLM **explicable** (score dérivé de critères notés, pas produit en bloc) + observabilité de décision.

**Première phase à attaquer : Phase 1 — Socle de domaine** (schéma `JobOffer` + interface `Source`). Tout l'aval en dépend, rien ne se code avant qu'il soit figé.

Deux points d'extension sont structurants et non négociables (cf. `rules/architecture.md`) : les **sources** sont pluggables derrière une interface commune, et le **profil cible** est mutable via fichier config. Aucun schéma de source ni aucun profil n'est codé en dur dans le pipeline.

---

## Schémas cibles

> À affiner au moment du livrable correspondant — base de travail, pas contrat figé.

### `JobOffer` (schéma neutre — Pydantic)

```python
from pydantic import BaseModel
from datetime import datetime

class JobOffer(BaseModel):
    source: str              # "france_travail", futur: autre source
    source_id: str           # id natif stable côté source
    fingerprint: str         # hash(titre normalisé + entreprise + localisation) — crochet cross-source
    title: str
    description: str
    company: str | None
    location: str | None     # libellé brut
    remote: bool             # full-remote détecté
    contract_type: str | None
    url: str
    fetched_at: datetime
```

### Profil cible (`profile.yaml` — déclaratif, mutable)

```yaml
profile_id: ai-engineer-generic
title: AI Engineer
seniority: mid            # junior | mid | senior
stack: [python, llm, rag, fastapi, docker]
location:
  base: Strasbourg
  radius_km: 30
  remote_ok: true        # full-remote sans contrainte géo accepté
criteria:                # critères notés par le LLM (0-10 chacun)
  - { key: stack_fit,     weight: 0.35 }
  - { key: seniority_fit, weight: 0.20 }
  - { key: location_fit,  weight: 0.15 }
  - { key: contract_fit,  weight: 0.10 }
  - { key: mission_fit,   weight: 0.20 }
```

Le loader hashe le fichier → ré-embed du profil uniquement si le hash change (base d'offres non rebuildée).

### Scoring (sortie LLM structurée par critère)

```json
{
  "criteria": [
    { "key": "stack_fit",     "score": 8, "justification": "…" },
    { "key": "seniority_fit", "score": 6, "justification": "…" }
  ]
}
```

Score global = Σ (score_critère/10 × weight) × 100, **calculé côté code**. Le LLM ne produit jamais le score global.

### Persistance (SQLite — 2 tables)

```sql
CREATE TABLE offers (
  id INTEGER PRIMARY KEY,
  source TEXT, source_id TEXT, fingerprint TEXT,
  title TEXT, company TEXT, location TEXT, remote INTEGER,
  contract_type TEXT, url TEXT, fetched_at TEXT,
  score REAL,                 -- score global agrégé
  criteria_json TEXT,         -- détail critères + justifs (observabilité)
  UNIQUE(source, source_id)
);

CREATE TABLE verdicts (
  id INTEGER PRIMARY KEY,
  offer_id INTEGER REFERENCES offers(id),
  status TEXT,                -- favori | rejeté | candidaté
  created_at TEXT
);
```

Séparer `offers` (score LLM) de `verdicts` (verdict humain) = signal d'apprentissage V2. Ne pas fusionner.

---

## Phases

### Phase 1 — Socle de domaine
**Objectif :** figer le schéma neutre `JobOffer` et l'interface `Source` dont dépend tout l'aval.
**Durée estimée :** 0.5 j

- [x] Livrable 1 — Schéma `JobOffer` + interface `Source`
- [x] Livrable 3 — Fichier profil config + loader (parallélisable)

```
✋ Verify before continuing:
- [ ] JobOffer instancie et valide un exemple à la main
- [ ] Source est une ABC avec fetch() -> list[JobOffer]
- [ ] profile.yaml se charge, se valide, et son hash est calculé

Si tout est OK : "go". Sinon dis ce qui cloche.
```

### Phase 2 — Ingestion & dédup
**Objectif :** récupérer des offres réelles France Travail et ne garder que le neuf.
**Durée estimée :** 1 j

- [x] Livrable 2 — Adapter `FranceTravailSource` (OAuth2, mapping → JobOffer)
- [x] Livrable 4 — Module dédup clé composite `(source, source_id)` + fingerprint

```
✋ Verify before continuing:
- [ ] Un fetch réel retourne des JobOffer valides (mapping OAuth + champs OK)
- [ ] Deux fetch d'affilée : le 2e ne sort que le neuf (0 si rien de neuf)

Si tout est OK : "go". Sinon dis ce qui cloche.
```

### Phase 3 — Matching & scoring explicable (cœur)
**Objectif :** scorer chaque offre neuve par critères structurés, score agrégé côté code.
**Durée estimée :** 1.5 j — risque technique principal

- [x] Livrable 5 — Embedding offre↔profil (recâblage ChromaDB, ré-embed au hash)
- [x] Livrable 6 — Scoring LLM par critères structurés + parsing défensif + agrégation `L`

```
✋ Verify before continuing:
- [ ] Similarité offre↔profil cohérente sur le dataset des 27 offres connues
- [ ] Sur 5-10 offres : le JSON parse, les critères sont plausibles
- [ ] Le score agrégé reflète bien les critères notés (pas de divergence)

Si tout est OK : "go". Sinon dis ce qui cloche.
```

### Phase 4 — Persistance, digest & verdicts
**Objectif :** câbler le run end-to-end et émettre le digest.
**Durée estimée :** 1 j

- [x] Livrable 7 — Persistance SQLite (tables offers + verdicts)
- [x] Livrable 8 — Génération du digest matinal
- [x] Livrable 9 — Orchestrateur `run.py` (fetch→dédup→embed→score→persist→digest)
- [x] Livrable 10 — Saisie de statut (favori/rejeté/candidaté)

```
✋ Verify before continuing:
- [ ] python run.py produit un digest complet sur données réelles end-to-end
- [ ] Les justifications du digest sont fidèles aux scores
- [ ] Un verdict humain s'enregistre dans verdicts, séparé de offers

Si tout est OK : "go". Sinon dis ce qui cloche.
```

---

## Livrables détaillés

1. **Schéma `JobOffer` + interface `Source`** — dataclass/Pydantic figée + ABC `fetch() -> list[JobOffer]`, aval consomme JobOffer uniquement. `S`
2. **Adapter `FranceTravailSource`** — OAuth2, refresh token, pull (Strasbourg+rayon OR remote), mapping payload FT → JobOffer. Done : un appel retourne des JobOffer valides. `M`
3. **Profil config + loader** — `profile.yaml` + loader/validateur, hash pour ré-embed conditionnel. Done : changer le YAML change le matching sans toucher au code. `M`
4. **Dédup clé composite** — `(source, source_id)` + calcul/stockage fingerprint, filtre le neuf avant scoring. Done : une offre vue hier n'est ni re-scorée ni re-notifiée. `M`
5. **Embedding offre↔profil** — recâblage ChromaDB, ré-embed profil au hash, base offres persistante. Done : similarité offre↔profil calculable. `M`
6. **Scoring LLM par critères** — prompt few-shot notant 4-6 critères atomiques (score + mini-justif), parsing défensif + retry, agrégation pondérée côté code. Done : une offre produit `{critères, justifs, score agrégé}` parsable. `L`
7. **Persistance SQLite** — tables offers + verdicts. Done : un run écrit les offres scorées ; un statut humain s'enregistre séparément. `M`
8. **Digest matinal** — top offres triées par score + justification lecture seule + lien, format poussable. Done : digest lisible listant le neuf scoré du jour. `M`
9. **Orchestrateur `run.py`** — enchaîne tout, exécutable en une commande. Done : `python run.py` produit le digest end-to-end. `M`
10. **Saisie de statut** — écriture du verdict humain dans verdicts (CLI ou champ digest). Done : un verdict humain persiste, prêt comme signal V2. `S`

---

## Dépendances critiques

- Livrable 1 **bloque** 2, 3, 4, 5, 6, 7 (le schéma neutre conditionne tout l'aval).
- Livrable 2 **bloque** 4 (dédup a besoin d'offres réelles).
- Livrables 3 + 5 **bloquent** 6 (scoring a besoin du profil et de l'embedding).
- Livrable 6 **bloque** 7, 8 (persistance et digest consomment le score).
- Livrable 9 **dépend de** 2, 4, 5, 6, 7, 8 (jalon "Zone A fonctionne").

Chemin critique : `1 → 2 → 4` // `1+3 → 5 → 6 → 7 → 8 → 9`.

---

## Garde-fous

- **Si Phase 3 (scoring) dépasse 1.5 j** : figer la grille à 4 critères max, accepter un parsing imparfait avec fallback score=0 + flag `parse_failed`, avancer. Le tuning fin se fait sous Pro, pas sous Max.
- **Si le 7B/8B note de façon instable** (hypothèse risquée) : baisser la température, renforcer le few-shot, et si ça ne suffit pas, réduire le nombre de critères avant d'envisager un modèle plus gros.
- **Découpe Max/Pro** : livrables 1-9 sous Max (architecture + pipeline). Tuning du scoring (grille, pondérations, qualité des justifs) + livrable 10 poursuivables sous Pro — c'est du débogage, pas de la construction.
- **Rappel produit** : "reposition, never fabricate" — hors-scope ici (c'est Zone B), mais ne jamais introduire de génération de contenu candidat dans ce repo.
