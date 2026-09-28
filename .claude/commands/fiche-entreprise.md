---
description: Fiche entreprise d'une offre retenue — identifie l'employeur réel, restitue ses positions avec sources (JSON ≤ 8 points)
argument-hint: <offer_id>
---

<!-- MANUEL -->
Invocation manuelle : `$ARGUMENTS` = id de l'offre. Lance
`.venv/bin/python -m orchestrator.job_search.fiche $ARGUMENTS` (lecture seule sur `data/job_search.sqlite`,
cascade d'identification via Ollama local). La sortie est le prompt complet, données de l'offre et résultat
de la cascade compris : applique-le tel quel avec WebSearch et WebFetch uniquement (ni Bash, ni Write, ni Edit
pour la recherche), puis réponds par le seul objet JSON demandé. Le back n'a pas besoin d'être démarré.
<!-- /MANUEL -->
Tu prépares la fiche d'une entreprise qui recrute, pour un candidat qui va y postuler. Tu ne rédiges rien pour lui et tu ne donnes pas ton avis.

Étapes, dans l'ordre :
1. Pars de l'annonce ci-dessous. Cherche qui recrute vraiment, pas qui diffuse l'annonce. Le résultat de la cascade est un indice à vérifier, pas une vérité.
2. Classe la source : employeur direct, agence de recrutement (l'employeur final est masqué) ou agrégateur (un canal, pas un employeur). Si l'employeur est masqué, relève les indices de l'annonce (secteur, ville, taille, produit) et cherche avec.
3. Identifie l'entité précise qui recrute, pas seulement le groupe.
4. Ouvre son site propre, puis sa page carrière, puis le site corporate, dans cet ordre.
5. Note ce que ces sources ne donnent pas. Si elles sont pauvres, cherche ailleurs : entité sœur, presse, prises de parole publiques.
6. Cherche qui dirige le service qui recrute et ce que cette personne a publié.
7. Restitue les positions de l'entreprise et de ce dirigeant point par point, sans les commenter.

Règles :
- Tu lances toujours au moins une recherche web avant de conclure, même si l'employeur te paraît évident.
- Tu choisis `mode` après ta recherche : `entreprise` si tu as identifié l'employeur et lu ses pages ; `offre_seule` si tu ne l'as pas identifié. Ce choix est le tien, pas celui de la cascade.
- `presentation` : un paragraphe qui dit ce qu'est l'entreprise et ce qu'elle fait, tiré des mêmes pages que les points — jamais de ta connaissance générale. Mode `offre_seule` : dis ce que l'annonce laisse savoir de l'employeur (secteur, taille, produit) sans le nommer. Tu ne rédiges jamais de lettre ni de paragraphe de candidature : `presentation` décrit l'entreprise, pas le candidat.
- Mode `entreprise` : chaque point porte l'URL de la page d'où il vient et une citation courte copiée de cette page. Un point sans URL ou sans citation n'est pas rendu.
- Mode `offre_seule` : les points ne viennent que de l'annonce (citation copiée de l'annonce, `url` à null). Aucun point ne nomme un employeur que ni la cascade ni ta recherche n'ont identifié.
- « non trouvé » est une réponse valide. Préfère-la à une supposition. Si tu hésites entre deux employeurs, mets la confiance à « probable » et dis pourquoi dans `methode`.
- Aucun point tiré de ta connaissance générale : seulement des pages ouvertes pendant cette recherche.
- 8 points au maximum. Garde les plus utiles pour une lettre ou un entretien.
- Réponse : un unique objet JSON `{mode, presentation, employeur{nom, entite_precise, type_source, methode, confiance, urls}, points[{position, citation, url}]}`.
