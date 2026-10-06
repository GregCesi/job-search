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
            @click="ajouterAuJeuReference"
            :disabled="ajoutReferenceEnCours"
            class="text-sm text-gray-400 hover:text-indigo-600 transition-colors disabled:opacity-50"
          >
            {{ libelleAjoutReference }}
          </button>
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
                  :class="stepActive(step)
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
        <div class="w-1/3 flex flex-col overflow-hidden bg-gray-50">
          <div v-if="offer" class="flex-1 overflow-y-auto p-6 flex flex-col gap-3">

            <!-- Entreprise -->
            <div
              @click="openCard('Entreprise')"
              class="rounded-lg border border-gray-200 bg-white p-4 cursor-pointer hover:border-indigo-200 hover:shadow-sm transition-all flex flex-col gap-2"
            >
              <div class="flex items-center justify-between">
                <span class="text-sm font-medium text-gray-700">Entreprise</span>
                <span class="flex items-center gap-1.5">
                  <svg v-if="cardAvancement('Entreprise')?.etat === 'en_cours'" class="w-3 h-3 animate-spin text-amber-500" fill="none" viewBox="0 0 24 24">
                    <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"/>
                    <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8v4a4 4 0 00-4 4H4z"/>
                  </svg>
                  <span class="text-[10px] px-2 py-0.5 rounded-full font-medium" :class="cardBadge('Entreprise').class">{{ cardBadge('Entreprise').label }}</span>
                </span>
              </div>
              <div class="h-10 rounded bg-gray-50 border border-dashed border-gray-200 flex items-center justify-center">
                <span class="text-xs text-gray-300 italic">{{ cardPreview('Entreprise') }}</span>
              </div>
            </div>

            <!-- CV et Lettre, côte à côte -->
            <div class="flex gap-3">
              <div
                ref="cvCardEl"
                @click="openCard('CV')"
                class="flex-1 min-w-0 rounded-lg border border-gray-200 bg-white p-4 cursor-pointer hover:border-indigo-200 hover:shadow-sm transition-all flex flex-col gap-2"
              >
                <div class="flex items-center justify-between">
                  <span class="text-sm font-medium text-gray-700">CV</span>
                  <span class="flex items-center gap-1.5">
                    <svg v-if="cardAvancement('CV')?.etat === 'en_cours'" class="w-3 h-3 animate-spin text-amber-500" fill="none" viewBox="0 0 24 24">
                      <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"/>
                      <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8v4a4 4 0 00-4 4H4z"/>
                    </svg>
                    <span class="text-[10px] px-2 py-0.5 rounded-full font-medium" :class="cardBadge('CV').class">{{ cardBadge('CV').label }}</span>
                  </span>
                </div>
                <div
                  v-if="miniatureVisible('CV')"
                  class="relative mx-auto overflow-hidden rounded border border-gray-100 bg-white"
                  :style="{ width: `${miniatureLargeur}px`, height: `${miniatureHauteur}px` }"
                >
                  <iframe
                    :srcdoc="cv?.html ?? ''"
                    class="absolute top-0 left-0 origin-top-left border-0 pointer-events-none"
                    :style="{ width: '794px', height: '1123px', transform: `scale(${miniatureEchelle})` }"
                    tabindex="-1"
                    title="Miniature du CV"
                  />
                </div>
                <div v-else class="h-10 rounded bg-gray-50 border border-dashed border-gray-200 flex items-center justify-center">
                  <span class="text-xs text-gray-300 italic">{{ cardPreview('CV') }}</span>
                </div>
              </div>

              <div
                @click="openCard('Lettre de motivation')"
                class="flex-1 min-w-0 rounded-lg border border-gray-200 bg-white p-4 cursor-pointer hover:border-indigo-200 hover:shadow-sm transition-all flex flex-col gap-2"
              >
                <div class="flex items-center justify-between">
                  <span class="text-sm font-medium text-gray-700">Lettre de motivation</span>
                  <span class="flex items-center gap-1.5">
                    <svg v-if="cardAvancement('Lettre de motivation')?.etat === 'en_cours'" class="w-3 h-3 animate-spin text-amber-500" fill="none" viewBox="0 0 24 24">
                      <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"/>
                      <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8v4a4 4 0 00-4 4H4z"/>
                    </svg>
                    <span class="text-[10px] px-2 py-0.5 rounded-full font-medium" :class="cardBadge('Lettre de motivation').class">{{ cardBadge('Lettre de motivation').label }}</span>
                  </span>
                </div>
                <div
                  v-if="miniatureVisible('Lettre de motivation')"
                  class="relative mx-auto overflow-hidden rounded border border-gray-100 bg-white"
                  :style="{ width: `${miniatureLargeur}px`, height: `${miniatureHauteur}px` }"
                >
                  <iframe
                    :srcdoc="lettreMiseEnPageHtml ?? ''"
                    class="absolute top-0 left-0 origin-top-left border-0 pointer-events-none"
                    :style="{ width: '794px', height: '1123px', transform: `scale(${miniatureEchelle})` }"
                    tabindex="-1"
                    title="Miniature de la lettre"
                  />
                </div>
                <div v-else class="h-10 rounded bg-gray-50 border border-dashed border-gray-200 flex items-center justify-center">
                  <span class="text-xs text-gray-300 italic">{{ cardPreview('Lettre de motivation') }}</span>
                </div>
              </div>
            </div>

            <!-- Mail de candidature -->
            <div
              @click="openCard('Mail de candidature')"
              class="rounded-lg border border-gray-200 bg-white p-4 cursor-pointer hover:border-indigo-200 hover:shadow-sm transition-all flex flex-col gap-2"
            >
              <div class="flex items-center justify-between">
                <span class="text-sm font-medium text-gray-700">Mail de candidature</span>
                <span class="flex items-center gap-1.5">
                  <svg v-if="cardAvancement('Mail de candidature')?.etat === 'en_cours'" class="w-3 h-3 animate-spin text-amber-500" fill="none" viewBox="0 0 24 24">
                    <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"/>
                    <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8v4a4 4 0 00-4 4H4z"/>
                  </svg>
                  <span class="text-[10px] px-2 py-0.5 rounded-full font-medium" :class="cardBadge('Mail de candidature').class">{{ cardBadge('Mail de candidature').label }}</span>
                </span>
              </div>
              <div class="h-10 rounded bg-gray-50 border border-dashed border-gray-200 flex items-center justify-center">
                <span class="text-xs text-gray-300 italic">{{ cardPreview('Mail de candidature') }}</span>
              </div>
            </div>

            <!-- Bouton Tout télécharger -->
            <div class="mt-auto pt-2 space-y-1">
              <button
                @click="telechargerTout"
                :disabled="!!telechargerToutLabel || telechargerToutBusy"
                :title="telechargerToutLabel ?? undefined"
                class="w-full px-4 py-2.5 rounded-lg bg-indigo-600 text-white text-sm font-medium hover:bg-indigo-700 transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
              >
                {{ telechargerToutBusy ? 'Téléchargement…' : 'Tout télécharger' }}
              </button>
              <p v-if="cvPdfError" class="text-xs text-red-600 text-center">{{ cvPdfError }}</p>
              <p v-if="lettrePdfError" class="text-xs text-red-600 text-center">{{ lettrePdfError }}</p>

              <!-- Candidature envoyée (EXE-139) -->
              <template v-if="!pieces?.envoyee_le">
                <button
                  @click="marquerEnvoyee"
                  :disabled="!pieces?.prete_a_l_envoi || envoyeeBusy"
                  :title="envoyeeRaison ?? undefined"
                  class="w-full px-4 py-2.5 rounded-lg border border-indigo-200 text-indigo-700 text-sm font-medium hover:bg-indigo-50 transition-colors disabled:opacity-50 disabled:cursor-not-allowed disabled:border-gray-200 disabled:text-gray-400"
                >
                  Candidature envoyée
                </button>
                <p v-if="envoyeeRaison" class="text-xs text-gray-400 text-center">{{ envoyeeRaison }}</p>
              </template>
              <div v-else class="flex items-center justify-center gap-2 text-xs text-gray-500">
                <span>Envoyée le {{ formatDateFr(pieces.envoyee_le) }}</span>
                <button @click="annulerEnvoyee" :disabled="envoyeeBusy" class="text-indigo-600 hover:underline disabled:opacity-50">Annuler</button>
              </div>
              <p v-if="envoyeeError" class="text-xs text-red-600 text-center">{{ envoyeeError }}</p>
            </div>
          </div>
        </div>

      </div>
    </div>

    <!-- Aperçu plein écran CV/Lettre, offre à côté (EXE-129) -->
    <div
      v-if="apercuCard"
      class="fixed inset-0 z-50 bg-white flex flex-col"
    >
      <div class="flex items-center justify-between px-6 py-4 border-b border-gray-200 flex-shrink-0">
        <div class="flex items-center gap-4">
          <h2 class="text-base font-semibold text-gray-900">{{ apercuCard }}</h2>
          <PieceReadyToggle
            v-if="pieces"
            :pret="(apercuCard === 'CV' ? pieces.cv.statut : pieces.lettre.statut) === 'prete'"
            :disabled="(apercuCard === 'CV' ? pieces.cv.statut : pieces.lettre.statut) === 'a_faire'"
            @toggle="apercuCard === 'CV' ? toggleCvPret() : toggleLettrePret()"
          />
        </div>
        <div class="flex items-center gap-4">
          <button @click="modifierDepuisApercu" class="text-sm text-indigo-600 hover:underline">Modifier</button>
          <button @click="fermerApercu" class="text-gray-400 hover:text-gray-600" aria-label="Fermer l'aperçu">
            <svg class="w-5 h-5" fill="none" stroke="currentColor" stroke-width="2" viewBox="0 0 24 24">
              <path stroke-linecap="round" stroke-linejoin="round" d="M6 18L18 6M6 6l12 12"/>
            </svg>
          </button>
        </div>
      </div>
      <div class="flex-1 overflow-hidden flex">
        <div v-if="offer" class="flex-1 min-w-0 h-full overflow-y-auto border-r border-gray-100 p-6">
          <OfferSidePanel
            :offer="offer"
            :owned-techs="ownedTechs"
            :missing-techs="missingTechs"
            :rendered-description="renderedDescription"
          />
        </div>
        <div class="flex-shrink-0 h-full overflow-y-auto p-3 bg-gray-50">
          <p v-if="apercuCard === 'Lettre de motivation' && lettreMiseEnPageError" class="text-sm text-red-600" style="width: 210mm">{{ lettreMiseEnPageError }}</p>
          <iframe
            v-if="apercuCard === 'CV' && cv?.html"
            ref="cvFrame"
            :srcdoc="cv.html"
            class="border-0 bg-white"
            style="width: 210mm"
            title="Aperçu du CV"
            @load="resizeFrame(cvFrame)"
          />
          <iframe
            v-else-if="apercuCard === 'Lettre de motivation' && lettreMiseEnPageHtml"
            ref="lettreFrame"
            :srcdoc="lettreMiseEnPageHtml"
            class="border-0 bg-white"
            style="width: 210mm"
            title="Aperçu de la lettre"
            @load="resizeFrame(lettreFrame)"
          />
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
        <div class="flex items-center gap-4">
          <h2 class="text-base font-semibold text-gray-900">{{ activeCard }}</h2>
          <PieceReadyToggle
            v-if="pieces && (activeCard === 'CV' || activeCard === 'Lettre de motivation')"
            :pret="(activeCard === 'CV' ? pieces.cv.statut : pieces.lettre.statut) === 'prete'"
            :disabled="(activeCard === 'CV' ? pieces.cv.statut : pieces.lettre.statut) === 'a_faire'"
            @toggle="activeCard === 'CV' ? toggleCvPret() : toggleLettrePret()"
          />
        </div>
        <div class="flex items-center gap-4">
          <button @click="activeCard = null" class="text-gray-400 hover:text-gray-600">
            <svg class="w-5 h-5" fill="none" stroke="currentColor" stroke-width="2" viewBox="0 0 24 24">
              <path stroke-linecap="round" stroke-linejoin="round" d="M6 18L18 6M6 6l12 12"/>
            </svg>
          </button>
        </div>
      </div>
      <div v-if="activeCard === 'Lettre de motivation'" class="flex-1 overflow-hidden flex">
        <div v-if="offer" class="flex-1 min-w-0 h-full overflow-y-auto border-r border-gray-100 p-6">
          <OfferSidePanel
            :offer="offer"
            :owned-techs="ownedTechs"
            :missing-techs="missingTechs"
            :rendered-description="renderedDescription"
          />
        </div>
        <div class="flex-shrink-0 h-full overflow-y-auto p-3">
        <div class="space-y-4 mx-auto" style="width: 210mm">
          <!-- Statut de pièce (EXE-101) ; la marque Prête vit dans la barre du haut (EXE-138) -->
          <div v-if="pieces" class="sticky top-0 z-10 rounded-lg border border-gray-200 bg-white p-4 flex items-center gap-2 text-xs font-medium flex-wrap">
            <template v-for="(step, idx) in PIECE_STEPS" :key="step.value">
              <span :class="pieces.lettre.statut === step.value ? 'text-indigo-600' : 'text-gray-300'">{{ step.label }}</span>
              <svg v-if="idx < PIECE_STEPS.length - 1" class="w-3 h-3 text-gray-300 flex-shrink-0" fill="none" stroke="currentColor" stroke-width="2" viewBox="0 0 24 24">
                <path stroke-linecap="round" stroke-linejoin="round" d="M9 5l7 7-7 7"/>
              </svg>
            </template>
          </div>
          <p v-if="lettrePretError" class="text-xs text-red-600">{{ lettrePretError }}</p>

          <!-- Non éligible -->
          <div v-if="!isRetenue || lettreRaisonAttente" class="rounded-lg border border-gray-200 bg-white p-6 flex flex-col items-center justify-center text-center gap-3">
            <p v-if="!isRetenue" class="text-sm text-gray-400 italic">La lettre n'est générée que pour une offre retenue.</p>
            <p v-else class="text-sm text-gray-400 italic">{{ lettreRaisonAttente }}</p>
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
                ref="texteEditRef"
                v-model="texteEdit"
                :disabled="lettre.regeneration_en_cours"
                rows="1"
                class="w-full rounded-lg border border-gray-200 p-3 text-sm text-gray-800 leading-relaxed resize-none overflow-hidden disabled:bg-gray-50 disabled:text-gray-400"
                @input="autoGrowTexte"
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
                <button
                  @click="telechargerLettrePdf"
                  class="text-xs px-2 py-1 rounded bg-indigo-50 text-indigo-700 hover:bg-indigo-100"
                >Télécharger le PDF</button>
              </div>
              <p v-if="lettre.regeneration_error" class="text-xs text-red-600">{{ lettre.regeneration_error }}</p>
              <p v-if="lettreActionError" class="text-xs text-red-600">{{ lettreActionError }}</p>
              <p v-if="lettrePdfError" class="text-xs text-red-600">{{ lettrePdfError }}</p>
            </template>

            <!-- Historique des versions -->
            <section class="rounded-lg border border-gray-200 bg-white p-4 space-y-2">
              <h3 class="text-xs font-semibold text-gray-400 uppercase tracking-wide">Historique des versions</h3>
              <p v-if="!lettreVersionsRecentesDabord.length" class="text-sm text-gray-400 italic">Aucune version.</p>
              <div v-else class="space-y-2">
                <details v-for="(v, i) in lettreVersionsRecentesDabord" :key="i" class="rounded border border-gray-200 bg-gray-50">
                  <summary class="cursor-pointer px-3 py-2 text-xs text-gray-500 flex items-center justify-between select-none">
                    <span>{{ formatDateHeure(v.created_at) }}</span>
                    <span class="px-1.5 py-0.5 rounded bg-gray-100 text-gray-500 flex-shrink-0 ml-2">{{ v.origine === 'moi' ? 'moi' : 'modèle' }}</span>
                  </summary>
                  <p class="text-xs text-gray-700 whitespace-pre-wrap px-3 pb-3">{{ v.texte }}</p>
                </details>
              </div>
            </section>
          </template>
        </div>
        </div>
      </div>

      <!-- CV adapté -->
      <div v-else-if="activeCard === 'CV'" class="flex-1 overflow-hidden flex">
        <div v-if="offer" class="flex-1 min-w-0 h-full overflow-y-auto border-r border-gray-100 p-6">
          <OfferSidePanel
            :offer="offer"
            :owned-techs="ownedTechs"
            :missing-techs="missingTechs"
            :rendered-description="renderedDescription"
          />
        </div>
        <div class="flex-shrink-0 h-full overflow-y-auto p-3">
        <div class="space-y-5 mx-auto" style="width: 210mm">
          <!-- Statut de pièce (EXE-101) ; la marque Prête vit dans la barre du haut (EXE-138) -->
          <div v-if="pieces" class="sticky top-0 z-10 rounded-lg border border-gray-200 bg-white p-4 flex items-center gap-2 text-xs font-medium flex-wrap">
            <template v-for="(step, idx) in PIECE_STEPS" :key="step.value">
              <span :class="pieces.cv.statut === step.value ? 'text-indigo-600' : 'text-gray-300'">{{ step.label }}</span>
              <svg v-if="idx < PIECE_STEPS.length - 1" class="w-3 h-3 text-gray-300 flex-shrink-0" fill="none" stroke="currentColor" stroke-width="2" viewBox="0 0 24 24">
                <path stroke-linecap="round" stroke-linejoin="round" d="M9 5l7 7-7 7"/>
              </svg>
            </template>
          </div>
          <p v-if="cvPretError" class="text-xs text-red-600">{{ cvPretError }}</p>

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
            <div class="rounded-lg border border-gray-200 bg-gray-50 px-4 py-3 space-y-3">
              <div class="flex items-center justify-between gap-4">
                <p class="text-xs text-gray-500">
                  <span class="text-gray-400">Lieu</span> <span class="font-medium text-gray-700">{{ cv.localisation ?? '—' }}</span>
                </p>
                <div class="flex items-center gap-3 flex-shrink-0">
                  <a
                    v-if="cvHtmlUrl"
                    :href="cvHtmlUrl"
                    target="_blank"
                    rel="noopener noreferrer"
                    class="text-indigo-600 hover:underline font-medium text-sm"
                  >Ouvrir le CV ↗</a>
                  <button
                    @click="telechargerCvPdf"
                    class="text-xs px-2 py-1 rounded bg-indigo-50 text-indigo-700 hover:bg-indigo-100"
                  >Télécharger le PDF</button>
                </div>
              </div>

              <div class="flex items-center gap-2">
                <input
                  v-model="cvTitreEdit"
                  type="text"
                  placeholder="Titre du CV"
                  class="flex-1 rounded border border-gray-200 px-2 py-1 text-xs"
                >
                <button
                  @click="enregistrerCvTitre"
                  class="px-2.5 py-1 rounded bg-indigo-50 text-indigo-700 hover:bg-indigo-100 text-xs flex-shrink-0"
                >Enregistrer</button>
              </div>
              <label class="flex items-center gap-2 text-xs text-gray-500">
                <input type="checkbox" v-model="cvTitreParDefaut">
                Utiliser ce titre pour les prochains CV
              </label>
              <p v-if="cvTitreError" class="text-xs text-red-600">{{ cvTitreError }}</p>

              <div v-if="cvTitreDefaut" class="flex items-center gap-2 text-xs text-gray-500 pt-2 border-t border-gray-100">
                <span>Titre par défaut <span class="font-medium text-gray-700">{{ cvTitreDefaut }}</span></span>
                <button @click="effacerCvTitreDefaut" class="text-gray-400 hover:text-red-500">Effacer</button>
              </div>
              <p v-if="cvTitreDefautError" class="text-xs text-red-600">{{ cvTitreDefautError }}</p>
            </div>
            <p v-if="cvPdfError" class="text-xs text-red-600">{{ cvPdfError }}</p>

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
      </div>

      <!-- Mail de candidature -->
      <div v-else-if="activeCard === 'Mail de candidature'" class="flex-1 overflow-y-auto p-6">
        <div class="max-w-3xl mx-auto space-y-4">
          <div v-if="mailError" class="rounded-lg border border-gray-200 bg-white p-6 flex items-center justify-center text-center text-sm text-red-600">
            {{ mailError }}
          </div>
          <template v-else-if="mail">
            <section class="rounded-lg border border-gray-200 bg-white p-4 space-y-2">
              <div class="flex items-center justify-between">
                <h3 class="text-xs font-semibold text-gray-400 uppercase tracking-wide">Objet</h3>
                <button
                  @click="copierMailObjet"
                  class="text-xs px-2 py-1 rounded bg-indigo-50 text-indigo-700 hover:bg-indigo-100"
                >{{ mailObjetCopied ? 'Copié !' : 'Copier' }}</button>
              </div>
              <p class="text-sm text-gray-800">{{ mail.objet }}</p>
            </section>
            <section class="rounded-lg border border-gray-200 bg-white p-4 space-y-2">
              <div class="flex items-center justify-between">
                <h3 class="text-xs font-semibold text-gray-400 uppercase tracking-wide">Corps</h3>
                <button
                  @click="copierMailCorps"
                  class="text-xs px-2 py-1 rounded bg-indigo-50 text-indigo-700 hover:bg-indigo-100"
                >{{ mailCorpsCopied ? 'Copié !' : 'Copier' }}</button>
              </div>
              <p class="text-sm text-gray-800 whitespace-pre-wrap">{{ mail.corps }}</p>
            </section>
          </template>
          <div v-else class="rounded-lg border border-gray-200 bg-white p-6 flex items-center justify-center text-sm text-gray-400">
            Chargement…
          </div>
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
import type { Avancement, AvancementPiece, Cv, FicheEntreprise, FicheTas, Lettre, LettrePoint, LettreVersion, MailCandidature, OfferDetail, PieceInfo, Pieces, PieceStatut, TechInfo } from '~/stores/offers'

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
  await chargerCvTitreDefaut()
  await chargerLettre()
  await syncLettreMiseEnPage()
  await chargerLettrePoints()
  await chargerLettreVersions()
  if (shouldPollLettre(lettre.value)) startLettrePolling()
  if (isRetenue.value) {
    await chargerPieces()
    await chargerAvancement()
    if (avancementActif(avancement.value)) startAvancementPolling()
  }
})
onBeforeUnmount(() => {
  stopPolling()
  stopCvPolling()
  stopLettrePolling()
  stopAvancementPolling()
  if (cvBlobUrl) URL.revokeObjectURL(cvBlobUrl)
  if (lettreCopiedTimer) clearTimeout(lettreCopiedTimer)
  if (mailObjetTimer) clearTimeout(mailObjetTimer)
  if (mailCorpsTimer) clearTimeout(mailCorpsTimer)
})

