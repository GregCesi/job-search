<template>
  <aside class="w-44 shrink-0 bg-white border-r border-gray-200 sticky top-0 h-screen overflow-y-auto">
    <nav aria-label="Vue candidat" class="flex flex-col gap-1 p-3">
      <template v-for="entry in MENU" :key="entry.label">
        <button
          v-if="'view' in entry"
          :class="itemClass(isActive(entry))"
          :aria-current="isActive(entry) ? 'page' : undefined"
          @click="openView(entry.view)"
        >
          {{ entry.label }}
        </button>
        <NuxtLink
          v-else
          :to="entry.to"
          :class="itemClass(isActive(entry))"
          :aria-current="isActive(entry) ? 'page' : undefined"
        >
          {{ entry.label }}
        </NuxtLink>
      </template>
    </nav>

    <!-- Ajout d'une offre par URL (EXE-81) -->
    <div class="flex flex-col gap-1.5 px-3 pb-3 pt-2 border-t border-gray-100">
      <button
        class="px-3 py-1.5 rounded-md text-sm font-medium text-left bg-indigo-50 text-indigo-700 hover:bg-indigo-100 transition-colors"
        @click="ajouts.ouvrirFormulaire()"
      >
        Ajouter une offre
      </button>
      <p v-if="ajouts.enCours" class="px-3 text-xs text-gray-500" aria-live="polite">
        {{ ajouts.enCours }} ajout{{ ajouts.enCours > 1 ? 's' : '' }} en cours…
      </p>
    </div>

    <AjoutForm />
    <AjoutNotifications />
  </aside>
</template>

<script setup lang="ts">
import { useOffersStore } from '~/stores/offers'
import type { CandidateView } from '~/stores/offers'
import { useAjoutsStore } from '~/stores/ajouts'
import { usePieceNotificationsStore } from '~/stores/pieceNotifications'

// Entrées du menu candidat, déclarées ici et nulle part ailleurs (EXE-80).
// Une entrée `view` ouvre une vue de VIEW_PRESETS sur la page d'accueil ;
// une entrée `to` mènerait à une autre page.
type MenuEntry = { label: string; view: CandidateView } | { label: string; to: string }

const MENU: MenuEntry[] = [
  { label: 'Cibles',   view: 'cibles'   },
  { label: 'Gaps',     view: 'gaps'     },
  { label: 'Filet',    view: 'filet'    },
  { label: 'Retenues', view: 'retenues' },
]

const store = useOffersStore()
const ajouts = useAjoutsStore()
const pieceNotifs = usePieceNotificationsStore()
const route = useRoute()
const router = useRouter()

// Le suivi des ajouts et des pièces démarre une fois par session, sur la
// première page du cadre (EXE-128 pour les pièces).
onMounted(() => {
  ajouts.start()
  pieceNotifs.start()
})

function isActive(entry: MenuEntry): boolean {
  if ('view' in entry) return route.path === '/' && store.activeView === entry.view
  return route.path === entry.to
}

function openView(view: CandidateView) {
  if (route.path !== '/') {
    router.push({ path: '/', query: { vue: view } })
    return
  }
  if (route.query.vue) router.replace({ path: '/' })
  store.setView(view)
}

function itemClass(active: boolean): string[] {
  return [
    'px-3 py-1.5 rounded-md text-sm font-medium text-left transition-colors',
    active ? 'bg-indigo-600 text-white' : 'text-gray-600 hover:bg-gray-100',
  ]
}
</script>
