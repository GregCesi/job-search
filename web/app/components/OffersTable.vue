<template>
  <div>
    <!-- Filtre par étape (EXE-199, critère 9) : au-dessus du tableau Suivi
         seulement, nombres rendus par l'API, jamais recalculés ici. -->
    <div v-if="isSuiviView" class="mb-3 flex flex-wrap gap-2">
      <button
        v-for="chip in etapeChips"
        :key="chip.key ?? 'toutes'"
        :class="[
          'px-3 py-1 rounded-full text-xs font-medium transition-colors',
          isEtapeActive(chip.key)
            ? 'bg-indigo-600 text-white'
            : 'bg-gray-100 text-gray-600 hover:bg-gray-200',
        ]"
        @click="store.filterSuiviByEtape(chip.key)"
      >
        {{ chip.label }} ({{ chip.count }})
      </button>
    </div>

    <div class="overflow-x-auto rounded-lg border border-gray-200 bg-white shadow-sm">
      <!-- Empty state -->
      <div v-if="store.offers.length === 0 && !store.loading"
           class="py-16 text-center text-sm text-gray-400">
        Aucune offre dans cette vue.
      </div>

      <!-- Suivi (EXE-199, critères 1-11) : colonnes dédiées, ordre et
           contenu décidés par l'API. -->
      <table v-else-if="isSuiviView" class="min-w-full divide-y divide-gray-100 text-sm">
        <thead class="bg-gray-50 text-xs font-medium text-gray-500 uppercase tracking-wide">
          <tr>
            <th class="px-3 py-3 text-left">Étape</th>
            <th class="px-3 py-3 text-left">Entreprise</th>
            <th class="px-3 py-3 text-left">Poste</th>
            <th class="px-3 py-3 text-left">Dernier geste</th>
            <th class="px-3 py-3 text-left">Temps écoulé</th>
          </tr>
        </thead>
        <tbody class="divide-y divide-gray-50">
          <tr
            v-for="offer in store.offers" :key="offer.id"
            :class="[
              'cursor-pointer transition-colors text-gray-800 hover:bg-indigo-50',
              selectedId === offer.id ? 'bg-indigo-50 ring-1 ring-inset ring-indigo-200' : '',
            ]"
            @click="$emit('select', offer)"
          >
            <td class="px-3 py-3 whitespace-nowrap">
              <VerdictBadge :tri="offer.tri" :etape="offer.etape" :revue="offer.revue_hors_perimetre" />
            </td>
            <td class="px-3 py-3 whitespace-nowrap">{{ offer.company ?? '—' }}</td>
            <td class="px-3 py-3 max-w-xs">
              <span class="block truncate font-medium" :title="offer.title ?? ''">
                {{ offer.title ?? '—' }}
              </span>
            </td>
            <td class="px-3 py-3 whitespace-nowrap text-gray-600">
              <span v-if="offer.dernier_geste_libelle">
                {{ offer.dernier_geste_libelle }}
                <span class="text-gray-400 text-xs">· {{ offer.dernier_geste_effet_at?.slice(0, 10) }}</span>
              </span>
              <span v-else class="text-gray-300">—</span>
            </td>
            <td class="px-3 py-3 whitespace-nowrap text-gray-500 text-xs">
              {{ offer.temps_depuis_libelle ?? '—' }}
            </td>
          </tr>
        </tbody>
      </table>

      <table v-else class="min-w-full divide-y divide-gray-100 text-sm">
        <thead class="bg-gray-50 text-xs font-medium text-gray-500 uppercase tracking-wide">
          <tr>
            <th v-if="props.mode === 'operateur'" class="w-6 px-3 py-3"></th>
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
            <!-- Écartées (EXE-194, critère 9) : date et motif de l'écart, rendus par l'API -->
            <th v-if="isEcarteesView" class="px-3 py-3 text-left">Écartée le</th>
            <th v-if="isEcarteesView" class="px-3 py-3 text-left">Motif</th>
          </tr>
        </thead>
        <tbody class="divide-y divide-gray-50">
          <tr
            v-for="offer in store.offers" :key="offer.id"
            :class="[
              'cursor-pointer transition-colors',
              offer.seen_candidat
                ? 'text-gray-400 hover:bg-gray-50'
                : 'text-gray-800 hover:bg-indigo-50',
              selectedId === offer.id ? 'bg-indigo-50 ring-1 ring-inset ring-indigo-200' : '',
            ]"
            @click="$emit('select', offer)"
          >
            <!-- Review state dot — opérateur uniquement -->
            <td v-if="props.mode === 'operateur'" class="px-3 py-3">
              <span v-if="offer.etat_review === 'non_relue'" class="block w-2 h-2 rounded-full bg-indigo-400" title="Non relue" />
              <span v-else-if="offer.etat_review === 'validee'" class="block w-2 h-2 rounded-full bg-green-400" title="Validée" />
              <span v-else-if="offer.etat_review === 'corrigee'" class="block w-2 h-2 rounded-full bg-amber-400" title="Corrigée" />
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

            <!-- Catégorie (finale ou hors-périmètre) -->
            <td class="px-3 py-3 whitespace-nowrap">
              <div v-if="offer.perimetre_causes?.length" class="flex items-center gap-1">
                <span v-for="cause in offer.perimetre_causes" :key="cause"
                      :class="reasonClass(cause)"
                      class="text-xs px-1.5 py-0.5 rounded font-medium">
                  {{ reasonLabel(cause) }}
                </span>
              </div>
              <div v-else-if="offer.hors_perimetre_reason" class="flex items-center gap-1.5">
                <span :class="reasonClass(offer.hors_perimetre_reason)"
                      class="text-xs px-1.5 py-0.5 rounded font-medium">
                  {{ reasonLabel(offer.hors_perimetre_reason) }}
                </span>
              </div>
              <div v-else class="flex items-center gap-1.5">
                <span v-if="offer.categorie_finale" :class="categoryClass(offer.categorie_finale)"
                      class="text-xs px-1.5 py-0.5 rounded font-medium">
                  {{ categoryLabel(offer.categorie_finale) }}
                </span>
                <span v-else-if="offer.category" :class="categoryClass(offer.category)"
                      class="text-xs px-1.5 py-0.5 rounded font-medium opacity-60">
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
              <div class="flex items-center gap-1.5">
                <VerdictBadge :tri="offer.tri" :etape="offer.etape" :revue="offer.revue_hors_perimetre" />
                <span
                  v-if="offer.expired"
                  class="inline-flex items-center px-2 py-0.5 rounded-full bg-red-100 text-red-700 text-xs font-medium"
                >
                  Expiré
                </span>
              </div>
            </td>

            <!-- Écartées (EXE-194, critère 9) -->
            <td v-if="isEcarteesView" class="px-3 py-3 whitespace-nowrap text-gray-400 text-xs">
              {{ offer.ecartee_le?.slice(0, 10) ?? '—' }}
            </td>
            <td v-if="isEcarteesView" class="px-3 py-3 max-w-xs truncate text-gray-500 text-xs" :title="offer.motif_ecart ?? ''">
              {{ offer.motif_ecart ?? '—' }}
            </td>
          </tr>
        </tbody>
      </table>

      <!-- Loading overlay -->
      <div v-if="store.loading" class="py-8 text-center text-sm text-gray-400 animate-pulse">
        Chargement…
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { useOffersStore } from '~/stores/offers'