async function retirerDesRetenues() {
  await $fetch(`${config.public.apiBase}/offers/${id.value}/verdict`, { method: 'DELETE' })
  router.back()
}

// ── Jeu de référence (EXE-123) ──────────────────────────────────────────────
const ajoutReferenceStatut = ref<'ajoutee' | 'deja_presente' | 'sans_faits' | null>(null)
const ajoutReferenceEnCours = ref(false)
const libelleAjoutReference = computed(() => {
  if (ajoutReferenceStatut.value === 'ajoutee') return 'Ajoutée au jeu de référence'
  if (ajoutReferenceStatut.value === 'deja_presente') return 'Déjà dans le jeu de référence'
  if (ajoutReferenceStatut.value === 'sans_faits') return 'Sans faits extraits — impossible'
  return 'Ajouter au jeu de référence'
})
async function ajouterAuJeuReference() {
  ajoutReferenceEnCours.value = true
  try {
    const res = await $fetch<{ statut: 'ajoutee' | 'deja_presente' | 'sans_faits' }>(
      `${config.public.apiBase}/offers/${id.value}/reference`,
      { method: 'POST' },
    )
    ajoutReferenceStatut.value = res.statut
  } finally {
    ajoutReferenceEnCours.value = false
  }
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

const PIECE_LABELS: Record<PieceStatut, string> = {
  a_faire: 'à faire',
  en_cours: 'en cours',
  prete: 'prête',
}
const PIECE_BADGE_CLASS: Record<PieceStatut, string> = {
  a_faire: 'bg-gray-100 text-gray-400',
  en_cours: 'bg-amber-50 text-amber-600',
  prete: 'bg-green-50 text-green-700',
}

function cardBadge(title: string): { label: string, class: string } {
  const av = cardAvancement(title)
  if (av && av.etat !== 'terminee') {
    if (av.etat === 'en_cours') return { label: 'Génération…', class: 'bg-amber-50 text-amber-600' }
    if (av.etat === 'en_erreur') return { label: 'Erreur', class: 'bg-red-50 text-red-600' }
    return { label: av.raison ?? 'à produire', class: 'bg-gray-100 text-gray-400' } // en_attente
  }
  if (av?.etat === 'terminee' && title === 'Mail de candidature') {
    return { label: 'Prêt', class: 'bg-green-50 text-green-700' }
  }
  if (title === 'Entreprise' && fiche.value) {
    if (fiche.value.statut === 'pending') return { label: 'en cours', class: 'bg-amber-50 text-amber-600' }
    if (fiche.value.statut === 'done') return { label: 'prête', class: 'bg-green-50 text-green-700' }
    return { label: 'erreur', class: 'bg-red-50 text-red-600' }
  }
  if (title === 'CV' && pieces.value) {
    return { label: PIECE_LABELS[pieces.value.cv.statut], class: PIECE_BADGE_CLASS[pieces.value.cv.statut] }
  }
  if (title === 'Lettre de motivation' && pieces.value) {
    return { label: PIECE_LABELS[pieces.value.lettre.statut], class: PIECE_BADGE_CLASS[pieces.value.lettre.statut] }
  }
  return { label: 'à produire', class: 'bg-gray-100 text-gray-400' }
}

function cardPreview(title: string): string {
  const av = cardAvancement(title)
  if (av && av.etat !== 'terminee') {
    if (av.etat === 'en_cours') return 'Génération…'
    return av.raison ?? 'Vide' // en_attente ou en_erreur sans raison
  }
  if (title === 'Entreprise' && fiche.value?.statut === 'done') {
    return `${fiche.value.employeur_nom ?? 'employeur non trouvé'} · ${fiche.value.points.length} points`
  }
  if (title === 'CV' && cv.value?.statut === 'done') {
    return `${cv.value.au_cv.length} compétences`
  }
  return 'Vide'
}

// ── Pieces (statut, marque Prête, PDF) — EXE-101/EXE-102 ──────────────────
const pieces = ref<Pieces | null>(null)
const cvPretError = ref<string | null>(null)
const lettrePretError = ref<string | null>(null)
const cvPdfError = ref<string | null>(null)
const lettrePdfError = ref<string | null>(null)

const PIECE_STEPS: { value: PieceStatut, label: string }[] = [
  { value: 'a_faire', label: 'À faire' },
  { value: 'en_cours', label: 'En cours' },
  { value: 'prete', label: 'Prête' },
]

async function errorDetail(e: unknown): Promise<string> {
  const data = (e as { data?: unknown })?.data
  if (data instanceof Blob) {
    try {
      const parsed = JSON.parse(await data.text()) as { detail?: string }
      return parsed.detail ?? 'Action impossible.'
    } catch {
      return 'Action impossible.'
    }
  }
  const detail = (data as { detail?: string } | undefined)?.detail
  return detail ?? 'Action impossible.'
}

async function chargerPieces() {
  try {
    pieces.value = await $fetch<Pieces>(`${config.public.apiBase}/offers/${id.value}/pieces`)
  } catch {
    pieces.value = null // offre non retenue : pas de statut de pièce à afficher
  }
}

// ── Avancement des pièces (EXE-127/EXE-128) — ce que l'API rend, jamais recalculé ──
const avancement = ref<Avancement | null>(null)
let avancementPollTimer: ReturnType<typeof setInterval> | null = null

const AVANCEMENT_KEY: Record<string, keyof Avancement> = {
  'Entreprise': 'fiche',
  'CV': 'cv',
  'Lettre de motivation': 'lettre',
  'Mail de candidature': 'mail',
}

function cardAvancement(title: string): AvancementPiece | null {
  const key = AVANCEMENT_KEY[title]
  return key ? avancement.value?.[key] ?? null : null
}

function avancementActif(a: Avancement | null): boolean {
  if (!a) return false
  return [a.fiche, a.cv, a.lettre].some(p => p.etat === 'en_attente' || p.etat === 'en_cours')
}

async function chargerAvancement() {
  if (!isRetenue.value) { avancement.value = null; return }
  try {
    const next = await $fetch<Avancement>(`${config.public.apiBase}/offers/${id.value}/avancement`)
    avancement.value = next
    // La lettre vient de démarrer (fiche terminée côté API) : on rejoint son propre
    // suivi, sans quoi son overlay resterait sur l'ancien statut jusqu'au rechargement.
    if (next.lettre.etat === 'en_cours' && lettre.value?.statut !== 'pending') {
      await chargerLettre()
      if (lettre.value?.statut === 'pending') startLettrePolling()
    }
  } catch {
    avancement.value = null
  }
}

function stopAvancementPolling() {
  if (avancementPollTimer) { clearInterval(avancementPollTimer); avancementPollTimer = null }
}

function startAvancementPolling() {
  stopAvancementPolling()
  let ticks = 0
  avancementPollTimer = setInterval(async () => {
    await chargerAvancement()
    ticks++
    if (!avancementActif(avancement.value) || ticks >= POLL_MAX) stopAvancementPolling()
  }, 5000)
}

const lettreRaisonAttente = computed(() => {
  const av = avancement.value?.lettre
  return av && av.etat === 'en_attente' ? av.raison : null
})

// ── Tout télécharger — CV + lettre en PDF, si les deux sont Prêtes (EXE-134) ──
const telechargerToutBusy = ref(false)
const telechargerToutLabel = computed(() => {
  const cvPret = pieces.value?.cv.statut === 'prete'
  const lettrePret = pieces.value?.lettre.statut === 'prete'
  if (cvPret && lettrePret) return null
  if (!cvPret && !lettrePret) return 'Le CV et la lettre ne sont pas encore prêts.'
  if (!cvPret) return 'Le CV n\'est pas encore prêt.'
  return 'La lettre n\'est pas encore prête.'
})

async function telechargerTout() {
  telechargerToutBusy.value = true
  try {
    await telechargerCvPdf()
    await telechargerLettrePdf()
  } finally {
    telechargerToutBusy.value = false
  }
}

async function toggleCvPret() {
  if (!pieces.value) return
  const pret = pieces.value.cv.statut !== 'prete'
  cvPretError.value = null
  try {
    await $fetch<PieceInfo>(`${cvUrl()}/pret`, { method: 'PUT', body: { pret } })
    await chargerPieces() // relit prete_a_l_envoi et envoyee_le, pas seulement la pièce modifiée
  } catch (e) {
    cvPretError.value = await errorDetail(e)
  }
}

async function toggleLettrePret() {
  if (!pieces.value) return
  const pret = pieces.value.lettre.statut !== 'prete'
  lettrePretError.value = null
  try {
    await $fetch<PieceInfo>(`${lettreUrl()}/pret`, { method: 'PUT', body: { pret } })
    await chargerPieces() // relit prete_a_l_envoi et envoyee_le, pas seulement la pièce modifiée
  } catch (e) {
    lettrePretError.value = await errorDetail(e)
  }
}

function declencherTelechargement(blob: Blob, contentDisposition: string | null): string | null {
  const match = contentDisposition?.match(/filename="?([^"]+)"?/)
  if (!match) return 'Le nom du fichier est manquant : téléchargement annulé.'
  const filename = match[1]!
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = filename
  a.click()
  URL.revokeObjectURL(url)
  return null
}

