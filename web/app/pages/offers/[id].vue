<template>
  <div class="h-screen overflow-hidden flex">

    <!-- Menu candidat (EXE-80) -->
    <CandidateMenu />

    <div class="flex-1 min-w-0 overflow-hidden flex flex-col">

      <!-- En-tête fixe -->
      <header class="bg-white border-b border-gray-200 px-6 py-4 flex items-center gap-4 flex-shrink-0">
        <button
          @click="router.back()"
          class="text-gray-400 hover:text-gray-600 flex-shrink-0"
          aria-label="Retour"
        >
          <svg class="w-5 h-5" fill="none" stroke="currentColor" stroke-width="2" viewBox="0 0 24 24">
            <path stroke-linecap="round" stroke-linejoin="round" d="M15 19l-7-7 7-7"/>
          </svg>
        </button>

        <div v-if="offer" class="flex-1 min-w-0">
          <h1 class="text-base font-semibold text-gray-900 leading-snug truncate">
            {{ offer.title ?? '(sans titre)' }}
          </h1>
          <p class="text-sm text-gray-500 mt-0.5">
            {{ offer.company ?? '—' }}
          </p>
        </div>
        <div v-else class="flex-1 min-w-0">
          <div class="h-4 bg-gray-200 rounded w-64 animate-pulse mb-1.5"></div>
          <div class="h-3 bg-gray-100 rounded w-32 animate-pulse"></div>
        </div>

        <div class="flex items-center gap-3 flex-shrink-0">
          <button
            v-if="offer"
            @click="retirerDesRetenues"
            class="text-sm text-gray-400 hover:text-red-500 transition-colors"
          >
            Retirer des retenues
          </button>
          <a
            v-if="offer?.url"
            :href="offer.url"
            target="_blank"
            rel="noopener noreferrer"
            class="text-indigo-600 hover:underline font-medium text-sm"
          >
            Voir l'annonce ↗
          </a>
        </div>
      </header>

      <!-- Corps -->
      <div class="flex-1 overflow-hidden flex">

        <!-- Colonne gauche (2/3) -->
        <div class="w-2/3 flex flex-col gap-4 overflow-hidden border-r border-gray-100 p-6">
          <div v-if="!offer" class="flex items-center justify-center h-full text-gray-400 text-sm">
            Chargement…
          </div>

          <template v-if="offer">
            <!-- Frise de statut -->
            <div class="flex items-center gap-0 flex-shrink-0">
              <template v-for="(step, idx) in STEPS" :key="step">
                <div
                  tabindex="-1"
                  class="flex items-center gap-1.5 px-3 py-1.5 rounded-full text-xs font-medium select-none"
                  :class="step === 'Retenue'
                    ? 'bg-indigo-600 text-white'
                    : 'text-gray-400'"
                >
                  <span>{{ step }}</span>
                </div>
                <svg v-if="idx < STEPS.length - 1" class="w-4 h-4 text-gray-300 flex-shrink-0" fill="none" stroke="currentColor" stroke-width="2" viewBox="0 0 24 24">
                  <path stroke-linecap="round" stroke-linejoin="round" d="M9 5l7 7-7 7"/>
                </svg>
              </template>
            </div>

            <!-- Vérification d'expiration (EXE-76/77/78) — tag/date/checks pour
                 toute offre expirée ; URL employeur réservée aux retenues -->
            <div v-if="isRetenue || offer.expired" class="rounded-lg border border-gray-200 bg-white px-4 py-3 space-y-2 flex-shrink-0 text-xs">
              <div v-if="offer.expired" class="space-y-2">
                <div class="flex items-center gap-2">
                  <span class="inline-flex items-center px-2 py-0.5 rounded-full bg-red-100 text-red-700 font-medium">Expiré</span>
                  <span v-if="offer.last_checked_at" class="text-gray-400">
                    Dernière vérification <span class="text-gray-600 font-medium">{{ offer.last_checked_at.slice(0, 10) }}</span>
                  </span>
                </div>
                <ul v-if="offer.expiration_checks.length" class="space-y-1">
                  <li v-for="chk in offer.expiration_checks" :key="chk.url" class="flex items-center gap-2 text-gray-600">
                    <span class="truncate flex-1">{{ chk.url }}</span>
                    <span class="font-medium">{{ chk.status_code !== null ? chk.status_code : 'pas de réponse' }}</span>
                  </li>
                </ul>
              </div>

              <template v-if="isRetenue">
                <div class="flex items-center gap-2" :class="offer.expired ? 'pt-2 border-t border-gray-100' : ''">
                  <label class="text-gray-400 shrink-0">URL chez l'employeur</label>
                  <input
                    v-model="employerUrlEdit"
                    type="text"
                    placeholder="https://..."
                    class="flex-1 rounded border border-gray-200 px-2 py-1 text-xs"
                  >
                  <button
                    @click="enregistrerEmployerUrl"
                    :disabled="employerUrlBusy"
                    class="px-2.5 py-1 rounded bg-indigo-50 text-indigo-700 hover:bg-indigo-100 disabled:opacity-50 shrink-0"
                  >{{ employerUrlBusy ? '…' : 'Enregistrer' }}</button>
                </div>
                <p v-if="employerUrlError" class="text-red-600">{{ employerUrlError }}</p>
              </template>
            </div>

            <!-- Synthèse d'extraction -->
            <div class="rounded-lg border border-gray-200 bg-gray-50 px-4 py-3 space-y-2 flex-shrink-0 text-xs">
              <!-- Lieu + remote + contrat + date + source -->
              <div class="flex flex-wrap gap-x-4 gap-y-1 text-gray-600">
                <span v-if="offer.remote" class="px-2 py-0.5 rounded bg-teal-50 text-teal-700 font-medium">Remote</span>
                <span v-else-if="offer.location">{{ offer.location }}</span>
                <span v-if="offer.contract_type"><span class="text-gray-400">Contrat</span> <span class="font-medium">{{ offer.contract_type }}</span></span>
                <span v-if="offer.fetched_at"><span class="text-gray-400">Ajoutée</span> {{ offer.fetched_at.slice(0, 10) }}</span>
                <span v-if="offer.source"><span class="text-gray-400">Source</span> <span class="font-medium">{{ offer.source }}</span></span>
                <span v-if="offer.categorie_finale ?? offer.category">
                  <span class="text-gray-400">Catégorie</span>
                  <span :class="categoryBadgeClass(offer.categorie_finale ?? offer.category)" class="ml-1 px-1.5 py-0.5 rounded border font-medium">
                    {{ categoryLabel(offer.categorie_finale ?? offer.category) }}
                  </span>
                </span>
              </div>
              <!-- Faits extraits -->
              <div v-if="offer.extracted_facts" class="flex flex-wrap gap-x-4 gap-y-1 text-gray-600">
                <span v-if="offer.extracted_facts.seniority_required"><span class="text-gray-400">Séniorité</span> <span class="font-medium">{{ offer.extracted_facts.seniority_required }}</span></span>
                <span v-if="offer.extracted_facts.role_level"><span class="text-gray-400">Rôle</span> <span class="font-medium">{{ offer.extracted_facts.role_level }}</span></span>
                <span v-if="offer.extracted_facts.domain"><span class="text-gray-400">Domaine</span> <span class="font-medium">{{ offer.extracted_facts.domain }}</span></span>
              </div>
              <!-- Technos -->
              <template v-if="offer.extracted_facts && offer.extracted_facts.techs_required.length > 0">
                <div v-if="ownedTechs.length" class="flex flex-wrap items-center gap-1.5">
                  <span class="text-[10px] text-gray-400 mr-0.5">Possédées</span>
                  <span
                    v-for="tech in ownedTechs" :key="tech.name"
                    :class="techBadgeClass(tech.importance)"
                    class="inline-flex items-center px-2 py-0.5 rounded font-medium"
                    :title="tech.importance ?? 'importance inconnue'"
                  >{{ tech.name }}</span>
                </div>
                <div v-if="missingTechs.length" class="flex flex-wrap items-center gap-1.5">
                  <span class="text-[10px] text-gray-400 mr-0.5">Manquantes</span>
                  <span
                    v-for="tech in missingTechs" :key="tech.name"
                    :class="techBadgeClass(tech.importance)"
                    class="inline-flex items-center px-2 py-0.5 rounded font-medium ring-1 ring-red-300"
                    :title="tech.importance ?? 'importance inconnue'"
                  >{{ tech.name }}</span>
                </div>
              </template>
            </div>

            <!-- Bloc annonce -->
            <div class="flex-1 overflow-y-auto prose prose-sm prose-gray max-w-none leading-relaxed text-gray-600" v-html="renderedDescription" />
          </template>
        </div>

        <!-- Colonne droite (1/3) -->
        <div class="w-1/3 flex flex-col gap-3 p-6 bg-gray-50">
          <template v-if="offer">
            <!-- Trois cartes -->
            <div
              v-for="card in CARDS" :key="card.title"
              @click="openCard(card.title)"
              class="rounded-lg border border-gray-200 bg-white p-4 cursor-pointer hover:border-indigo-200 hover:shadow-sm transition-all flex flex-col gap-2"
            >
              <div class="flex items-center justify-between">
                <span class="text-sm font-medium text-gray-700">{{ card.title }}</span>
                <span class="text-[10px] px-2 py-0.5 rounded-full font-medium" :class="cardBadge(card.title).class">{{ cardBadge(card.title).label }}</span>
              </div>
              <div class="h-10 rounded bg-gray-50 border border-dashed border-gray-200 flex items-center justify-center">
                <span class="text-xs text-gray-300 italic">{{ cardPreview(card.title) }}</span>
              </div>
            </div>

            <!-- Bouton Envoyer -->
            <div class="mt-auto pt-2">
              <button
                @click="() => {}"
                class="w-full px-4 py-2.5 rounded-lg bg-indigo-600 text-white text-sm font-medium hover:bg-indigo-700 transition-colors"
              >
                Envoyer
              </button>
            </div>
          </template>
        </div>

      </div>
    </div>

    <!-- Overlay -->
    <div
      v-if="activeCard"
      class="fixed inset-0 z-50 bg-white flex flex-col"
      @click.self="activeCard = null"
    >
      <div class="flex items-center justify-between px-6 py-4 border-b border-gray-200 flex-shrink-0">
        <h2 class="text-base font-semibold text-gray-900">{{ activeCard }}</h2>
        <button @click="activeCard = null" class="text-gray-400 hover:text-gray-600">
          <svg class="w-5 h-5" fill="none" stroke="currentColor" stroke-width="2" viewBox="0 0 24 24">
            <path stroke-linecap="round" stroke-linejoin="round" d="M6 18L18 6M6 6l12 12"/>
          </svg>
        </button>
      </div>
      <div v-if="activeCard === 'Lettre de motivation'" class="flex-1 overflow-y-auto p-6">
        <div class="max-w-3xl mx-auto space-y-4">
          <!-- Non éligible -->
          <div v-if="!isRetenue || !ficheDone" class="rounded-lg border border-gray-200 bg-white p-6 flex flex-col items-center justify-center text-center gap-3">
            <p v-if="!isRetenue" class="text-sm text-gray-400 italic">La lettre n'est générée que pour une offre retenue.</p>
            <p v-else class="text-sm text-gray-400 italic">La fiche entreprise doit être terminée avant de générer la lettre.</p>
          </div>

          <template v-else>
            <!-- Points choisis -->
            <section class="rounded-lg border border-gray-200 bg-white p-4 space-y-2">
              <h3 class="text-xs font-semibold text-gray-400 uppercase tracking-wide">Points choisis pour la lettre</h3>
              <p v-if="!lettrePoints || !lettrePoints.length" class="text-sm text-gray-400 italic">Aucun point.</p>
              <ul v-else class="space-y-2">
                <li v-for="(point, idx) in lettrePoints" :key="idx" class="flex items-start gap-2 text-sm text-gray-700">
                  <input
                    type="checkbox"
                    :checked="point.choisi"
                    @change="togglePointChoisi(idx)"
                    class="mt-0.5 flex-shrink-0"
                  >
                  <span class="flex-1">{{ point.texte }}</span>
                  <span v-if="point.tas" class="text-[10px] px-1.5 py-0.5 rounded bg-gray-100 text-gray-500 flex-shrink-0">{{ point.tas }}</span>
                </li>
              </ul>
            </section>

            <!-- Pas de lettre / erreur -->
            <div v-if="!lettre || lettre.statut === 'error'" class="rounded-lg border border-gray-200 bg-white p-6 flex flex-col items-center justify-center text-center gap-3">
              <p v-if="lettre?.error_message" class="text-sm text-red-600">{{ lettre.error_message }}</p>
              <button
                @click="genererLettre"
                :disabled="lettreBusy"
                class="px-4 py-2.5 rounded-lg bg-indigo-600 text-white text-sm font-medium hover:bg-indigo-700 transition-colors disabled:opacity-50"
              >{{ lettreBusy ? 'Lancement…' : 'Générer la lettre' }}</button>
              <p v-if="lettreActionError" class="text-xs text-red-600">{{ lettreActionError }}</p>
            </div>

            <!-- En cours -->
            <div v-else-if="lettre.statut === 'pending'" class="rounded-lg border border-gray-200 bg-white p-6 flex items-center justify-center gap-3 text-sm text-gray-500">
              <svg class="w-5 h-5 animate-spin text-indigo-600" fill="none" viewBox="0 0 24 24">
                <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"/>
                <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8v4a4 4 0 00-4 4H4z"/>
              </svg>
              Génération en cours…
            </div>

            <!-- Lettre prête -->
            <template v-else>
              <div
                v-if="lettre.nb_mots !== null || lettre.depasse_longueur || lettre.tournures_signalees.length"
                class="rounded-lg border border-gray-200 bg-gray-50 px-4 py-3 space-y-2 text-xs"
              >
                <p v-if="lettre.nb_mots !== null" class="text-gray-500"><span class="text-gray-400">Mots</span> <span class="font-medium text-gray-700">{{ lettre.nb_mots }}</span></p>
                <p v-if="lettre.depasse_longueur" class="text-amber-800 bg-amber-50 border border-amber-200 rounded px-2 py-1">Dépasse la longueur recommandée.</p>
                <div v-if="lettre.tournures_signalees.length" class="space-y-1">
                  <p class="text-gray-400">Tournures signalées</p>
                  <ul class="flex flex-wrap gap-1.5">
                    <li v-for="t in lettre.tournures_signalees" :key="t" class="px-2 py-0.5 rounded bg-red-50 text-red-600">{{ t }}</li>
                  </ul>
                </div>
              </div>

              <textarea
                v-model="texteEdit"
                :disabled="lettre.regeneration_en_cours"
                rows="14"
                class="w-full rounded-lg border border-gray-200 p-3 text-sm text-gray-800 leading-relaxed disabled:bg-gray-50 disabled:text-gray-400"
              />

              <div class="flex items-center gap-2">
                <button
                  @click="sauvegarderTexte"
                  :disabled="lettre.regeneration_en_cours"
                  class="px-4 py-2.5 rounded-lg bg-indigo-600 text-white text-sm font-medium hover:bg-indigo-700 transition-colors disabled:opacity-50"
                >Enregistrer</button>
                <button
                  @click="copierTexte"
                  class="text-xs px-2 py-1 rounded bg-indigo-50 text-indigo-700 hover:bg-indigo-100"
                >{{ lettreCopied ? 'Copié !' : 'Copier' }}</button>
                <button
                  @click="regenererLettre"
                  :disabled="lettre.regeneration_en_cours || lettreBusy"
                  class="text-xs px-2 py-1 rounded bg-indigo-50 text-indigo-700 hover:bg-indigo-100 disabled:opacity-50"
                >{{ lettre.regeneration_en_cours ? 'Régénération en cours…' : 'Régénérer' }}</button>
              </div>
              <p v-if="lettre.regeneration_error" class="text-xs text-red-600">{{ lettre.regeneration_error }}</p>
              <p v-if="lettreActionError" class="text-xs text-red-600">{{ lettreActionError }}</p>
            </template>

            <!-- Historique des versions -->
            <section class="rounded-lg border border-gray-200 bg-white p-4 space-y-2">
              <h3 class="text-xs font-semibold text-gray-400 uppercase tracking-wide">Historique des versions</h3>
              <p v-if="!lettreVersions.length" class="text-sm text-gray-400 italic">Aucune version.</p>
              <ul v-else class="space-y-2">
                <li v-for="(v, i) in lettreVersions" :key="i" class="rounded border border-gray-200 bg-gray-50 p-3 space-y-1">
                  <div class="flex items-center justify-between text-xs text-gray-500">
                    <span>{{ v.created_at }}</span>
                    <span class="px-1.5 py-0.5 rounded bg-gray-100 text-gray-500">{{ v.origine === 'moi' ? 'moi' : 'modèle' }}</span>
                  </div>
                  <p class="text-xs text-gray-700 whitespace-pre-wrap">{{ v.texte }}</p>
                </li>
              </ul>
            </section>
          </template>
        </div>
      </div>

      <!-- CV adapté -->
      <div v-else-if="activeCard === 'CV'" class="flex-1 overflow-y-auto p-6">
        <div class="max-w-3xl mx-auto space-y-5">
          <!-- Pas de CV / erreur -->
          <div v-if="!cv || cv.statut === 'error'" class="rounded-lg border border-gray-200 bg-white p-6 flex flex-col items-center justify-center text-center gap-3">
            <p v-if="cv?.error_message" class="text-sm text-red-600">{{ cv.error_message }}</p>
            <p v-if="!isRetenue" class="text-sm text-gray-400 italic">Le CV n'est généré que pour une offre retenue.</p>
            <button
              v-else
              @click="genererCv"
              class="px-4 py-2.5 rounded-lg bg-indigo-600 text-white text-sm font-medium hover:bg-indigo-700 transition-colors"
            >
              Générer le CV
            </button>
          </div>

          <!-- En cours -->
          <div v-else-if="cv.statut === 'pending'" class="rounded-lg border border-gray-200 bg-white p-6 flex items-center justify-center gap-3 text-sm text-gray-500">
            <svg class="w-5 h-5 animate-spin text-indigo-600" fill="none" viewBox="0 0 24 24">
              <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"/>
              <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8v4a4 4 0 00-4 4H4z"/>
            </svg>
            Génération en cours…
          </div>

          <!-- CV prêt -->
          <template v-else>
            <div class="rounded-lg border border-gray-200 bg-gray-50 px-4 py-3 flex items-center justify-between gap-4">
              <p class="text-xs text-gray-500">
                <span class="text-gray-400">Titre</span> <span class="font-medium text-gray-700">{{ cv.titre ?? '—' }}</span>
                <span class="text-gray-400 ml-3">Lieu</span> <span class="font-medium text-gray-700">{{ cv.localisation ?? '—' }}</span>
              </p>
              <a
                v-if="cvHtmlUrl"
                :href="cvHtmlUrl"
                target="_blank"
                rel="noopener noreferrer"
                class="text-indigo-600 hover:underline font-medium text-sm flex-shrink-0"
              >Ouvrir le CV ↗</a>
            </div>

            <!-- Au CV -->
            <section class="rounded-lg border border-gray-200 bg-white p-4 space-y-3">
              <h3 class="text-xs font-semibold text-gray-400 uppercase tracking-wide">Au CV</h3>
              <p v-if="!cv.groupes.length && !cv.notions.length" class="text-sm text-gray-400 italic">Vide.</p>
              <div v-for="grp in cv.groupes" :key="grp.label" class="space-y-1">
                <p class="text-xs font-medium text-gray-500">{{ grp.label }}</p>
                <ul class="flex flex-wrap gap-1.5">
                  <li
                    v-for="item in grp.items" :key="item"
                    class="inline-flex items-center gap-1 px-2 py-0.5 rounded bg-gray-100 text-gray-700 text-xs"
                  >
                    {{ item }}
                    <button @click="retirerCompetence(item)" class="text-gray-400 hover:text-red-500" :aria-label="`Retirer ${item}`">×</button>
                  </li>
                </ul>
              </div>
              <div v-if="cv.notions.length" class="space-y-1">
                <p class="text-xs font-medium text-gray-500">Notions en :</p>
                <ul class="flex flex-wrap gap-1.5">
                  <li
                    v-for="item in cv.notions" :key="item"
                    class="inline-flex items-center gap-1 px-2 py-0.5 rounded bg-gray-50 text-gray-600 text-xs ring-1 ring-gray-200"
                  >
                    {{ item }}
                    <button @click="retirerCompetence(item)" class="text-gray-400 hover:text-red-500" :aria-label="`Retirer ${item}`">×</button>
                  </li>
                </ul>
              </div>
            </section>

            <!-- Demandé sans y être -->
            <section class="rounded-lg border border-gray-200 bg-white p-4 space-y-2">
              <h3 class="text-xs font-semibold text-gray-400 uppercase tracking-wide">Demandé sans y être</h3>
              <p v-if="!cv.demande_sans_y_etre.length" class="text-sm text-gray-400 italic">Vide.</p>
              <ul v-else class="space-y-2">
                <li
                  v-for="item in cv.demande_sans_y_etre" :key="item"
                  class="flex items-center gap-2 text-sm text-gray-700"
                >
                  <span class="flex-1">{{ item }}</span>
                  <select v-model="ajoutChoix[item]" class="text-xs border border-gray-200 rounded px-1.5 py-1">
                    <option value="">Non maîtrisée</option>
                    <option v-for="grp in cv.groupes" :key="grp.label" :value="grp.label">Maîtrisée — {{ grp.label }}</option>
                  </select>
                  <button
                    @click="ajouterCompetence(item)"
                    class="text-xs px-2 py-1 rounded bg-indigo-50 text-indigo-700 hover:bg-indigo-100 flex-shrink-0"
                  >Ajouter</button>
                </li>
              </ul>
            </section>

            <p v-if="cvActionError" class="text-xs text-red-600">{{ cvActionError }}</p>
          </template>
        </div>
      </div>

      <!-- Fiche entreprise -->
      <div v-else class="flex-1 overflow-y-auto p-6">
        <div class="max-w-3xl mx-auto space-y-4">
          <!-- Pas de fiche / erreur -->
          <div v-if="!fiche || fiche.statut === 'error'" class="rounded-lg border border-gray-200 bg-white p-6 flex flex-col items-center justify-center text-center gap-3">
            <p v-if="fiche?.error_message" class="text-sm text-red-600">{{ fiche.error_message }}</p>
            <p v-if="!isRetenue" class="text-sm text-gray-400 italic">La fiche n'est produite que pour une offre retenue.</p>
            <button
              v-else
              @click="preparerFiche"
              class="px-4 py-2.5 rounded-lg bg-indigo-600 text-white text-sm font-medium hover:bg-indigo-700 transition-colors"
            >
              Préparer la fiche
            </button>
          </div>

          <!-- En cours -->
          <div v-else-if="fiche.statut === 'pending'" class="rounded-lg border border-gray-200 bg-white p-6 flex items-center justify-center gap-3 text-sm text-gray-500">
            <svg class="w-5 h-5 animate-spin text-indigo-600" fill="none" viewBox="0 0 24 24">
              <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"/>
              <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8v4a4 4 0 00-4 4H4z"/>
            </svg>
            Recherche en cours…
          </div>

          <!-- Fiche prête -->
          <template v-else>
            <div class="rounded-lg border border-gray-200 bg-gray-50 px-4 py-3 space-y-2">
              <div class="text-xs text-gray-500 flex flex-wrap gap-x-4 gap-y-1">
                <span><span class="text-gray-400">Employeur</span> <span class="font-medium text-gray-700">{{ fiche.employeur_nom ?? 'non trouvé' }}</span></span>
                <span v-if="fiche.employeur_confiance"><span class="text-gray-400">Confiance</span> {{ fiche.employeur_confiance }}</span>
                <span><span class="text-gray-400">Mode</span> {{ fiche.mode === 'offre_seule' ? 'offre seule' : 'entreprise' }}</span>
              </div>
              <p v-if="fiche.presentation" class="text-sm text-gray-700 leading-relaxed">{{ fiche.presentation }}</p>
            </div>

            <div v-if="fiche.propose_intermediaire" class="flex items-center gap-2 text-xs bg-amber-50 border border-amber-200 rounded-lg px-3 py-2">
              <span class="text-amber-800">« {{ offer?.company }} » ressemble à un intermédiaire (agence / agrégateur), pas à l'employeur.</span>
              <button
                @click="ajouterIntermediaire"
                :disabled="addingIntermediaire"
                class="ml-auto shrink-0 px-2.5 py-1 rounded-full bg-amber-600 text-white hover:bg-amber-700 disabled:opacity-50"
              >{{ addingIntermediaire ? '…' : `Ajouter ${offer?.company} aux intermédiaires` }}</button>
            </div>

            <p v-if="!fiche.points.length" class="text-sm text-gray-400 italic">Aucun point restitué.</p>

            <div
              v-for="(point, idx) in fiche.points" :key="idx"
              class="rounded-lg border border-gray-200 bg-white p-4 space-y-3"
            >
              <div class="space-y-1">
                <p class="text-sm text-gray-800">{{ point.position }}</p>
                <p v-if="point.citation" class="text-xs text-gray-500 italic border-l-2 border-gray-200 pl-2">« {{ point.citation }} »</p>
                <a
                  v-if="lienSur(point.url)" :href="lienSur(point.url)!" target="_blank" rel="noopener noreferrer"
                  class="text-xs text-indigo-600 hover:underline break-all"
                >{{ point.url }} ↗</a>
              </div>

              <div class="flex flex-wrap items-center gap-1.5">
                <span class="text-[10px] text-gray-400 mr-1 w-16">Tas</span>
                <button
                  v-for="t in TAS" :key="t.value"
                  @click="annoter(idx, t.value)"
                  class="px-2.5 py-1 rounded-full border text-xs transition-colors"
                  :class="point.tas === t.value ? 'bg-teal-600 border-teal-600 text-white' : 'border-gray-200 text-gray-600 hover:border-teal-300'"
                >{{ t.label }}</button>
              </div>

              <div class="space-y-2">
                <button
                  @click="expliquer(idx)"
                  :disabled="explaining === idx"
                  class="text-xs text-indigo-600 hover:underline disabled:text-gray-400"
                >{{ explaining === idx ? 'Explication en cours…' : 'Expliquer' }}</button>
                <p v-if="explainError === idx" class="text-xs text-red-600">L'explication a échoué.</p>
                <div v-if="point.explication" class="text-xs text-gray-700 bg-gray-50 rounded p-3 whitespace-pre-wrap">{{ point.explication }}</div>
              </div>
            </div>
          </template>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import DOMPurify from 'dompurify'
