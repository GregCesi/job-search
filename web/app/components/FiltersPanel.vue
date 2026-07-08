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
        @change="apply"
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
        @change="apply"
      >
        <option :value="undefined">Tous</option>
        <option :value="true">Remote uniquement</option>
        <option :value="false">Sur site</option>
      </select>
    </div>

    <!-- Source -->
    <div class="flex flex-col gap-1">
      <label class="text-xs font-medium text-gray-500 uppercase tracking-wide">Source</label>
      <select
        v-model="local.source"
        class="border border-gray-200 rounded px-2 py-1 text-sm focus:outline-none focus:ring-2 focus:ring-indigo-300"
        @change="apply"
      >
        <option value="">Toutes</option>
        <option value="France-Travail">France Travail</option>
        <option value="Remotive">Remotive</option>
        <option value="Indeed">Indeed</option>
      </select>
    </div>

    <!-- État review (multi-select) -->
    <div class="flex flex-col gap-1">
      <label class="text-xs font-medium text-gray-500 uppercase tracking-wide">Review</label>
      <div class="flex gap-3 items-center h-[30px]">
        <label class="flex items-center gap-1 text-sm cursor-pointer">
          <input type="checkbox" value="non_relue" v-model="local.etat_review" @change="apply" class="accent-indigo-500" />
          Non relue
        </label>
        <label class="flex items-center gap-1 text-sm cursor-pointer">
          <input type="checkbox" value="validee" v-model="local.etat_review" @change="apply" class="accent-green-500" />
          Validée
        </label>
        <label class="flex items-center gap-1 text-sm cursor-pointer">
          <input type="checkbox" value="corrigee" v-model="local.etat_review" @change="apply" class="accent-amber-500" />
          Corrigée
        </label>
      </div>
    </div>

    <!-- Hors-périmètre -->
    <div class="flex flex-col gap-1">
      <label class="text-xs font-medium text-gray-500 uppercase tracking-wide">Hors-périmètre</label>
      <select
        v-model="local.hors_perimetre"
        class="border border-gray-200 rounded px-2 py-1 text-sm focus:outline-none focus:ring-2 focus:ring-indigo-300"
        @change="apply"
      >
        <option :value="undefined">Tous</option>
        <option :value="true">Uniquement HP</option>
        <option :value="false">Exclure HP</option>
      </select>
    </div>

    <!-- Verdict -->
    <div class="flex flex-col gap-1">
      <label class="text-xs font-medium text-gray-500 uppercase tracking-wide">Verdict</label>
      <select
        v-model="local.verdict"
        class="border border-gray-200 rounded px-2 py-1 text-sm focus:outline-none focus:ring-2 focus:ring-indigo-300"
        @change="apply"
      >
        <option value="">Tous</option>
        <option value="retenu">Retenu</option>
        <option value="candidaté">Candidaté</option>
        <option value="rejeté">Rejeté</option>
        <option value="masqué">Masqué</option>
        <option value="hors_perimetre_ok">Confirmé HP</option>
        <option value="hors_perimetre_faux_pos">Faux positif</option>
      </select>
    </div>

    <!-- Reset -->
    <div class="flex gap-2 ml-auto">
      <button
        @click="reset"
        class="px-3 py-1 rounded border border-gray-200 text-gray-500 hover:bg-gray-50 text-sm transition-colors"
      >
        Réinitialiser
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
  source: string
  etat_review: string[]
  hors_perimetre: boolean | undefined
  verdict: string
}

const local = reactive<LocalFilters>({
  q: '',
  category: '',
  remote: undefined,
  source: '',
  etat_review: [],
  hors_perimetre: undefined,
  verdict: '',
})

function apply() {
  store.filters.q              = local.q || undefined
  store.filters.category       = local.category || undefined
  store.filters.remote         = local.remote
  store.filters.source         = local.source || undefined
  store.filters.etat_review    = local.etat_review.length ? local.etat_review.join(',') : undefined
  store.filters.hors_perimetre = local.hors_perimetre
  store.filters.verdict        = local.verdict || undefined
  store.fetchOffers()
}

function reset() {
  local.q              = ''
  local.category       = ''
  local.remote         = undefined
  local.source         = ''
  local.etat_review    = []
  local.hors_perimetre = undefined
  local.verdict        = ''
  store.filters.q              = undefined
  store.filters.category       = undefined
  store.filters.remote         = undefined
  store.filters.source         = undefined
  store.filters.etat_review    = undefined
  store.filters.hors_perimetre = undefined
  store.filters.verdict        = undefined
  store.fetchOffers()
}
</script>