async function telechargerCvPdf() {
  cvPdfError.value = null
  try {
    const res = await $fetch.raw(cvUrl() + '/pdf', { responseType: 'blob' })
    cvPdfError.value = declencherTelechargement(res._data as Blob, res.headers.get('content-disposition'))
  } catch (e) {
    cvPdfError.value = await errorDetail(e)
  }
}

async function telechargerLettrePdf() {
  lettrePdfError.value = null
  try {
    const res = await $fetch.raw(lettreUrl() + '/pdf', { responseType: 'blob' })
    lettrePdfError.value = declencherTelechargement(res._data as Blob, res.headers.get('content-disposition'))
  } catch (e) {
    lettrePdfError.value = await errorDetail(e)
  }
}

function stepActive(step: string): boolean {
  if (step === 'Retenue') return true
  if (step === 'Prête à l\'envoi') return !!pieces.value?.prete_a_l_envoi
  if (step === 'Candidature envoyée') return !!pieces.value?.envoyee_le
  return false
}

// ── Candidature envoyée (EXE-139) — marque humaine, distincte du statut
// retenu/rejeté/candidaté et des statuts de pièce ────────────────────────
const envoyeeBusy = ref(false)
const envoyeeError = ref<string | null>(null)
const envoyeeRaison = computed(() => {
  const cvPret = pieces.value?.cv.statut === 'prete'
  const lettrePret = pieces.value?.lettre.statut === 'prete'
  if (cvPret && lettrePret) return null
  if (!cvPret && !lettrePret) return 'Le CV et la lettre ne sont pas encore prêts.'
  if (!cvPret) return 'Le CV n\'est pas encore prêt.'
  return 'La lettre n\'est pas encore prête.'
})