import { marked } from 'marked'
import type { Cv, FicheEntreprise, FicheTas, Lettre, LettrePoint, LettreVersion, OfferDetail, TechInfo } from '~/stores/offers'

const config = useRuntimeConfig()
const router = useRouter()
const route = useRoute()

const id = computed(() => Number(route.params.id))
const offer = ref<OfferDetail | null>(null)

const fiche = ref<FicheEntreprise | null>(null)
const isRetenue = computed(() => offer.value?.verdict === 'retenu')

onMounted(async () => {
  offer.value = await $fetch<OfferDetail>(`${config.public.apiBase}/offers/${id.value}`)
  await chargerFiche()
  if (fiche.value?.statut === 'pending') startPolling()
  await chargerCv()
  if (cv.value?.statut === 'pending') startCvPolling()
  await chargerLettre()
  await chargerLettrePoints()
  await chargerLettreVersions()
  if (shouldPollLettre(lettre.value)) startLettrePolling()
})
onBeforeUnmount(() => {
  stopPolling()
  stopCvPolling()
  stopLettrePolling()
  if (cvBlobUrl) URL.revokeObjectURL(cvBlobUrl)
  if (lettreCopiedTimer) clearTimeout(lettreCopiedTimer)
})

async function retirerDesRetenues() {
  await $fetch(`${config.public.apiBase}/offers/${id.value}/verdict`, { method: 'DELETE' })
  router.back()
}