import type { OfferRow } from '~/stores/offers'
defineEmits<{ select: [offer: OfferRow] }>()
const props = withDefaults(defineProps<{ selectedId?: number; mode?: 'candidat' | 'operateur' }>(), { mode: 'candidat' })

const store = useOffersStore()

const isEcarteesView = computed(() => store.activeView === 'ecartees')
const isSuiviView = computed(() => store.activeView === 'suivi')

const COLS = [
  { key: 'title',        label: 'Poste',       sortable: true  },
  { key: 'company',      label: 'Entreprise',  sortable: true  },
  { key: 'contract_type',label: 'Contrat',     sortable: true  },
  { key: 'location',     label: 'Lieu',        sortable: true  },
  { key: 'category',     label: 'Catégorie',   sortable: true  },
  { key: 'fetched_at',   label: 'Récupéré',    sortable: true  },
  { key: 'verdict',      label: 'Verdict',     sortable: true  },
]

// Libellés d'affichage des chips du filtre Suivi — purement textuel, les
// nombres comme la liste des étapes connues viennent de l'API (critère 11).
const ETAPE_FILTER_LABELS: Record<string, string> = {
  retenue: 'Retenue',
  prete_a_l_envoi: 'Prête à l\'envoi',
  candidature_envoyee: 'Candidature envoyée',
  entretien: 'Entretien',
  offre_recue: 'Offre reçue',
  refusee: 'Refusée',
  sans_suite: 'Sans suite',
  abandonnee: 'Abandonnée',
}
const ETAPE_ORDER = [
  'retenue', 'prete_a_l_envoi', 'candidature_envoyee', 'entretien',
  'offre_recue', 'refusee', 'sans_suite', 'abandonnee',
]

const etapeChips = computed(() => {
  const counts = store.suiviEtapesCount
  const chips = [{ key: null as string | null, label: 'Toutes', count: counts.toutes ?? 0 }]
  for (const etape of ETAPE_ORDER) {
    if (etape in counts) {
      chips.push({ key: etape, label: ETAPE_FILTER_LABELS[etape] ?? etape, count: counts[etape] ?? 0 })
    }
  }
  return chips
})

function isEtapeActive(key: string | null): boolean {
  return (store.filters.etape ?? null) === key
}

function categoryLabel(c: string) {
  if (c === 'parfait')        return '★ parfait'
  if (c === 'reve')           return '◈ rêve'
  if (c === 'atteignable')    return '✓ atteignable'
  if (c === 'hors_perimetre') return '⊘ hors-périmètre'
  return '✗ hors'
}

function categoryClass(c: string) {
  if (c === 'parfait')        return 'bg-green-50 text-green-700'
  if (c === 'reve')           return 'bg-indigo-50 text-indigo-700'
  if (c === 'atteignable')    return 'bg-amber-50 text-amber-700'
  if (c === 'hors_perimetre') return 'bg-slate-100 text-slate-500'
  return 'bg-gray-100 text-gray-400'
}

function reasonLabel(r: string) {
  if (r === 'no_tech')    return '⊘ sans techno'
  if (r === 'mgmt_role')  return '⊘ managérial'
  if (r === 'langue')     return '⊘ langue tierce'
  if (r === 'contrat')    return '⊘ stage/alternance'
  return '⊘ hors-périmètre'
}

function reasonClass(r: string) {
  if (r === 'no_tech')    return 'bg-orange-50 text-orange-600'
  if (r === 'langue')     return 'bg-violet-50 text-violet-600'
  if (r === 'contrat')    return 'bg-cyan-50 text-cyan-600'
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