async function marquerEnvoyee() {
  if (!pieces.value) return
  envoyeeError.value = null
  envoyeeBusy.value = true
  try {
    const res = await $fetch<{ envoyee_le: string | null }>(`${config.public.apiBase}/offers/${id.value}/envoyee`, { method: 'PUT', body: { envoyee: true } })
    pieces.value = { ...pieces.value, envoyee_le: res.envoyee_le }
  } catch (e) {
    envoyeeError.value = await errorDetail(e)
  } finally {
    envoyeeBusy.value = false
  }
}

async function annulerEnvoyee() {
  if (!pieces.value) return
  envoyeeError.value = null
  envoyeeBusy.value = true
  try {
    const res = await $fetch<{ envoyee_le: string | null }>(`${config.public.apiBase}/offers/${id.value}/envoyee`, { method: 'PUT', body: { envoyee: false } })
    pieces.value = { ...pieces.value, envoyee_le: res.envoyee_le }
  } catch (e) {
    envoyeeError.value = await errorDetail(e)
  } finally {
    envoyeeBusy.value = false
  }
}

// ── Mail de candidature — EXE-103 ───────────────────────────────────────────
const mail = ref<MailCandidature | null>(null)
const mailError = ref<string | null>(null)
const mailObjetCopied = ref(false)
const mailCorpsCopied = ref(false)
let mailObjetTimer: ReturnType<typeof setTimeout> | null = null
let mailCorpsTimer: ReturnType<typeof setTimeout> | null = null

