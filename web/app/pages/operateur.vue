<template>
  <div class="min-h-screen bg-gray-50 flex flex-col">

    <!-- Top bar -->
    <header class="bg-white border-b border-gray-200 px-6 py-3 flex items-center gap-6 sticky top-0 z-10 shadow-sm">
      <span class="text-sm font-semibold text-gray-800 tracking-tight shrink-0">job-search · opérateur</span>

      <!-- View tabs -->
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

      <!-- Offer count + links -->
      <div class="ml-auto flex items-center gap-3">
        <span class="text-xs text-gray-400">
          {{ store.offers.length }} offre{{ store.offers.length !== 1 ? 's' : '' }}
        </span>
        <NuxtLink
          to="/traces"
          class="text-xs text-indigo-600 hover:underline font-medium"
        >
          Traces LLM
        </NuxtLink>
        <ExportPopover />
        <a
          :href="`${config.public.apiBase}/export/calibration`"
          target="_blank"
          class="text-xs text-indigo-600 hover:underline font-medium"
        >
          Calibration ↗
        </a>
      </div>
    </header>

    <!-- Filters — visible in "tout" and "hors_perimetre" views -->
    <div v-if="store.activeView === 'tout' || store.activeView === 'hors_perimetre'" class="px-6 pt-4">
      <FiltersPanel />
    </div>

    <!-- Table -->
    <main class="flex-1 px-6 py-4">
      <OffersTable :selected-id="store.openedOffer?.id" mode="operateur" @select="handleSelect" />
    </main>

    <!-- Detail panel -->
    <OfferDetail
      v-if="store.openedOffer"
      :offer="store.openedOffer"
      mode="operateur"
      @close="store.openedOffer = null"
    />
  </div>
</template>

<script setup lang="ts">
import { useOffersStore } from '~/stores/offers'
import type { OfferRow, ActiveView } from '~/stores/offers'

const config = useRuntimeConfig()
const store = useOffersStore()
onMounted(() => {
  store.fetchOffers()
  store.fetchTraceCounts()
})

const VIEWS: { key: ActiveView; label: string }[] = [
  { key: 'a_traiter',      label: 'À traiter'       },
  { key: 'hors_perimetre', label: 'Hors-périmètre'  },
  { key: 'tout',           label: 'Tout'            },
]

async function handleSelect(offer: OfferRow) {
  await store.openDetail(offer.id)
}
</script>
