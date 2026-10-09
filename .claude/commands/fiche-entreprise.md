---
description: Fiche entreprise d'une offre retenue. Identifie l'employeur réel et rend, par une recherche ciblée sur mes sujets de lettre, les faits précis sur lesquels la lettre peut s'appuyer, avec citation, lien et sujet (JSON, 8 points au plus)
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

La lettre s'écrit à partir d'un seul fait, choisi ensuite parmi tes points, et d'un texte prêt qui répond à ce fait. La liste de ces textes, « mes sujets », t'est donnée après l'annonce, avec pour chacun un identifiant et sa condition d'usage. Un point sert à la lettre quand il répond à l'un de ces sujets, ou quand il dit précisément ce que le poste fait faire. Tout le reste ne sert à rien, même vrai et sourcé.

Étapes, dans l'ordre :
1. Pars de l'annonce ci-dessous. Cherche qui recrute vraiment, pas qui diffuse l'annonce. Le résultat de la cascade est un indice à vérifier, pas une vérité.
2. Classe la source : employeur direct, agence de recrutement (l'employeur final est masqué) ou agrégateur (un canal, pas un employeur). Si l'employeur est masqué, relève les indices de l'annonce (secteur, ville, taille, produit) et cherche avec.
3. Identifie l'entité précise qui recrute, pas seulement le groupe.
4. Lis l'annonce en entier. Relève les passages qui disent ce que le poste fait faire et comment l'équipe travaille, en gardant les mots de l'annonce. Pour chacun, dis s'il répond à l'un de mes sujets.
5. Recherche ciblée, un sujet à la fois : pour chacun de mes sujets, une recherche avec le nom de l'entité et les mots du sujet, sur ce que l'entreprise publie elle-même (site, blog technique, articles signés par ses ingénieurs, pages qui décrivent sa méthode ou ses offres en IA, autres offres techniques, prises de parole de ses responsables techniques). Tu ouvres la page avant de retenir quoi que ce soit. Un sujet sans fait précis reste sans point : tu ne forces pas un rapprochement.
6. Si l'entreprise ne publie rien, une seule recherche de plus sur ce qu'elle fait avec l'IA (entité sœur, presse spécialisée, conférence, étude de cas d'un partenaire), toujours rapportée à un sujet.
7. Restitue les faits point par point, sans les commenter.

Ce qu'est un bon point : un fait précis, que seul quelqu'un qui s'est renseigné peut écrire, et qui sert la lettre. Il entre dans l'une de ces trois familles.
- La façon de travailler de l'équipe : une méthode, un process, une exigence qu'elle décrit elle-même (ce qu'elle mesure, teste, évalue, trace, fait valider par une personne, prototype), et qui répond à l'un de mes sujets.
- Ce que le poste fait faire : un passage précis de l'annonce, pas son résumé. Il reste un bon point même s'il ne répond à aucun de mes sujets.
- Les preuves que l'entreprise sait travailler avec l'IA : ce que ses ingénieurs publient, les outils qu'elle nomme, un partenariat qu'elle affiche avec un éditeur de modèles, un cas d'usage qu'elle décrit, quand l'un de mes sujets y répond.

Ce qui n'est pas un point, même vrai et sourcé :
- un slogan, une mission, des valeurs ;
- un chiffre de taille, de chiffre d'affaires, de levée de fonds, de nombre de clients ;
- une implantation, une ville, une région ;
- la vie de l'entreprise : événements, avantages, formation interne, mentorat, ambiance ;
- un prix ou un label sans rapport avec le travail technique ;
- ce que fait toute entreprise du secteur ;
- un fait sur l'entreprise, même précis, qui ne répond à aucun de mes sujets et n'est pas un passage de l'annonce.

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
- 8 points au maximum, passages de l'annonce compris, les plus précis d'abord ; deux points au plus par sujet. Trois points solides valent mieux que huit faibles : si peu de faits entrent dans les trois familles, rends-en peu, ou aucun.
- `sujet` : l'identifiant du sujet auquel le point répond, parmi ceux de ma liste ; null pour un passage de l'annonce qui n'en sert aucun. Un point qui n'est ni l'un ni l'autre n'est pas rendu.
- Réponse : un unique objet JSON `{mode, presentation, employeur{nom, entite_precise, type_source, methode, confiance, urls}, points[{position, citation, url, sujet}]}`.
