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

      <!-- Offer count -->
      <span class="ml-auto text-xs text-gray-400">
        {{ store.offers.length }} offre{{ store.offers.length !== 1 ? 's' : '' }}
      </span>
    </header>

    <!-- Filters (L8) — visible only in "tout" view -->
    <div v-if="store.activeView === 'tout'" class="px-6 pt-4">
      <FiltersPanel />
    </div>

    <!-- Table (L6) -->
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
import type { OfferRow, ActiveView } from '~/stores/offers'

const store = useOffersStore()
onMounted(() => store.fetchOffers())

const VIEWS: { key: ActiveView; label: string }[] = [
  { key: 'a_traiter',    label: 'À traiter'    },
  { key: 'atteignables', label: 'Atteignables' },
  { key: 'favoris',      label: 'Favoris'      },
  { key: 'tout',         label: 'Tout'         },
]

async function handleSelect(offer: OfferRow) {
  await store.openDetail(offer.id)
}
</script>