// ── Vérification d'expiration (EXE-77) ──────────────────────────────────────
const employerUrlEdit = ref('')
const employerUrlBusy = ref(false)
const employerUrlError = ref<string | null>(null)

watch(offer, (o) => { employerUrlEdit.value = o?.employer_url ?? '' }, { immediate: true })

async function enregistrerEmployerUrl() {
  employerUrlError.value = null
  employerUrlBusy.value = true
  try {
    await $fetch(`${config.public.apiBase}/offers/${id.value}/employer-url`, {
      method: 'PUT',
      body: { url: employerUrlEdit.value },
    })
    if (offer.value) offer.value.employer_url = employerUrlEdit.value
  } catch (e) {
    employerUrlError.value = (e as { data?: { detail?: string } })?.data?.detail ?? 'Action impossible.'
  } finally {
    employerUrlBusy.value = false
  }
}

// ── Fiche entreprise ──────────────────────────────────────────────────────
const ficheUrl = () => `${config.public.apiBase}/offers/${id.value}/fiche`
const TAS: { value: FicheTas, label: string }[] = [
  { value: 'lettre', label: 'Lettre' },
  { value: 'entretien', label: 'Entretien' },
  { value: 'rien', label: 'Rien' },
]
const explaining = ref<number | null>(null)
const explainError = ref<number | null>(null)
const addingIntermediaire = ref(false)
let pollTimer: ReturnType<typeof setInterval> | null = null

