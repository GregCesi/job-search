import { defineStore } from 'pinia'

// ── Types ──────────────────────────────────────────────────────────────────

export interface OfferRow {
  id: number
  title: string | null
  company: string | null
  location: string | null
  remote: boolean
  contract_type: string | null
  score: number | null
  verdict: string | null
  seen: boolean
  fetched_at: string
}

export interface CriterionScore {
  key: string
  score: number
  justification: string
  parse_failed: boolean
}

export interface OfferDetail extends OfferRow {
  description: string | null
  url: string | null
  source: string
  criteria: CriterionScore[]
}

export interface Filters {
  score_min?: number
  score_max?: number
  remote?: boolean
  source?: string
  verdict?: string
  seen?: boolean
  q?: string
  sort: string
  order: 'asc' | 'desc'
}

export type ActiveView = 'a_traiter' | 'top_scores' | 'favoris' | 'tout'

// Préréglages de filtres par vue
const VIEW_PRESETS: Record<ActiveView, Partial<Filters>> = {
  a_traiter:  { seen: false, sort: 'score', order: 'desc' },
  top_scores: { score_min: 80, sort: 'score', order: 'desc' },
  favoris:    { verdict: 'favori', sort: 'score', order: 'desc' },
  tout:       { sort: 'score', order: 'desc' },
}

// ── Store ──────────────────────────────────────────────────────────────────

export const useOffersStore = defineStore('offers', () => {
  const config = useRuntimeConfig()

  const offers = ref<OfferRow[]>([])
  const openedOffer = ref<OfferDetail | null>(null)
  const activeView = ref<ActiveView>('a_traiter')
  const filters = ref<Filters>({ ...VIEW_PRESETS.a_traiter, sort: 'score', order: 'desc' })
  const loading = ref(false)

  async function fetchOffers() {
    loading.value = true
    try {
      const params: Record<string, string | number | boolean> = {
        sort: filters.value.sort,
        order: filters.value.order,
      }
      if (filters.value.score_min !== undefined) params.score_min = filters.value.score_min
      if (filters.value.score_max !== undefined) params.score_max = filters.value.score_max
      if (filters.value.remote !== undefined) params.remote = filters.value.remote
      if (filters.value.source !== undefined) params.source = filters.value.source
      if (filters.value.verdict !== undefined) params.verdict = filters.value.verdict
      if (filters.value.seen !== undefined) params.seen = filters.value.seen
      if (filters.value.q) params.q = filters.value.q

      const data = await $fetch<OfferRow[]>(`${config.public.apiBase}/offers`, { params })
      offers.value = data
      console.log(`[offers] ${data.length} offres chargées`, data)
    } finally {
      loading.value = false
    }
  }

  async function openDetail(id: number) {
    const data = await $fetch<OfferDetail>(`${config.public.apiBase}/offers/${id}`)
    openedOffer.value = data
    // Mettre à jour seen dans la liste locale
    const idx = offers.value.findIndex(o => o.id === id)
    if (idx !== -1) offers.value[idx].seen = true
  }

  async function setVerdict(id: number, status: string) {
    await $fetch(`${config.public.apiBase}/offers/${id}/verdict`, {
      method: 'PUT',
      body: { status },
    })
    const idx = offers.value.findIndex(o => o.id === id)
    if (idx !== -1) {
      offers.value[idx].verdict = status
      // "masqué" disparaît des vues filtrées (tout sauf "tout")
      if (status === 'masqué' && activeView.value !== 'tout') {
        offers.value.splice(idx, 1)
        openedOffer.value = null
        return
      }
    }
    if (openedOffer.value?.id === id) openedOffer.value.verdict = status
  }

  async function clearVerdict(id: number) {
    await $fetch(`${config.public.apiBase}/offers/${id}/verdict`, { method: 'DELETE' })
    const idx = offers.value.findIndex(o => o.id === id)
    if (idx !== -1) offers.value[idx].verdict = null
    if (openedOffer.value?.id === id) openedOffer.value.verdict = null
  }

  function setView(view: ActiveView) {
    activeView.value = view
    filters.value = { sort: 'score', order: 'desc', ...VIEW_PRESETS[view] }
    fetchOffers()
  }

  return {
    offers,
    openedOffer,
    activeView,
    filters,
    loading,
    fetchOffers,
    openDetail,
    setVerdict,
    clearVerdict,
    setView,
  }
})
