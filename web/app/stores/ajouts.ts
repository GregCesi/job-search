import { defineStore } from 'pinia'

// Ajout à la main d'une offre par son URL ou son texte (EXE-81, EXE-83), sur les
// routes /ajouts (EXE-79, EXE-82). Le store envoie, suit et restitue l'état rendu
// par l'API, tel quel.

export type AjoutStatut =
  | 'en_cours'
  | 'termine'
  | 'filtree'
  | 'hors_perimetre'
  | 'deja_en_base'
  | 'texte_a_coller'
  | 'echec'

export interface Ajout {
  id: number
  url: string | null
  texte: string | null
  statut: AjoutStatut
  offer_id: number | null
  categorie: string | null
  raison: string | null
  causes: string[]
  message: string | null
  created_at: string
  finished_at: string | null
}

export interface AjoutForm {
  url?: string
  texte?: string
  titre?: string
  entreprise?: string
  lieu?: string
}

// Échec de l'envoi lui-même : pas d'ajout créé, seulement le message rendu.
export interface EnvoiEchoue {
  id: string
  url: string | null
  statut: 'echec'
  message: string
}

// Ids des ajouts suivis (en cours ou notifiés non fermés) : survivent au rechargement.
const STORAGE_KEY = 'job-search:ajouts-suivis'
const POLL_MS = 3000

export const useAjoutsStore = defineStore('ajouts', () => {
  const config = useRuntimeConfig()

  const suivis = ref<number[]>([])
  const ajouts = ref<Record<number, Ajout>>({})
  const envois = ref(0)
  const envoisEchoues = ref<EnvoiEchoue[]>([])
  const formulaire = ref<{ ouvert: boolean; initial: AjoutForm }>({
    ouvert: false,
    initial: {},
  })
  // Incrémenté à chaque ajout fini : la page affichée recharge sa liste.
  const termines = ref(0)

  let started = false
  let timer: ReturnType<typeof setTimeout> | null = null

  const enCours = computed(
    () => envois.value + suivis.value.filter(id => ajouts.value[id]?.statut === 'en_cours').length,
  )
  const notifications = computed(() => [
    ...envoisEchoues.value,
    ...suivis.value
      .map(id => ajouts.value[id])
      .filter((a): a is Ajout => !!a && a.statut !== 'en_cours'),
  ])

  function save() {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(suivis.value))
  }

  function load(): number[] {
    try {
      const raw = JSON.parse(localStorage.getItem(STORAGE_KEY) ?? '[]')
      return Array.isArray(raw) ? raw.filter((v): v is number => typeof v === 'number') : []
    } catch {
      return []
    }
  }

  function record(ajout: Ajout) {
    const avant = ajouts.value[ajout.id]
    ajouts.value[ajout.id] = ajout
    if (avant?.statut === 'en_cours' && ajout.statut !== 'en_cours') termines.value++
  }

  async function refresh() {
    if (!suivis.value.length) return
    const recents = await $fetch<Ajout[]>(`${config.public.apiBase}/ajouts`)
    const parId = new Map(recents.map(a => [a.id, a]))
    for (const id of [...suivis.value]) {
      const ajout = parId.get(id)
      if (ajout) {
        record(ajout)
        continue
      }
      // Hors des 24 dernières heures : lu un par un, oublié s'il n'existe plus.
      try {
        record(await $fetch<Ajout>(`${config.public.apiBase}/ajouts/${id}`))
      } catch {
        suivis.value = suivis.value.filter(s => s !== id)
        save()
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
      if (suivis.value.some(id => !isFinished(id))) schedule()
    }, POLL_MS)
  }

  function isFinished(id: number): boolean {
    const ajout = ajouts.value[id]
    return !!ajout && ajout.statut !== 'en_cours'
  }

  async function start() {
    if (started) return
    started = true
    suivis.value = load()
    try {
      await refresh()
    } catch {
      // Rien à afficher tant que l'API ne répond pas ; le suivi reprend au tour suivant.
    }
    if (suivis.value.some(id => !isFinished(id))) schedule()
  }

  function ouvrirFormulaire(initial: AjoutForm = {}) {
    formulaire.value = { ouvert: true, initial }
  }

  function fermerFormulaire() {
    formulaire.value.ouvert = false
  }

  async function envoyer(form: AjoutForm) {
    fermerFormulaire()
    envois.value++
    try {
      const cree = await $fetch<{ id: number; statut: AjoutStatut; url: string | null }>(
        `${config.public.apiBase}/ajouts`,
        { method: 'POST', body: form },
      )
      suivis.value = [...suivis.value, cree.id]
      save()
      ajouts.value[cree.id] = {
        id: cree.id,
        url: cree.url,
        texte: form.texte ?? null,
        statut: cree.statut,
        offer_id: null,
        categorie: null,
        raison: null,
        causes: [],
        message: null,
        created_at: '',
        finished_at: null,
      }
      schedule()
    } catch (err) {
      envoisEchoues.value = [
        ...envoisEchoues.value,
        { id: `envoi-${Date.now()}`, url: form.url ?? null, statut: 'echec', message: messageErreur(err) },
      ]
    } finally {
      envois.value--
    }
  }

  function fermer(id: number | string) {
    if (typeof id === 'string') {
      envoisEchoues.value = envoisEchoues.value.filter(e => e.id !== id)
      return
    }
    suivis.value = suivis.value.filter(s => s !== id)
    delete ajouts.value[id]
    save()
  }

  // Rouvre le formulaire avec l'URL et le texte envoyés, tels que l'API les rend.
  function coller(ajout: Ajout) {
    fermer(ajout.id)
    ouvrirFormulaire({ url: ajout.url ?? '', texte: ajout.texte ?? '' })
  }

  return {
    ajouts,
    formulaire,
    enCours,
    notifications,
    termines,
    start,
    ouvrirFormulaire,
    fermerFormulaire,
    envoyer,
    fermer,
    coller,
  }
})

// Message rendu par l'API (detail FastAPI), sinon celui de l'erreur de transport.
function messageErreur(err: unknown): string {
  const data = (err as { data?: { detail?: unknown } })?.data
  const detail = data?.detail
  if (typeof detail === 'string') return detail
  if (Array.isArray(detail)) {
    return detail.map(d => (d as { msg?: string })?.msg ?? String(d)).join(' ; ')
  }
  return err instanceof Error ? err.message : String(err)
}