async function ajouterIntermediaire() {
  addingIntermediaire.value = true
  try {
    await $fetch(`${ficheUrl()}/intermediaire`, { method: 'POST' })
    await chargerFiche() // recalcule propose_intermediaire côté back, masque le bandeau
  } catch {
    // silencieux : le bandeau reste, l'utilisateur peut réessayer
  } finally {
    addingIntermediaire.value = false
  }
}

async function chargerFiche() {
  try {
    fiche.value = await $fetch<FicheEntreprise>(ficheUrl())
  } catch (e) {
    // 404 = pas encore de fiche ; toute autre erreur (réseau) garde l'état courant
    if ((e as { statusCode?: number }).statusCode === 404) fiche.value = null
  }
}

function stopPolling() {
  if (pollTimer) { clearInterval(pollTimer); pollTimer = null }
}

const POLL_MAX = 180 // 15 min à 5 s : au-delà, la génération est considérée perdue

function startPolling() {
  stopPolling()
  let ticks = 0
  pollTimer = setInterval(async () => {
    await chargerFiche()
    ticks++
    if (fiche.value?.statut !== 'pending') stopPolling() // done ou error : on s'arrête
    else if (ticks >= POLL_MAX) {
      stopPolling()
      fiche.value = { ...fiche.value, statut: 'error', error_message: 'Délai dépassé. Relancer la fiche.' }
    }
  }, 5000)
}

