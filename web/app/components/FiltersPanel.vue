<template>
  <div class="bg-white border border-gray-200 rounded-lg shadow-sm px-4 py-3 flex flex-wrap gap-4 items-end text-sm">

    <!-- Recherche texte -->
    <div class="flex flex-col gap-1 min-w-40">
      <label class="text-xs font-medium text-gray-500 uppercase tracking-wide">Recherche</label>
      <input
        v-model="local.q"
        type="text"
        placeholder="Titre, entreprise…"
        class="border border-gray-200 rounded px-2 py-1 text-sm focus:outline-none focus:ring-2 focus:ring-indigo-300"
        @keydown.enter="apply"
      />
    </div>

    <!-- Désirabilité min/max -->
    <div class="flex flex-col gap-1">
      <label class="text-xs font-medium text-gray-500 uppercase tracking-wide">Désirabilité</label>
      <div class="flex items-center gap-1">
        <input
          v-model.number="local.desirability_min"
          type="number" min="0" max="100"
          placeholder="min"
          class="w-16 border border-gray-200 rounded px-2 py-1 text-sm focus:outline-none focus:ring-2 focus:ring-indigo-300"
        />
        <span class="text-gray-400">–</span>
        <input
          v-model.number="local.desirability_max"
          type="number" min="0" max="100"
          placeholder="max"
          class="w-16 border border-gray-200 rounded px-2 py-1 text-sm focus:outline-none focus:ring-2 focus:ring-indigo-300"
        />
      </div>
    </div>

    <!-- Remote -->
    <div class="flex flex-col gap-1">
      <label class="text-xs font-medium text-gray-500 uppercase tracking-wide">Remote</label>
      <select
        v-model="local.remote"
        class="border border-gray-200 rounded px-2 py-1 text-sm focus:outline-none focus:ring-2 focus:ring-indigo-300"
      >
        <option :value="undefined">Tous</option>
        <option :value="true">Remote uniquement</option>
        <option :value="false">Sur site</option>
      </select>
    </div>

    <!-- Verdict -->
    <div class="flex flex-col gap-1">
      <label class="text-xs font-medium text-gray-500 uppercase tracking-wide">Verdict</label>
      <select
        v-model="local.verdict"
        class="border border-gray-200 rounded px-2 py-1 text-sm focus:outline-none focus:ring-2 focus:ring-indigo-300"
      >
        <option value="">Tous</option>
        <option value="favori">Favori</option>
        <option value="candidaté">Candidaté</option>
        <option value="rejeté">Rejeté</option>
        <option value="masqué">Masqué</option>
      </select>
    </div>

    <!-- Actions -->
    <div class="flex gap-2 ml-auto">
      <button
        @click="reset"
        class="px-3 py-1 rounded border border-gray-200 text-gray-500 hover:bg-gray-50 text-sm transition-colors"
      >
        Réinitialiser
      </button>
      <button
        @click="apply"
        class="px-3 py-1 rounded bg-indigo-600 text-white hover:bg-indigo-700 text-sm font-medium transition-colors"
      >
        Appliquer
      </button>
    </div>
  </div>
</template>

<script setup lang="ts">
import { useOffersStore } from '~/stores/offers'

const store = useOffersStore()

interface LocalFilters {
  q: string
  desirability_min: number | undefined
  desirability_max: number | undefined
  remote: boolean | undefined
  verdict: string
}

const local = reactive<LocalFilters>({
  q: '',
  desirability_min: undefined,
  desirability_max: undefined,
  remote: undefined,
  verdict: '',
})

function apply() {
  store.filters.q          = local.q || undefined
  store.filters.desirability_min  = local.desirability_min
  store.filters.desirability_max  = local.desirability_max
  store.filters.remote     = local.remote
  store.filters.verdict    = local.verdict || undefined
  store.fetchOffers()
}

function reset() {
  local.q         = ''
  local.desirability_min = undefined
  local.desirability_max = undefined
  local.remote    = undefined
  local.verdict   = ''
  store.filters.q        = undefined
  store.filters.desirability_min = undefined
  store.filters.desirability_max = undefined
  store.filters.remote    = undefined
  store.filters.verdict   = undefined
  store.fetchOffers()
}
</script>
