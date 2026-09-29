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
  </aside>
</template>

<script setup lang="ts">
import { useOffersStore } from '~/stores/offers'
import type { CandidateView } from '~/stores/offers'

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
const route = useRoute()
const router = useRouter()

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