function lienSur(url: string | null): string | null {
  return url && /^https?:\/\//i.test(url) ? url : null // contenu issu du web : http(s) seulement
}

async function preparerFiche() {
  const empty = { mode: null, presentation: null, employeur_nom: null, employeur_confiance: null, points: [], session_id: null, cost_usd: null, propose_intermediaire: false }
  try {
    await $fetch(ficheUrl(), { method: 'POST' })
  } catch {
    fiche.value = { ...empty, statut: 'error', error_message: 'Impossible de lancer la fiche.' }
    return
  }
  fiche.value = { ...empty, statut: 'pending', error_message: null }
  startPolling()
}

async function annoter(idx: number, value: FicheTas) {
  const point = fiche.value?.points[idx]
  if (!point) return
  const next = point.tas === value ? null : value // re-clic = effacer
  point.tas = next
  try {
    await $fetch(`${ficheUrl()}/points/${idx}`, { method: 'PATCH', body: { tas: next } })
  } catch {
    await chargerFiche()
  }
}

async function expliquer(idx: number) {
  const point = fiche.value?.points[idx]
  if (!point) return
  explaining.value = idx
  explainError.value = null
  try {
    point.explication = await $fetch<string>(`${ficheUrl()}/points/${idx}/explain`, { method: 'POST' })
  } catch {
    explainError.value = idx
  } finally {
    explaining.value = null
  }
}

