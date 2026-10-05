import { defineStore } from 'pinia'
import type { Avancement } from '~/stores/offers'

// Avancement des pièces d'une offre retenue, vu depuis n'importe quelle page
// (EXE-128) : poll de `GET /avancement` (EXE-127), qui ne rend que les offres
// dont une pièce tourne ou vient de changer d'état. Fiche, CV, lettre
// seulement — le mail se recalcule à la demande, jamais en tâche de fond.

export type PieceKey = 'fiche' | 'cv' | 'lettre'

interface AvancementOffre {
  id: number
  title: string | null
  avancement: Avancement
}

export interface PieceNotification {
  id: string
  offerId: number
  title: string | null
  piece: PieceKey
  etat: 'terminee' | 'en_erreur'
  raison: string | null
}

const PIECES: PieceKey[] = ['fiche', 'cv', 'lettre']

const TITRES_TERMINEE: Record<PieceKey, string> = {
  fiche: 'Fiche entreprise prête à relire',
  cv: 'CV prêt à relire',
  lettre: 'Lettre prête à relire',
}

const TITRES_ERREUR: Record<PieceKey, string> = {
  fiche: 'Échec de la fiche entreprise',
  cv: 'Échec du CV',
  lettre: 'Échec de la lettre',
}

export function titreNotification(n: PieceNotification): string {
  return n.etat === 'terminee' ? TITRES_TERMINEE[n.piece] : TITRES_ERREUR[n.piece]
}

const POLL_MS = 4000

export const usePieceNotificationsStore = defineStore('pieceNotifications', () => {
  const config = useRuntimeConfig()

  const notifications = ref<PieceNotification[]>([])
  // Dernier état terminal déjà notifié par pièce — évite de renotifier tant que
  // rien n'a changé ; effacé dès que la pièce redevient active (régénération).
  const vus = ref<Record<string, 'terminee' | 'en_erreur'>>({})

  let started = false
  let timer: ReturnType<typeof setTimeout> | null = null

  async function refresh() {
    const liste = await $fetch<AvancementOffre[]>(`${config.public.apiBase}/avancement`)
    for (const offre of liste) {
      for (const piece of PIECES) {
        const av = offre.avancement[piece]
        const cle = `${offre.id}:${piece}`
        if (av.etat === 'terminee' || av.etat === 'en_erreur') {
          if (vus.value[cle] === av.etat) continue
          vus.value[cle] = av.etat
          notifications.value = [
            ...notifications.value,
            {
              id: `${cle}:${Date.now()}`,
              offerId: offre.id,
              title: offre.title,
              piece,
              etat: av.etat,
              raison: av.raison,
            },
          ]
        } else {
          delete vus.value[cle]
        }
      }
    }
  }

  function schedule() {
    if (timer !== null) return
    timer = setTimeout(async () => {
      timer = null
      try {
        await refresh()
      } catch {
        // API momentanément injoignable : on retentera au tour suivant.
      }
      schedule()
    }, POLL_MS)
  }

  async function start() {
    if (started) return
    started = true
    try {
      await refresh()
    } catch {
      // Rien à afficher tant que l'API ne répond pas ; le suivi reprend au tour suivant.
    }
    schedule()
  }

  function fermer(id: string) {
    notifications.value = notifications.value.filter(n => n.id !== id)
  }

  return {
    notifications,
    start,
    fermer,
  }
})
