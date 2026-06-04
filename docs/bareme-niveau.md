# Barème niveau techno — 10 paliers

> Utilisé dans `profile.yaml` : `level` = compréhension / capacité à en parler.
> Ce n'est **pas** un score d'autonomie de code — c'est une mesure de ce qu'on peut en dire
> dans un entretien ou une conversation technique.
>
> Aide à la saisie : choisir le palier le plus haut où **toutes** les conditions sont vraies.
> En cas de doute entre deux paliers, prendre le bas.

---

## Paliers

| # | Nom | Théorique | Pratique | Discours |
|---|-----|-----------|----------|----------|
| 1 | **Entendu** | J'ai entendu le terme | Aucune | Je sais que ça existe |
| 2 | **Notions** | Je comprends le concept, j'ai lu de la doc | Aucune | Je peux expliquer à quoi ça sert |
| 3 | **Tuto** | Je comprends les bases | J'ai suivi un tuto, fait un hello world guidé | Je peux décrire le flux principal |
| 4 | **Expérimenté** | Je comprends les patterns de base | J'ai fait un projet perso/kata, j'ai déboggué | Je peux répondre à "comment tu l'as utilisé ?" |
| 5 | **Utilisé** | Je comprends les patterns courants | Utilisé dans un contexte structuré (formation, side-project) | Je peux expliquer les choix et les alternatives basiques |
| 6 | **Opérationnel** | Je connais les pièges courants | Je livre du code fonctionnel sans aide constante | Je peux coder en live sur un problème connu |
| 7 | **Autonome** | Je connais les patterns avancés | Je conçois et livre des solutions en autonomie, je débogue seul | Je peux code-reviewer du code junior sur ce sujet |
| 8 | **Confirmé** | Je maîtrise les trade-offs, j'ai des opinions | J'ai géré des cas edge, j'ai des patterns à moi | Je fais des choix d'archi sur ce sujet, j'écris des RFC |
| 9 | **Expert** | Je connais les internals | J'ai contribué à l'écosystème ou j'ai des responsabilités techniques dessus | Je suis référence interne, je brieffe des seniors |
| 10 | **Référence** | Je connais les internals + la roadmap | Auteur, mainteneur, speaker connu, ou responsable d'équipe dessus | Je suis la référence publique ou la goto-person dans l'entreprise |

---

## Règles de saisie

- **Absent du profil** = inconnu = neutre. Ne pas mettre level 1 pour "j'en ai entendu parler" — laisser absent.
- **Paliers 1-2** : connaissance passive. On peut en parler mais on ne peut pas coder.
- **Palier 5** : seuil minimum pour qu'une offre qui exige cette techno ne soit pas un mur.
- **Palier 7** : autonomie réelle. En-dessous, il faut du support sur les problèmes non-triviaux.
- **Paliers 9-10** : rares. Réserver à une expertise qui se voit dans des contributions publiques ou des responsabilités formelles.

## Mapping indicatif depuis l'ancien format (v1 → v2)

| Ancien palier | Niveau v2 indicatif | Nuance |
|---------------|---------------------|--------|
| `notions` | 2–4 | 2 = lu doc, 4 = projet perso |
| `working` | 5–7 | 5 = utilisé, 7 = autonome |
| `confirmed` | 7–9 | 7 = confirmé usage, 9 = expert |

> Ce mapping est une aide à la migration, pas une règle mécanique.
> Recalibrer à la main plutôt que de mapper automatiquement.