function cardBadge(title: string): { label: string, class: string } {
  if (title === 'Entreprise' && fiche.value) {
    if (fiche.value.statut === 'pending') return { label: 'en cours', class: 'bg-amber-50 text-amber-600' }
    if (fiche.value.statut === 'done') return { label: 'prête', class: 'bg-green-50 text-green-700' }
    return { label: 'erreur', class: 'bg-red-50 text-red-600' }
  }
  if (title === 'CV' && cv.value) {
    if (cv.value.statut === 'pending') return { label: 'en cours', class: 'bg-amber-50 text-amber-600' }
    if (cv.value.statut === 'done') return { label: 'prêt', class: 'bg-green-50 text-green-700' }
    return { label: 'erreur', class: 'bg-red-50 text-red-600' }
  }
  return { label: 'à produire', class: 'bg-gray-100 text-gray-400' }
}

function cardPreview(title: string): string {
  if (title === 'Entreprise' && fiche.value?.statut === 'done') {
    return `${fiche.value.employeur_nom ?? 'employeur non trouvé'} · ${fiche.value.points.length} points`
  }
  if (title === 'CV' && cv.value?.statut === 'done') {
    return `${cv.value.au_cv.length} compétences`
  }
  return 'Vide'
}

// ── CV adapté ────────────────────────────────────────────────────────────
const cv = ref<Cv | null>(null)
const ajoutChoix = ref<Record<string, string>>({})
const cvActionError = ref<string | null>(null)
const cvHtmlUrl = ref<string | null>(null)
let cvBlobUrl: string | null = null
let cvPollTimer: ReturnType<typeof setInterval> | null = null

