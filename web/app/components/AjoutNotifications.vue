<template>
  <Teleport to="body">
    <div
      v-if="ajouts.notifications.length || pieceNotifs.notifications.length"
      class="fixed bottom-4 right-4 z-50 w-80 flex flex-col gap-2"
      aria-live="polite"
    >
      <NotificationToast
        v-for="notif in ajouts.notifications"
        :key="notif.id"
        :auto-retrait="autoRetraitAjout(notif)"
        :class="ouvrable(notif) ? 'cursor-pointer hover:bg-gray-50' : ''"
        :role="ouvrable(notif) ? 'button' : undefined"
        :tabindex="ouvrable(notif) ? 0 : undefined"
        @click="ouvrable(notif) && ouvrir(notif as Ajout)"
        @keydown.enter="ouvrable(notif) && ouvrir(notif as Ajout)"
        @fermer="ajouts.fermer(notif.id)"
      >
        <button
          class="absolute top-2 right-2 text-gray-400 hover:text-gray-600"
          aria-label="Fermer la notification"
          @click.stop="ajouts.fermer(notif.id)"
        >
          <svg class="w-4 h-4" fill="none" stroke="currentColor" stroke-width="2" viewBox="0 0 24 24">
            <path stroke-linecap="round" stroke-linejoin="round" d="M6 18L18 6M6 6l12 12"/>
          </svg>
        </button>

        <p class="font-semibold" :class="TITRES[notif.statut].classe">
          {{ TITRES[notif.statut].libelle }}
        </p>
        <p v-if="notif.url" class="text-xs text-gray-400 truncate" :title="notif.url">{{ notif.url }}</p>

        <p v-if="notif.statut === 'termine'" class="mt-1 text-gray-700">
          Catégorie : <span class="font-medium">{{ (notif as Ajout).categorie }}</span>
        </p>
        <p v-else-if="notif.statut === 'filtree'" class="mt-1 text-gray-700">
          {{ (notif as Ajout).raison }}
        </p>
        <ul v-else-if="notif.statut === 'hors_perimetre'" class="mt-1 text-gray-700 list-disc list-inside">
          <li v-for="cause in (notif as Ajout).causes" :key="cause">{{ cause }}</li>
        </ul>
        <template v-else-if="notif.statut === 'texte_a_coller'">
          <p class="mt-1 text-gray-700">{{ notif.message }}</p>
          <button
            class="mt-2 px-2.5 py-1 rounded-md text-xs font-medium bg-indigo-600 text-white hover:bg-indigo-700 transition-colors"
            @click.stop="ajouts.coller(notif as Ajout)"
          >
            Coller le texte de l'offre
          </button>
        </template>
        <template v-else-if="notif.statut === 'echec'">
          <p class="mt-1 text-gray-700">{{ notif.message }}</p>
          <button
            v-if="typeof notif.id === 'number'"
            class="mt-2 px-2.5 py-1 rounded-md text-xs font-medium bg-indigo-600 text-white hover:bg-indigo-700 transition-colors"
            @click.stop="ajouts.coller(notif as Ajout)"
          >
            Rouvrir le formulaire
          </button>
        </template>
      </NotificationToast>

      <!-- Avancement des pièces d'une offre retenue (EXE-128) -->
      <NotificationToast
        v-for="notif in pieceNotifs.notifications"
        :key="notif.id"
        :auto-retrait="autoRetraitPiece(notif)"
        class="cursor-pointer hover:bg-gray-50"
        role="button"
        tabindex="0"
        @click="ouvrirOffre(notif.offerId)"
        @keydown.enter="ouvrirOffre(notif.offerId)"
        @fermer="pieceNotifs.fermer(notif.id)"
      >
        <button
          class="absolute top-2 right-2 text-gray-400 hover:text-gray-600"
          aria-label="Fermer la notification"
          @click.stop="pieceNotifs.fermer(notif.id)"
        >
          <svg class="w-4 h-4" fill="none" stroke="currentColor" stroke-width="2" viewBox="0 0 24 24">
            <path stroke-linecap="round" stroke-linejoin="round" d="M6 18L18 6M6 6l12 12"/>
          </svg>
        </button>

        <p class="font-semibold" :class="notif.etat === 'terminee' ? 'text-indigo-700' : 'text-red-700'">
          {{ titreNotification(notif) }}
        </p>
        <p class="text-xs text-gray-400 truncate">{{ notif.title ?? '(sans titre)' }}</p>
        <p v-if="notif.etat === 'en_erreur' && notif.raison" class="mt-1 text-gray-700">{{ notif.raison }}</p>
      </NotificationToast>
    </div>
  </Teleport>
</template>

<script setup lang="ts">
import { useAjoutsStore } from '~/stores/ajouts'
import { useOffersStore } from '~/stores/offers'
import type { Ajout, AjoutStatut, EnvoiEchoue } from '~/stores/ajouts'
import { titreNotification, usePieceNotificationsStore } from '~/stores/pieceNotifications'
import type { PieceNotification } from '~/stores/pieceNotifications'

const ajouts = useAjoutsStore()
const offers = useOffersStore()
const pieceNotifs = usePieceNotificationsStore()
const route = useRoute()
const router = useRouter()

// Une notification de pièce ouvre toujours la page de l'offre, qu'elle qu'elle soit.
function ouvrirOffre(offerId: number) {
  router.push(`/offers/${offerId}`)
}

const TITRES: Record<Exclude<AjoutStatut, 'en_cours'>, { libelle: string; classe: string }> = {
  termine:        { libelle: 'Offre ajoutée',        classe: 'text-indigo-700' },
  filtree:        { libelle: 'Filtrée',              classe: 'text-gray-700' },
  hors_perimetre: { libelle: 'Hors périmètre',       classe: 'text-gray-700' },
  deja_en_base:   { libelle: 'Déjà en base',         classe: 'text-gray-700' },
  texte_a_coller: { libelle: 'Texte à coller',       classe: 'text-amber-700' },
  echec:          { libelle: 'Échec',                classe: 'text-red-700' },
}

const OUVRABLES: AjoutStatut[] = ['termine', 'filtree', 'hors_perimetre', 'deja_en_base']

function ouvrable(notif: Ajout | EnvoiEchoue): boolean {
  return typeof notif.id === 'number' && OUVRABLES.includes(notif.statut) && (notif as Ajout).offer_id !== null
}

// Un échec ou une notification à bouton d'action (coller le texte, rouvrir
// le formulaire) ne se retire jamais seul (EXE-136).
function autoRetraitAjout(notif: Ajout | EnvoiEchoue): boolean {
  return OUVRABLES.includes(notif.statut)
}

function autoRetraitPiece(notif: PieceNotification): boolean {
  return notif.etat === 'terminee'
}

// Le détail s'ouvre sur la page d'accueil, quelle que soit la catégorie de l'offre.
function ouvrir(ajout: Ajout) {
  const id = ajout.offer_id!
  if (route.path === '/') {
    offers.openDetail(id)
    return
  }
  router.push({ path: '/', query: { offre: String(id) } })
}

// Un ajout fini : la liste affichée se recharge.
watch(
  () => ajouts.termines,
  () => {
    if (route.path === '/') offers.fetchOffers()
  },
)
</script>
