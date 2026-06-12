<template>
  <div class="overflow-x-auto rounded-lg border border-gray-200 bg-white shadow-sm">
    <!-- Empty state -->
    <div v-if="store.offers.length === 0 && !store.loading"
         class="py-16 text-center text-sm text-gray-400">
      Aucune offre dans cette vue.
    </div>

    <table v-else class="min-w-full divide-y divide-gray-100 text-sm">
      <thead class="bg-gray-50 text-xs font-medium text-gray-500 uppercase tracking-wide">
        <tr>
          <th class="w-6 px-3 py-3"></th>
          <th
            v-for="col in COLS" :key="col.key"
            :class="['px-3 py-3 text-left select-none', col.sortable ? 'cursor-pointer hover:text-gray-700' : '']"
            @click="col.sortable && toggleSort(col.key)"
          >
            {{ col.label }}
            <span v-if="col.sortable && store.filters.sort === col.key" class="ml-1 text-gray-400">
              {{ store.filters.order === 'asc' ? '↑' : '↓' }}
            </span>
          </th>
        </tr>
      </thead>
      <tbody class="divide-y divide-gray-50">
        <tr
          v-for="offer in store.offers" :key="offer.id"
          :class="[
            'cursor-pointer transition-colors',
            offer.seen
              ? 'text-gray-400 hover:bg-gray-50'
              : 'text-gray-800 hover:bg-indigo-50',
            selectedId === offer.id ? 'bg-indigo-50 ring-1 ring-inset ring-indigo-200' : '',
          ]"
          @click="$emit('select', offer)"
        >
          <!-- Seen dot -->
          <td class="px-3 py-3">
            <span v-if="!offer.seen" class="block w-2 h-2 rounded-full bg-indigo-400" title="Non vu" />
          </td>

          <!-- Title -->
          <td class="px-3 py-3 max-w-xs">
            <span class="block truncate font-medium" :title="offer.title ?? ''">
              {{ offer.title ?? '—' }}
            </span>
          </td>

          <!-- Company -->
          <td class="px-3 py-3 whitespace-nowrap">{{ offer.company ?? '—' }}</td>

          <!-- Contract -->
          <td class="px-3 py-3 whitespace-nowrap text-gray-500">{{ offer.contract_type ?? '—' }}</td>

          <!-- Location -->
          <td class="px-3 py-3 whitespace-nowrap">
            <span v-if="offer.remote" class="inline-flex items-center px-2 py-0.5 rounded-full bg-teal-50 text-teal-700 text-xs font-medium">
              Remote
            </span>
            <span v-else class="text-gray-500">{{ offer.location ?? '—' }}</span>
          </td>

          <!-- Désirabilité + Catégorie / Hors-périmètre -->
          <td class="px-3 py-3 whitespace-nowrap">
            <div v-if="offer.hors_perimetre_reason" class="flex items-center gap-1.5">
              <span :class="reasonClass(offer.hors_perimetre_reason)"
                    class="text-xs px-1.5 py-0.5 rounded font-medium">
                {{ reasonLabel(offer.hors_perimetre_reason) }}
              </span>
            </div>
            <div v-else class="flex items-center gap-1.5">
              <ScoreBadge :score="offer.desirability" />
              <span class="text-gray-300 text-xs">·</span>
              <ScoreBadge :score="offer.attainability" />
              <span v-if="offer.category" :class="categoryClass(offer.category)"
                    class="text-xs px-1.5 py-0.5 rounded font-medium">
                {{ categoryLabel(offer.category) }}
              </span>
            </div>
          </td>

          <!-- Date -->
          <td class="px-3 py-3 whitespace-nowrap text-gray-400 text-xs">
            {{ offer.fetched_at?.slice(0, 10) ?? '—' }}
          </td>

          <!-- Verdict -->
          <td class="px-3 py-3 whitespace-nowrap">
            <VerdictBadge :verdict="offer.verdict" />
          </td>
        </tr>
      </tbody>
    </table>

    <!-- Loading overlay -->
    <div v-if="store.loading" class="py-8 text-center text-sm text-gray-400 animate-pulse">
      Chargement…
    </div>
  </div>
</template>

<script setup lang="ts">
import { useOffersStore } from '~/stores/offers'

defineEmits<{ select: [offer: ReturnType<typeof useOffersStore>['offers']['value'][number]] }>()
defineProps<{ selectedId?: number }>()

const store = useOffersStore()

const COLS = [
  { key: 'title',        label: 'Poste',       sortable: true  },
  { key: 'company',      label: 'Entreprise',  sortable: false },
  { key: 'contract_type',label: 'Contrat',     sortable: false },
  { key: 'location',     label: 'Lieu',        sortable: false },
  { key: 'desirability', label: 'Désir / Reach', sortable: true  },
  { key: 'fetched_at',   label: 'Récupéré',    sortable: true  },
  { key: 'verdict',      label: 'Verdict',     sortable: false },
]

function categoryLabel(c: string) {
  if (c === 'parfait')     return '★ parfait'
  if (c === 'reve')        return '◈ rêve'
  if (c === 'atteignable') return '✓ atteignable'
  return '✗ hors'
}

function categoryClass(c: string) {
  if (c === 'parfait')     return 'bg-green-50 text-green-700'
  if (c === 'reve')        return 'bg-indigo-50 text-indigo-700'
  if (c === 'atteignable') return 'bg-amber-50 text-amber-700'
  return 'bg-gray-100 text-gray-400'
}

function reasonLabel(r: string) {
  if (r === 'no_tech')    return '⊘ sans techno'
  if (r === 'mgmt_role')  return '⊘ managérial'
  return '⊘ hors-périmètre'
}

function reasonClass(r: string) {
  if (r === 'no_tech')   return 'bg-orange-50 text-orange-600'
  return 'bg-slate-100 text-slate-500'
}

function toggleSort(key: string) {
  if (store.filters.sort === key) {
    store.filters.order = store.filters.order === 'desc' ? 'asc' : 'desc'
  } else {
    store.filters.sort = key
    store.filters.order = 'desc'
  }
  store.fetchOffers()
}
</script>
