<template>
  <Teleport to="body">
    <div v-if="panel.ouvert" class="fixed inset-0 z-40 bg-black/10" @click="panel.fermer()" />
    <aside
      v-if="panel.ouvert"
      class="fixed inset-y-0 right-0 z-50 w-96 bg-white border-l border-gray-200 shadow-xl flex flex-col"
      aria-label="Panneau de notifications"
    >
      <header class="flex items-center justify-between px-4 py-3 border-b border-gray-100">
        <h2 class="text-sm font-semibold text-gray-800">Notifications</h2>
        <button
          class="text-gray-400 hover:text-gray-600"
          aria-label="Fermer le panneau"
          @click="panel.fermer()"
        >
          <svg class="w-4 h-4" fill="none" stroke="currentColor" stroke-width="2" viewBox="0 0 24 24">
            <path stroke-linecap="round" stroke-linejoin="round" d="M6 18L18 6M6 6l12 12" />
          </svg>
        </button>
      </header>

      <div class="flex items-center justify-end px-4 py-2 border-b border-gray-100">
        <button
          class="text-xs text-indigo-600 hover:underline disabled:text-gray-300 disabled:no-underline"
          :disabled="!panel.entrees.length"
          @click="panel.toutEffacer()"
        >
          Tout effacer
        </button>
      </div>

      <ul class="flex-1 overflow-y-auto divide-y divide-gray-100">
        <li v-if="!panel.entrees.length" class="px-4 py-6 text-sm text-gray-400 text-center">
          Aucune notification pour l'instant.
        </li>
        <li
          v-for="entree in panel.entrees"
          :key="entree.cle"
          class="px-4 py-3 text-sm"
          :class="entree.offerId !== null ? 'cursor-pointer hover:bg-gray-50' : ''"
          :role="entree.offerId !== null ? 'button' : undefined"
          :tabindex="entree.offerId !== null ? 0 : undefined"
          @click="ouvrirOffre(entree)"
          @keydown.enter="ouvrirOffre(entree)"
        >
          <p class="font-medium text-gray-800">{{ entree.titre }}</p>
          <p v-if="entree.sousTitre" class="text-xs text-gray-400 truncate">{{ entree.sousTitre }}</p>
          <p class="mt-1 text-xs text-gray-400">{{ formatHeure(entree.heure) }}</p>
        </li>
      </ul>
    </aside>
  </Teleport>
</template>

<script setup lang="ts">
import { useNotificationsPanelStore } from '~/stores/notificationsPanel'
import type { EntreeHistorique } from '~/stores/notificationsPanel'
import { useOffersStore } from '~/stores/offers'

const panel = useNotificationsPanelStore()
const offers = useOffersStore()
const route = useRoute()
const router = useRouter()

// Une ligne ouvre exactement ce qu'ouvre la notification dont elle vient
// (EXE-138) : une pièce vers la page de l'offre retenue, un ajout vers la
// page d'accueil, comme leurs toasts respectifs (AjoutNotifications.vue).
function ouvrirOffre(entree: EntreeHistorique) {
  if (entree.offerId === null) return
  panel.fermer()
  if (entree.cle.startsWith('piece:')) {
    router.push(`/offers/${entree.offerId}`)
    return
  }
  if (route.path === '/') {
    offers.openDetail(entree.offerId)
    return
  }
  router.push({ path: '/', query: { offre: String(entree.offerId) } })
}

function formatHeure(iso: string): string {
  return new Date(iso).toLocaleTimeString('fr-FR', { hour: '2-digit', minute: '2-digit' })
}
</script>
