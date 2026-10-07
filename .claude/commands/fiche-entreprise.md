---
description: Fiche entreprise d'une offre retenue. Identifie l'employeur réel et rend les faits précis sur lesquels une lettre peut s'appuyer, avec citation et lien (JSON, 8 points au plus)
argument-hint: <offer_id>
---

<!-- MANUEL -->
Invocation manuelle : `$ARGUMENTS` = id de l'offre. Lance
`.venv/bin/python -m orchestrator.job_search.fiche $ARGUMENTS` (lecture seule sur `data/job_search.sqlite`,
cascade d'identification via Ollama local). La sortie est le prompt complet, données de l'offre et résultat
de la cascade compris : applique-le tel quel avec WebSearch et WebFetch uniquement (ni Bash, ni Write, ni Edit
pour la recherche), puis réponds par le seul objet JSON demandé. Le back n'a pas besoin d'être démarré.
<!-- /MANUEL -->
Tu prépares la fiche d'une entreprise qui recrute, pour un candidat qui va lui écrire une lettre de motivation courte. La fiche sert à une chose : trouver les faits précis sur lesquels cette lettre pourra s'appuyer. Tu ne rédiges rien pour lui et tu ne donnes pas ton avis.

Étapes, dans l'ordre :
1. Pars de l'annonce ci-dessous. Cherche qui recrute vraiment, pas qui diffuse l'annonce. Le résultat de la cascade est un indice à vérifier, pas une vérité.
2. Classe la source : employeur direct, agence de recrutement (l'employeur final est masqué) ou agrégateur (un canal, pas un employeur). Si l'employeur est masqué, relève les indices de l'annonce (secteur, ville, taille, produit) et cherche avec.
3. Identifie l'entité précise qui recrute, pas seulement le groupe.
4. Lis l'annonce en entier. Relève les passages qui disent comment l'équipe travaille et ce que le poste fait faire.
5. Ouvre le site de l'entreprise, puis ce qu'elle publie sur son propre travail : blog technique, articles signés par ses ingénieurs, pages qui décrivent sa méthode ou ses offres en IA, ses autres offres d'emploi techniques, prises de parole de ses responsables techniques.
6. Si ces sources sont pauvres, cherche ailleurs : entité sœur, presse spécialisée, conférences, étude de cas publiée par un partenaire.
7. Restitue les faits point par point, sans les commenter.

Ce qu'est un bon point : un fait précis, que seul quelqu'un qui s'est renseigné peut écrire. Il entre dans l'une de ces trois familles.
- La façon de travailler de l'équipe : une méthode, un process, une exigence qu'elle décrit elle-même (ce qu'elle mesure, teste, évalue, trace, fait valider par une personne, prototype).
- Ce que le poste fait faire : un passage précis de l'annonce, pas son résumé.
- Les preuves que l'entreprise sait travailler avec l'IA : ce que ses ingénieurs publient, les outils qu'elle nomme, un partenariat qu'elle affiche avec un éditeur de modèles, un cas d'usage qu'elle décrit.

Ce qui n'est pas un point, même vrai et sourcé :
- un slogan, une mission, des valeurs ;
- un chiffre de taille, de chiffre d'affaires, de levée de fonds, de nombre de clients ;
- une implantation, une ville, une région ;
- la vie de l'entreprise : événements, avantages, formation interne, mentorat, ambiance ;
- un prix ou un label sans rapport avec le travail technique ;
- ce que fait toute entreprise du secteur.

Règles :
- Tu lances toujours au moins une recherche web avant de conclure, même si l'employeur te paraît évident.
- Tu choisis `mode` après ta recherche : `entreprise` si tu as identifié l'employeur et lu ses pages ; `offre_seule` si tu ne l'as pas identifié. Ce choix est le tien, pas celui de la cascade.
- `presentation` : un paragraphe qui dit ce qu'est l'entreprise et ce qu'elle fait, tiré des mêmes pages que les points, jamais de ta connaissance générale. Termine-le par ce que tu as cherché sans le trouver. Mode `offre_seule` : dis ce que l'annonce laisse savoir de l'employeur (secteur, taille, produit) sans le nommer. Tu ne rédiges jamais de lettre ni de paragraphe de candidature : `presentation` décrit l'entreprise, pas le candidat.
- `citation` : une ou deux phrases copiées mot pour mot de la page, dans la langue de la page. Jamais une reformulation, jamais un extrait vu seulement dans un résultat de recherche : tu ouvres la page.
- `position` : le fait, dit en une phrase en français, pour un lecteur qui ne connaît pas l'entreprise. Si la page porte une date ou un auteur, finis la phrase par eux, entre parenthèses.
- Mode `entreprise` : chaque point porte l'URL de la page d'où il vient et sa citation. Un point sans URL ou sans citation n'est pas rendu. Seule exception : un passage de l'annonce, dont l'`url` est celle de l'annonce, ou null si elle n'en a pas.
- Mode `offre_seule` : les points ne viennent que de l'annonce (citation copiée de l'annonce, `url` à null). Aucun point ne nomme un employeur que ni la cascade ni ta recherche n'ont identifié.
- « non trouvé » est une réponse valide. Préfère-la à une supposition. Si tu hésites entre deux employeurs, mets la confiance à « probable » et dis pourquoi dans `methode`.
- Aucun point tiré de ta connaissance générale : seulement des pages ouvertes pendant cette recherche.
- 8 points au maximum, passages de l'annonce compris, les plus précis d'abord. Trois points solides valent mieux que huit faibles : si peu de faits entrent dans les trois familles, rends-en peu, ou aucun.
- Réponse : un unique objet JSON `{mode, presentation, employeur{nom, entite_precise, type_source, methode, confiance, urls}, points[{position, citation, url}]}`.
