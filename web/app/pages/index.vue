<template>
  <div class="min-h-screen bg-gray-50 flex">

    <!-- Menu candidat (EXE-80) -->
    <CandidateMenu />

    <div class="flex-1 min-w-0 flex flex-col">

      <!-- Top bar -->
      <header class="bg-white border-b border-gray-200 px-6 py-3 flex items-center gap-6 sticky top-0 z-10 shadow-sm">
        <span class="text-sm font-semibold text-gray-800 tracking-tight shrink-0">job-search</span>

        <!-- Vérification d'expiration (EXE-76/77/78) — les onglets candidat.
             À postuler et Suivi vérifient tout (EXE-224) ; Écartées désigne
             les offres affichées. -->
        <button
          v-if="CANDIDATE_VIEWS.includes(store.activeView as CandidateView)"
          :disabled="store.checkingExpirations"
          class="px-3 py-1.5 rounded-md text-sm font-medium bg-red-50 text-red-700 hover:bg-red-100 disabled:opacity-50 transition-colors"
          @click="handleCheckExpirations"
        >
          {{ store.checkingExpirations ? 'Vérification en cours…' : 'Vérifier les offres' }}
        </button>

        <!-- Offer count + export calibration (L11) -->
        <div class="ml-auto flex items-center gap-3">
          <span class="text-xs text-gray-400">
            {{ nbAffichees }} offre{{ nbAffichees !== 1 ? 's' : '' }}
          </span>
          <NuxtLink
            to="/traces"
            class="text-xs text-indigo-600 hover:underline font-medium"
          >
            Traces LLM
          </NuxtLink>
          <ExportPopover />
          <NuxtLink
            to="/operateur"
            class="text-xs text-gray-400 hover:text-gray-600 font-medium"
          >
            Opérateur
          </NuxtLink>
        </div>
      </header>

      <!-- Table -->
      <main class="flex-1 px-6 py-4">
        <!-- À postuler (EXE-211) : sa liste, ses files, ses filtres et ses tris. -->
        <APostulerTable v-if="store.activeView === 'a_postuler'" />
        <OffersTable v-else :selected-id="store.openedOffer?.id" @select="handleSelect" />
      </main>

      <!-- Detail panel (L6 — content expanded in L9) -->
      <OfferDetail
        v-if="store.openedOffer"
        :offer="store.openedOffer"
        @close="store.openedOffer = null"
      />
    </div>
  </div>
</template>

<script setup lang="ts">
import { useOffersStore } from '~/stores/offers'
import type { OfferRow, CandidateView } from '~/stores/offers'
import { useAPostulerStore } from '~/stores/aPostuler'

const config = useRuntimeConfig()
const store = useOffersStore()
const aPostuler = useAPostulerStore()
const route = useRoute()
const CANDIDATE_VIEWS: CandidateView[] = ['a_postuler', 'suivi', 'ecartees']
const nbAffichees = computed(() =>
  store.activeView === 'a_postuler' ? aPostuler.lignes.length : store.offers.length,
)
onMounted(() => {
  // ?vue= est posé par le menu depuis une autre page ; sans lui, ou avec une
  // vue inconnue (anciens liens cibles, gaps, filet), À postuler (EXE-211).
  const vue = route.query.vue as CandidateView
  store.setView(CANDIDATE_VIEWS.includes(vue) ? vue : 'a_postuler')
  store.fetchTraceCounts()
  // ?offre= est posé par une notification d'ajout depuis une autre page (EXE-81).
  const offre = Number(route.query.offre)
  if (Number.isInteger(offre) && offre > 0) {
    store.openDetail(offre)
    router.replace({ path: '/', query: { ...route.query, offre: undefined } })
  }
})

const router = useRouter()

async function handleSelect(offer: OfferRow) {
  if (store.activeView === 'suivi') {
    router.push(`/offers/${offer.id}`)
  } else {
    await store.openDetail(offer.id)
  }
}

// À postuler et Suivi vérifient tout (EXE-224) ; les autres vues, les offres affichées.
function handleCheckExpirations() {
  if (store.activeView === 'suivi' || store.activeView === 'a_postuler') {
    store.checkExpirations('tout')
  } else {
    store.checkExpirations(store.offers.map(o => o.id))
  }
}
</script>