const EMPTY_CV: Cv = {
  statut: 'pending',
  html: null,
  titre: null,
  localisation: null,
  au_cv: [],
  groupes: [],
  notions: [],
  demande_sans_y_etre: [],
  ajouts_permis: [],
  seuil_utilise: null,
  cost_usd: null,
  error_message: null,
  created_at: '',
}

const cvUrl = () => `${config.public.apiBase}/offers/${id.value}/cv`

async function chargerCv() {
  try {
    cv.value = await $fetch<Cv>(cvUrl())
  } catch (e) {
    // 404 = pas encore de CV ; toute autre erreur (réseau) garde l'état courant
    if ((e as { statusCode?: number }).statusCode === 404) cv.value = null
  }
}

function stopCvPolling() {
  if (cvPollTimer) { clearInterval(cvPollTimer); cvPollTimer = null }
}

function startCvPolling() {
  stopCvPolling()
  let ticks = 0
  cvPollTimer = setInterval(async () => {
    await chargerCv()
    ticks++
    if (cv.value?.statut !== 'pending') stopCvPolling() // done ou error : on s'arrête
    else if (ticks >= POLL_MAX) {
      stopCvPolling()
      cv.value = { ...cv.value, statut: 'error', error_message: 'Délai dépassé. Relancer le CV.' }
    }
  }, 5000)
}

async function genererCv() {
  cvActionError.value = null
  try {
    const res = await $fetch<Cv>(cvUrl(), { method: 'POST' })
    if (res.statut === 'done') {
      cv.value = res // déjà terminé : rendu tel quel, aucun rappel du modèle
    } else {
      cv.value = { ...EMPTY_CV, statut: 'pending' }
      startCvPolling()
    }
  } catch {
    cv.value = { ...EMPTY_CV, statut: 'error', error_message: 'Impossible de lancer le CV.' }
  }
}

function messageErreurCv(e: unknown): string {
  const detail = (e as { data?: { detail?: string } })?.data?.detail
  return detail ?? 'Action impossible.'
}

async function ajouterCompetence(competence: string) {
  cvActionError.value = null
  const groupe = ajoutChoix.value[competence] || null
  try {
    cv.value = await $fetch<Cv>(`${cvUrl()}/skills`, {
      method: 'POST',
      body: { action: 'ajout', competence, maitrisee: groupe !== null, groupe },
    })
    delete ajoutChoix.value[competence]
  } catch (e) {
    cvActionError.value = messageErreurCv(e)
  }
}

async function retirerCompetence(competence: string) {
  cvActionError.value = null
  try {
    cv.value = await $fetch<Cv>(`${cvUrl()}/skills`, {
      method: 'POST',
      body: { action: 'retrait', competence },
    })
  } catch (e) {
    cvActionError.value = messageErreurCv(e)
  }
}

watch(() => cv.value?.html, (html) => {
  if (cvBlobUrl) { URL.revokeObjectURL(cvBlobUrl); cvBlobUrl = null }
  if (html) cvBlobUrl = URL.createObjectURL(new Blob([html], { type: 'text/html' }))
  cvHtmlUrl.value = cvBlobUrl
})

// ── Lettre de motivation ────────────────────────────────────────────────────
const lettre = ref<Lettre | null>(null)
const lettrePoints = ref<LettrePoint[] | null>(null)
const lettreVersions = ref<LettreVersion[]>([])
const texteEdit = ref('')
const lettreActionError = ref<string | null>(null)
const lettreBusy = ref(false)
const lettreCopied = ref(false)
let lettreCopiedTimer: ReturnType<typeof setTimeout> | null = null
let lettrePollTimer: ReturnType<typeof setInterval> | null = null

const ficheDone = computed(() => fiche.value?.statut === 'done')
const lettreUrl = () => `${config.public.apiBase}/offers/${id.value}/lettre`

const EMPTY_LETTRE: Lettre = {
  statut: 'pending',
  texte: null,
  tournures_signalees: [],
  nb_mots: null,
  depasse_longueur: false,
  modele: null,
  cost_usd: null,
  error_message: null,
  created_at: '',
  regeneration_en_cours: false,
  regeneration_error: null,
}

async function chargerLettre() {
  try {
    lettre.value = await $fetch<Lettre>(lettreUrl())
    texteEdit.value = lettre.value.texte ?? ''
  } catch (e) {
    // 404 = pas encore de lettre ; toute autre erreur (réseau) garde l'état courant
    if ((e as { statusCode?: number }).statusCode === 404) lettre.value = null
  }
}

async function chargerLettrePoints() {
  try {
    lettrePoints.value = await $fetch<LettrePoint[]>(`${lettreUrl()}/points`)
  } catch (e) {
    if ((e as { statusCode?: number }).statusCode === 404) lettrePoints.value = null
  }
}

async function chargerLettreVersions() {
  lettreVersions.value = await $fetch<LettreVersion[]>(`${lettreUrl()}/versions`)
}

function shouldPollLettre(l: Lettre | null): boolean {
  return !!l && (l.statut === 'pending' || l.regeneration_en_cours)
}

function stopLettrePolling() {
  if (lettrePollTimer) { clearInterval(lettrePollTimer); lettrePollTimer = null }
}

