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

    <!-- Catégorie -->
    <div class="flex flex-col gap-1">
      <label class="text-xs font-medium text-gray-500 uppercase tracking-wide">Catégorie</label>
      <select
        v-model="local.category"
        class="border border-gray-200 rounded px-2 py-1 text-sm focus:outline-none focus:ring-2 focus:ring-indigo-300"
      >
        <option value="">Toutes</option>
        <option value="parfait">★ Parfait</option>
        <option value="reve">◈ Rêve</option>
        <option value="atteignable">✓ Atteignable</option>
        <option value="hors">✗ Hors</option>
      </select>
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
        <option value="retenu">Retenu</option>
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
  category: string
  remote: boolean | undefined
  verdict: string
}

const local = reactive<LocalFilters>({
  q: '',
  category: '',
  remote: undefined,
  verdict: '',
})

function apply() {
  store.filters.q        = local.q || undefined
  store.filters.category = local.category || undefined
  store.filters.remote   = local.remote
  store.filters.verdict  = local.verdict || undefined
  store.fetchOffers()
}

function reset() {
  local.q        = ''
  local.category = ''
  local.remote   = undefined
  local.verdict  = ''
  store.filters.q        = undefined
  store.filters.category = undefined
  store.filters.remote   = undefined
  store.filters.verdict  = undefined
  store.fetchOffers()
}
</script>