async function chargerMail() {
  mail.value = null
  mailError.value = null
  try {
    mail.value = await $fetch<MailCandidature>(`${config.public.apiBase}/offers/${id.value}/mail`)
  } catch (e) {
    mailError.value = await errorDetail(e)
  }
}

async function copierMailObjet() {
  if (!mail.value) return
  await navigator.clipboard.writeText(mail.value.objet)
  mailObjetCopied.value = true
  if (mailObjetTimer) clearTimeout(mailObjetTimer)
  mailObjetTimer = setTimeout(() => { mailObjetCopied.value = false }, 1500)
}

async function copierMailCorps() {
  if (!mail.value) return
  await navigator.clipboard.writeText(mail.value.corps)
  mailCorpsCopied.value = true
  if (mailCorpsTimer) clearTimeout(mailCorpsTimer)
  mailCorpsTimer = setTimeout(() => { mailCorpsCopied.value = false }, 1500)
}

// ── Date lisible, fuseau local (EXE-143) ────────────────────────────────────
function formatDateFr(iso: string): string {
  return new Intl.DateTimeFormat('fr-FR', { day: 'numeric', month: 'long', year: 'numeric' }).format(new Date(iso))
}

// ── Date lisible pour l'historique de la lettre ─────────────────────────────
function formatDateHeure(iso: string): string {
  const d = new Date(iso)
  const date = new Intl.DateTimeFormat('fr-FR', { weekday: 'long', day: 'numeric', month: 'short', year: 'numeric' }).format(d)
  const heure = new Intl.DateTimeFormat('fr-FR', { hour: '2-digit', minute: '2-digit' }).format(d)
  return date.charAt(0).toUpperCase() + date.slice(1) + ', ' + heure
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
    cvTitreEdit.value = cv.value.titre ?? ''
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
    if (cv.value?.statut !== 'pending') {
      stopCvPolling() // done ou error : on s'arrête
      await chargerPieces()
    } else if (ticks >= POLL_MAX) {
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
      cvTitreEdit.value = res.titre ?? ''
      await chargerPieces()
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

// ── Titre du CV, et titre par défaut des prochains CV (EXE-130) ────────────
const cvTitreEdit = ref('')
const cvTitreParDefaut = ref(false)
const cvTitreError = ref<string | null>(null)
const cvTitreDefaut = ref<string | null>(null)
const cvTitreDefautError = ref<string | null>(null)

async function chargerCvTitreDefaut() {
  try {
    const res = await $fetch<{ titre_defaut: string | null }>(`${config.public.apiBase}/cv/titre-defaut`)
    cvTitreDefaut.value = res.titre_defaut
  } catch {
    cvTitreDefaut.value = null
  }
}

async function enregistrerCvTitre() {
  cvTitreError.value = null
  try {
    cv.value = await $fetch<Cv>(`${cvUrl()}/titre`, {
      method: 'PUT',
      body: { titre: cvTitreEdit.value, par_defaut: cvTitreParDefaut.value },
    })
    cvTitreEdit.value = cv.value.titre ?? ''
    await chargerPieces()
    if (cvTitreParDefaut.value) await chargerCvTitreDefaut()
  } catch (e) {
    cvTitreError.value = messageErreurCv(e)
  }
}

async function effacerCvTitreDefaut() {
  cvTitreDefautError.value = null
  try {
    await $fetch(`${config.public.apiBase}/cv/titre-defaut`, { method: 'DELETE' })
    cvTitreDefaut.value = null
  } catch (e) {
    cvTitreDefautError.value = messageErreurCv(e)
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
const texteEditRef = ref<HTMLTextAreaElement | null>(null)

function autoGrowTexte() {
  const el = texteEditRef.value
  if (!el) return
  el.style.height = 'auto'
  el.style.height = `${el.scrollHeight}px`
}

watch(texteEdit, () => nextTick(autoGrowTexte))
const lettreActionError = ref<string | null>(null)
const lettreBusy = ref(false)
const lettreCopied = ref(false)
let lettreCopiedTimer: ReturnType<typeof setTimeout> | null = null
let lettrePollTimer: ReturnType<typeof setInterval> | null = null

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
      await chargerPieces()
      await syncLettreMiseEnPage()
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
      await chargerPieces()
      await syncLettreMiseEnPage()
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
    await chargerPieces()
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
    await chargerPieces()
    await syncLettreMiseEnPage()
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
// Miniature CV/lettre sur la carte — page A4 réelle réduite à la largeur de
// la carte, mesurée sur la carte CV (identique à celle de la lettre, les deux
// se partagent la ligne à parts égales) (EXE-134, EXE-135).
const cvCardEl = ref<HTMLElement | null>(null)
const miniatureLargeur = ref(220)
const miniatureHauteur = computed(() => Math.round(miniatureLargeur.value * 1123 / 794))
const miniatureEchelle = computed(() => miniatureLargeur.value / 794)
let miniatureResizeObserver: ResizeObserver | null = null

// La carte n'existe qu'une fois l'offre chargée (v-if="offer") : on observe
// dès que la ref s'attache, pas seulement au montage du composant.
watch(cvCardEl, (el) => {
  miniatureResizeObserver?.disconnect()
  miniatureResizeObserver = null
  if (!el) return
  miniatureResizeObserver = new ResizeObserver((entries) => {
    const largeur = entries[0]?.contentRect.width
    if (largeur) miniatureLargeur.value = largeur
  })
  miniatureResizeObserver.observe(el)
})
onBeforeUnmount(() => miniatureResizeObserver?.disconnect())

function miniatureVisible(title: string): boolean {
  const av = cardAvancement(title)
  if (av && av.etat !== 'terminee') return false
  if (title === 'CV') return cv.value?.statut === 'done' && !!cv.value.html
  if (title === 'Lettre de motivation') return lettre.value?.statut === 'done' && !!lettreMiseEnPageHtml.value
  return false
}

const activeCard = ref<string | null>(null)
function openCard(title: string) {
  if (title === 'CV' && cv.value?.statut === 'done') { ouvrirApercu(title); return }
  if (title === 'Lettre de motivation' && lettre.value?.statut === 'done') { ouvrirApercu(title); return }
  activeCard.value = title
  if (title === 'Mail de candidature') chargerMail()
}

// ── Aperçu plein écran du CV et de la lettre (EXE-129) ──────────────────────
const apercuCard = ref<string | null>(null)
const lettreMiseEnPageHtml = ref<string | null>(null)
const lettreMiseEnPageError = ref<string | null>(null)
const cvFrame = ref<HTMLIFrameElement | null>(null)
const lettreFrame = ref<HTMLIFrameElement | null>(null)

function ouvrirApercu(title: string) {
  apercuCard.value = title
  if (title === 'Lettre de motivation') {
    lettreMiseEnPageHtml.value = null
    chargerLettreMiseEnPage()
  }
}

function fermerApercu() {
  apercuCard.value = null
}

function modifierDepuisApercu() {
  const title = apercuCard.value
  apercuCard.value = null
  if (title) activeCard.value = title
}

async function chargerLettreMiseEnPage() {
  lettreMiseEnPageError.value = null
  try {
    lettreMiseEnPageHtml.value = await $fetch<string>(`${lettreUrl()}/mise-en-page`, { responseType: 'text' })
  } catch (e) {
    lettreMiseEnPageHtml.value = null
    lettreMiseEnPageError.value = await errorDetail(e)
  }
}

// Tient la miniature de la carte à jour avec la mise en page rendue par l'API,
// sans attendre l'ouverture de l'aperçu plein écran (EXE-134).
async function syncLettreMiseEnPage() {
  if (lettre.value?.statut === 'done') await chargerLettreMiseEnPage()
  else lettreMiseEnPageHtml.value = null
}

function resizeFrame(frame: HTMLIFrameElement | null) {
  const doc = frame?.contentDocument
  if (doc) frame!.style.height = `${doc.documentElement.scrollHeight}px`
}

function onApercuKeydown(e: KeyboardEvent) {
  if (e.key === 'Escape' && apercuCard.value) fermerApercu()
}
onMounted(() => window.addEventListener('keydown', onApercuKeydown))
onBeforeUnmount(() => window.removeEventListener('keydown', onApercuKeydown))

watch(activeCard, (title) => { if (title === 'Lettre de motivation') nextTick(autoGrowTexte) })

const lettreVersionsRecentesDabord = computed(() => [...lettreVersions.value].reverse())

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