function startLettrePolling() {
  stopLettrePolling()
  let ticks = 0
  lettrePollTimer = setInterval(async () => {
    await chargerLettre()
    ticks++
    if (!shouldPollLettre(lettre.value)) {
      stopLettrePolling()
      await chargerLettreVersions()
    } else if (ticks >= POLL_MAX) {
      stopLettrePolling()
      if (lettre.value?.regeneration_en_cours) {
        lettre.value = { ...lettre.value, regeneration_en_cours: false, regeneration_error: 'Délai dépassé. Relancer la génération.' }
      } else {
        lettre.value = { ...(lettre.value ?? EMPTY_LETTRE), statut: 'error', error_message: 'Délai dépassé. Relancer la lettre.' }
      }
    }
  }, 5000)
}

function messageErreurLettre(e: unknown): string {
  const detail = (e as { data?: { detail?: string } })?.data?.detail
  return detail ?? 'Action impossible.'
}

async function genererLettre() {
  lettreActionError.value = null
  lettreBusy.value = true
  try {
    const res = await $fetch<Lettre>(lettreUrl(), { method: 'POST' })
    if (res.statut === 'done') {
      lettre.value = res
      texteEdit.value = res.texte ?? ''
      await chargerLettreVersions()
    } else {
      lettre.value = { ...EMPTY_LETTRE, statut: 'pending' }
      startLettrePolling()
    }
  } catch (e) {
    lettreActionError.value = messageErreurLettre(e)
  } finally {
    lettreBusy.value = false
  }
}

async function regenererLettre() {
  lettreActionError.value = null
  lettreBusy.value = true
  try {
    await $fetch(`${lettreUrl()}/regenerer`, { method: 'POST' })
    if (lettre.value) lettre.value = { ...lettre.value, regeneration_en_cours: true, regeneration_error: null }
    startLettrePolling()
  } catch (e) {
    lettreActionError.value = messageErreurLettre(e)
  } finally {
    lettreBusy.value = false
  }
}

async function sauvegarderTexte() {
  lettreActionError.value = null
  try {
    lettre.value = await $fetch<Lettre>(`${lettreUrl()}/texte`, { method: 'PUT', body: { texte: texteEdit.value } })
    texteEdit.value = lettre.value.texte ?? ''
    await chargerLettreVersions()
  } catch (e) {
    lettreActionError.value = messageErreurLettre(e)
  }
}

async function togglePointChoisi(idx: number) {
  if (!lettrePoints.value) return
  const point = lettrePoints.value[idx]
  if (!point) return
  point.choisi = !point.choisi // optimiste
  const indices = lettrePoints.value.reduce<number[]>((acc, p, i) => { if (p.choisi) acc.push(i); return acc }, [])
  try {
    lettrePoints.value = await $fetch<LettrePoint[]>(`${lettreUrl()}/points`, { method: 'PUT', body: { indices } })
  } catch {
    await chargerLettrePoints() // revert en cas d'échec
  }
}

async function copierTexte() {
  await navigator.clipboard.writeText(texteEdit.value)
  lettreCopied.value = true
  if (lettreCopiedTimer) clearTimeout(lettreCopiedTimer)
  lettreCopiedTimer = setTimeout(() => { lettreCopied.value = false }, 1500)
}

// ── Frise ────────────────────────────────────────────────────────────────
const STEPS = ['Retenue', 'Prête à l\'envoi', 'Candidature envoyée', 'Entretien à préparer']

// ── Cartes + overlay ──────────────────────────────────────────────────────
const CARDS = [
  { title: 'Entreprise' },
  { title: 'CV' },
  { title: 'Lettre de motivation' },
]
const activeCard = ref<string | null>(null)
function openCard(title: string) { activeCard.value = title }

// ── Markdown rendering ────────────────────────────────────────────────────
const renderedDescription = computed(() =>
  offer.value?.description ? DOMPurify.sanitize(marked(offer.value.description) as string) : '',
)

// ── Tech split ────────────────────────────────────────────────────────────
const ownedTechs = computed((): TechInfo[] => {
  if (!offer.value) return []
  const names = new Set(offer.value.techs_matched ?? [])
  return (offer.value.extracted_facts?.techs_required ?? []).filter(t => names.has(t.name))
})
const missingTechs = computed((): TechInfo[] => {
  if (!offer.value) return []
  const names = new Set(offer.value.techs_missing ?? [])
  return (offer.value.extracted_facts?.techs_required ?? []).filter(t => names.has(t.name))
})

// ── Helpers ───────────────────────────────────────────────────────────────
function techBadgeClass(importance: string | null) {
  if (importance === 'core')         return 'bg-blue-100 text-blue-800'
  if (importance === 'required')     return 'bg-green-100 text-green-800'
  if (importance === 'nice_to_have') return 'bg-gray-100 text-gray-500'
  return 'bg-gray-100 text-gray-400'
}

const CATEGORY_LABELS: Record<string, string> = {
  parfait: '★ Parfait',
  reve: '◈ Rêve',
  atteignable: '✓ Atteignable',
  hors: '✗ Hors',
  hors_perimetre: '⊘ Hors-périmètre',
}

function categoryLabel(cat: string | null | undefined): string {
  return cat ? (CATEGORY_LABELS[cat] ?? cat) : '?'
}

function categoryBadgeClass(cat: string | null | undefined): string {
  if (cat === 'parfait')        return 'bg-green-50 border-green-300 text-green-700'
  if (cat === 'reve')           return 'bg-indigo-50 border-indigo-300 text-indigo-700'
  if (cat === 'atteignable')    return 'bg-amber-50 border-amber-300 text-amber-700'
  if (cat === 'hors')           return 'bg-gray-100 border-gray-400 text-gray-600'
  if (cat === 'hors_perimetre') return 'bg-slate-100 border-slate-400 text-slate-600'
  return 'bg-gray-100 border-gray-200 text-gray-500'
}
</script>
