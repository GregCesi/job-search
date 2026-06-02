import { defineStore } from 'pinia'

// ── Types ──────────────────────────────────────────────────────────────────

export interface OfferRow {
  id: number
  title: string | null
  company: string | null
  location: string | null
  remote: boolean
  contract_type: string | null
  desirability: number | null
  attainability: string | null
  verdict: string | null
  seen: boolean
  fetched_at: string
}

export interface ExtractedFacts {
  seniority_required: string
  techs_required: string[]
  domain: string
  parse_failed: boolean
}

export interface AttainabilityDetail {
  techs_matched: string[]
  techs_missing: string[]
  seniority_gap: number
}

export interface OfferDetail extends OfferRow {
  description: string | null
  url: string | null
  source: string
  extracted_facts: ExtractedFacts | null
  desirability_detail: Record<string, unknown> | null
  attainability_detail: AttainabilityDetail | null
}

export interface Filters {
  desirability_min?: number
  desirability_max?: number
  attainability?: string
  remote?: boolean
  source?: string
  verdict?: string
  seen?: boolean
  q?: string
  sort: string
  order: 'asc' | 'desc'
}

export type ActiveView = 'a_traiter' | 'atteignables' | 'favoris' | 'tout'

const VIEW_PRESETS: Record<ActiveView, Partial<Filters>> = {
  a_traiter:    { seen: false,                              sort: 'desirability', order: 'desc' },
  atteignables: { desirability_min: 60, attainability: 'at_level', sort: 'desirability', order: 'desc' },
  favoris:      { verdict: 'favori',                        sort: 'desirability', order: 'desc' },
  tout:         {                                            sort: 'desirability', order: 'desc' },
}

// ── Store ──────────────────────────────────────────────────────────────────

export const useOffersStore = defineStore('offers', () => {
  const config = useRuntimeConfig()

  const offers = ref<OfferRow[]>([])
  const openedOffer = ref<OfferDetail | null>(null)
  const activeView = ref<ActiveView>('a_traiter')
  const filters = ref<Filters>({ ...VIEW_PRESETS.a_traiter })
  const loading = ref(false)

  async function fetchOffers() {
    loading.value = true
    try {
      const params: Record<string, string | number | boolean> = {
        sort: filters.value.sort,
        order: filters.value.order,
      }
      if (filters.value.desirability_min !== undefined) params.desirability_min = filters.value.desirability_min
      if (filters.value.desirability_max !== undefined) params.desirability_max = filters.value.desirability_max
      if (filters.value.attainability !== undefined) params.attainability = filters.value.attainability
      if (filters.value.remote !== undefined) params.remote = filters.value.remote
      if (filters.value.source !== undefined) params.source = filters.value.source
      if (filters.value.verdict !== undefined) params.verdict = filters.value.verdict
      if (filters.value.seen !== undefined) params.seen = filters.value.seen
      if (filters.value.q) params.q = filters.value.q

      const data = await $fetch<OfferRow[]>(`${config.public.apiBase}/offers`, { params })
      offers.value = data
    } finally {
      loading.value = false
    }
  }

  async function openDetail(id: number) {
    const data = await $fetch<OfferDetail>(`${config.public.apiBase}/offers/${id}`)
    openedOffer.value = data
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
    filters.value = { sort: 'desirability', order: 'desc', ...VIEW_PRESETS[view] }
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
