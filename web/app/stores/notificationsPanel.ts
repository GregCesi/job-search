import { defineStore } from 'pinia'
import { useAjoutsStore } from '~/stores/ajouts'
import type { AjoutStatut } from '~/stores/ajouts'
import { usePieceNotificationsStore, titreNotification } from '~/stores/pieceNotifications'

// Historique des notifications de la séance (EXE-136) : garde la trace de
// chaque notification des deux familles (ajout d'offre, pièces d'une offre
// retenue) même après son retrait du toast, auto ou manuel. En mémoire
// seulement — se vide au rechargement de la page, comme le suivi des ajouts
// (ajouts.ts) et des pièces (pieceNotifications.ts) dont il dépend.

export interface EntreeHistorique {
  cle: string
  offerId: number | null
  titre: string
  sousTitre: string | null
  heure: string
  vue: boolean
}

const TITRES_AJOUT: Record<AjoutStatut, string> = {
  en_cours: 'En cours',
  termine: 'Offre ajoutée',
  filtree: 'Filtrée',
  hors_perimetre: 'Hors périmètre',
  deja_en_base: 'Déjà en base',
  texte_a_coller: 'Texte à coller',
  echec: 'Échec',
}

export const useNotificationsPanelStore = defineStore('notificationsPanel', () => {
  const entrees = ref<EntreeHistorique[]>([])
  const ouvert = ref(false)
  const cles = new Set<string>()

  const nonVues = computed(() => entrees.value.filter(e => !e.vue).length)

  function ajouter(entree: Omit<EntreeHistorique, 'vue' | 'heure'>) {
    if (cles.has(entree.cle)) return
    cles.add(entree.cle)
    entrees.value = [{ ...entree, heure: new Date().toISOString(), vue: ouvert.value }, ...entrees.value]
  }

  function ouvrir() {
    ouvert.value = true
    entrees.value = entrees.value.map(e => (e.vue ? e : { ...e, vue: true }))
  }

  function fermer() {
    ouvert.value = false
  }

  function toutEffacer() {
    entrees.value = []
    cles.clear()
  }

  const ajouts = useAjoutsStore()
  const pieceNotifs = usePieceNotificationsStore()

  watch(
    () => ajouts.notifications,
    (liste) => {
      for (const notif of liste) {
        ajouter({
          cle: `ajout:${notif.id}`,
          offerId: 'offer_id' in notif ? notif.offer_id : null,
          titre: TITRES_AJOUT[notif.statut],
          sousTitre: notif.url,
        })
      }
    },
    { deep: true },
  )

  watch(
    () => pieceNotifs.notifications,
    (liste) => {
      for (const notif of liste) {
        ajouter({
          cle: `piece:${notif.id}`,
          offerId: notif.offerId,
          titre: titreNotification(notif),
          sousTitre: notif.title,
        })
      }
    },
    { deep: true },
  )

  return { entrees, ouvert, nonVues, ouvrir, fermer, toutEffacer }
})
