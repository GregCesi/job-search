# Gate Report — Lot G : rétro-attribution hors_perimetre (langue + contrat)

Date : 2026-07-08

## Distribution avant / après

| Bucket | Avant | Après | Delta |
|--------|------:|------:|------:|
| parfait | 2 | 1 | -1 |
| reve | 33 | 25 | -8 |
| atteignable | 28 | 24 | -4 |
| hors | 108 | 96 | -12 |
| hors_perimetre | 44 | 69 | +25 |
| filtered | 12 | 12 | 0 |

## Offres nouvellement gatées (changement de bucket)

| ID | Titre | Entreprise | Ancien bucket | Causes |
|---:|-------|-----------|---------------|--------|
| 1 | Ingénieur data - projet IA en alternance F/H/X (H/F) | SOCOMEC | atteignable | contrat |
| 9 | Alternance BTS SIO / Technicien(ne) informatique/Développeur | IFIDE Sup-Formation Eckbolsheim | hors | langue, contrat |
| 19 | Alternance Chargé de Data visualisation - Achenheim (F/H) (H |  | reve | contrat |
| 29 | Alternance Support IT & Opérations - Strasbourg (H/F) |  | hors | contrat |
| 37 | INGÉNIEUR ÉTUDES ET DÉVELOPPEMENT INFORMATIQUE (H/F) |  | atteignable | contrat |
| 41 | Alternance Développeur Transformation Digitale & Intégration |  | hors | contrat |
| 71 | Développeur Confirmé .NET H/F | CRIT INTERIM | hors | contrat |
| 79 | Ingénieur réseau expert (H/F) |  | hors | contrat |
| 117 | Quality Assurance Rater - German (Germany) | TELUS Digital | atteignable | langue |
| 123 | Online Data Analyst United States Spanish speakers | TELUS Digital | atteignable | langue |
| 140 | Mid/Senior AI Cinematic Video Editor | EverAI | reve | langue |
| 154 | Ingénieur systèmes et réseaux (H/F) | Actual Talent Metz IT | hors | contrat |
| 166 | Stage Full-Stack Developer - React / Python | Space | Etinars | hors | contrat |
| 167 | Stage Cloud Developer - Kubernetes / DevOps | Space | Etinars | hors | contrat |
| 186 | Computer Vision ML (Intern) | Sightengine | reve | contrat |
| 187 | Offre de Stage – Développement d'Applications, IA, Marketing | Helci assur | reve | contrat |
| 189 | Data Analyst (Portuguese) | Lightcast | reve | langue |
| 192 | Fullstack Software Engineer - Core | DATAIKU | hors | langue |
| 197 | AI Skills Engineer | QuadCode | parfait | langue |
| 201 | Ingénieur systèmes et réseaux (H/F) |  | hors | contrat |
| 205 | Python Backend Platform Engineer (AI Software) | QuadCode | reve | langue |
| 211 | Alternance - Ingénieur Cybersécurité & Systèmes H/F |  | hors | contrat |
| 212 | Alternance - Data Analyst (H/F) |  | reve | contrat |
| 215 | Développeur en Intelligence Artificielle - Alternance H/F |  | reve | contrat |
| 224 | Sr. Full Stack .NET Developer (Remote, Contract) | INFUSE | hors | langue |

Total : 25 offres ayant changé de bucket → hors_perimetre.

## Cas corpus — langue tierce (4 attendus)

| ID | Titre | Entreprise | Ancien bucket | Causes |
|---:|-------|-----------|---------------|--------|
| 9 | Alternance BTS SIO / Technicien(ne) informatique/Développeur | IFIDE Sup-Formation Eckbolsheim | hors | langue, contrat |
| 117 | Quality Assurance Rater - German (Germany) | TELUS Digital | atteignable | langue |
| 123 | Online Data Analyst United States Spanish speakers | TELUS Digital | atteignable | langue |
| 140 | Mid/Senior AI Cinematic Video Editor | EverAI | reve | langue |
| 189 | Data Analyst (Portuguese) | Lightcast | reve | langue |
| 192 | Fullstack Software Engineer - Core | DATAIKU | hors | langue |
| 197 | AI Skills Engineer | QuadCode | parfait | langue |
| 205 | Python Backend Platform Engineer (AI Software) | QuadCode | reve | langue |
| 224 | Sr. Full Stack .NET Developer (Remote, Contract) | INFUSE | hors | langue |

## Cas corpus — contrat (stage/alternance/MIS)

| ID | Titre | Entreprise | Ancien bucket | Causes |
|---:|-------|-----------|---------------|--------|
| 1 | Ingénieur data - projet IA en alternance F/H/X (H/F) | SOCOMEC | atteignable | contrat |
| 9 | Alternance BTS SIO / Technicien(ne) informatique/Développeur | IFIDE Sup-Formation Eckbolsheim | hors | langue, contrat |
| 19 | Alternance Chargé de Data visualisation - Achenheim (F/H) (H |  | reve | contrat |
| 29 | Alternance Support IT & Opérations - Strasbourg (H/F) |  | hors | contrat |
| 37 | INGÉNIEUR ÉTUDES ET DÉVELOPPEMENT INFORMATIQUE (H/F) |  | atteignable | contrat |
| 41 | Alternance Développeur Transformation Digitale & Intégration |  | hors | contrat |
| 71 | Développeur Confirmé .NET H/F | CRIT INTERIM | hors | contrat |
| 79 | Ingénieur réseau expert (H/F) |  | hors | contrat |
| 154 | Ingénieur systèmes et réseaux (H/F) | Actual Talent Metz IT | hors | contrat |
| 166 | Stage Full-Stack Developer - React / Python | Space | Etinars | hors | contrat |
| 167 | Stage Cloud Developer - Kubernetes / DevOps | Space | Etinars | hors | contrat |
| 186 | Computer Vision ML (Intern) | Sightengine | reve | contrat |
| 187 | Offre de Stage – Développement d'Applications, IA, Marketing | Helci assur | reve | contrat |
| 201 | Ingénieur systèmes et réseaux (H/F) |  | hors | contrat |
| 211 | Alternance - Ingénieur Cybersécurité & Systèmes H/F |  | hors | contrat |
| 212 | Alternance - Data Analyst (H/F) |  | reve | contrat |
| 215 | Développeur en Intelligence Artificielle - Alternance H/F |  | reve | contrat |

## Vérification non-régression

- Aucune offre CDI/Freelance/Full-time fr/en gatée par erreur parmi les 26 parfait/rêve restantes.
- Le gate ne modifie aucun score (`extracted_facts_json` inchangé pour toutes les offres).
- Les 44 offres historiquement `hors_perimetre` conservent leur statut (causes enrichies : scalaire → liste).
