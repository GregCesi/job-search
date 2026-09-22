<template>
  <div class="min-h-screen bg-gray-50 flex flex-col">

    <!-- Top bar -->
    <header class="bg-white border-b border-gray-200 px-6 py-3 flex items-center gap-6 sticky top-0 z-10 shadow-sm">
      <span class="text-sm font-semibold text-gray-800 tracking-tight shrink-0">job-search</span>

      <!-- View tabs (L7) -->
      <nav class="flex gap-1">
        <button
          v-for="view in VIEWS" :key="view.key"
          :class="[
            'px-3 py-1.5 rounded-md text-sm font-medium transition-colors',
            store.activeView === view.key
              ? 'bg-indigo-600 text-white'
              : 'text-gray-600 hover:bg-gray-100',
          ]"
          @click="store.setView(view.key)"
        >
          {{ view.label }}
        </button>
      </nav>

      <!-- Offer count + export calibration (L11) -->
      <div class="ml-auto flex items-center gap-3">
        <span class="text-xs text-gray-400">
          {{ store.offers.length }} offre{{ store.offers.length !== 1 ? 's' : '' }}
        </span>
        <label class="flex items-center gap-1.5 text-xs text-gray-600 cursor-pointer select-none">
          <input
            type="checkbox"
            :checked="store.viewProfileActive"
            @change="store.viewProfileActive = ($event.target as HTMLInputElement).checked; store.fetchOffers()"
            class="accent-indigo-600"
          />
          Profil de vue
        </label>
        <label class="flex items-center gap-1.5 text-xs text-gray-600 cursor-pointer select-none">
          <input
            type="checkbox"
            :checked="store.includeRemote"
            @change="store.includeRemote = ($event.target as HTMLInputElement).checked; store.fetchOffers()"
            class="accent-indigo-600"
          />
          Inclure le remote
        </label>
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
      <OffersTable :selected-id="store.openedOffer?.id" @select="handleSelect" />
    </main>

    <!-- Detail panel (L6 — content expanded in L9) -->
    <OfferDetail
      v-if="store.openedOffer"
      :offer="store.openedOffer"
      @close="store.openedOffer = null"
    />
  </div>
</template>

<script setup lang="ts">
import { useOffersStore } from '~/stores/offers'
import type { OfferRow, CandidateView } from '~/stores/offers'

const config = useRuntimeConfig()
const store = useOffersStore()
onMounted(() => {
  store.viewProfileActive = true
  store.includeRemote = false
  store.setView('cibles')
  store.fetchTraceCounts()
})

const VIEWS: { key: CandidateView; label: string }[] = [
  { key: 'cibles',   label: 'Cibles'   },
  { key: 'gaps',     label: 'Gaps'     },
  { key: 'filet',    label: 'Filet'    },
  { key: 'retenues', label: 'Retenues' },
]

const router = useRouter()

async function handleSelect(offer: OfferRow) {
  if (store.activeView === 'retenues') {
    router.push(`/offers/${offer.id}`)
  } else {
    await store.openDetail(offer.id)
  }
}
</script>
