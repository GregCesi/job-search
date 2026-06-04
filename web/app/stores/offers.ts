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
  attainability: number | null       // score 0-100 (chantier 2)
  category: string | null            // parfait | reve | atteignable | hors
  score_in_category: number | null
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
  attain_tech: number
  attain_role: number
  blocked_by: string | null
  techs_matched: string[]
  techs_missing: string[]
}

export interface Criterion {
  nom: string
  note: number
  justif: string
  axe: string
}

export interface ReviewOut {
  offer_id: string
  ratings_json: Record<string, { note: number | null; justif: string | null }>
  ai_snapshot_json: Criterion[]
  global_audit_text: string | null
  global_score: number | null
  seen_at_review: boolean
  created_at: string
}

export interface OfferDetail extends OfferRow {
  description: string | null
  url: string | null
  source: string
  extracted_facts: ExtractedFacts | null
  desirability_detail: Record<string, unknown> | null
  attainability_detail: AttainabilityDetail | null
  criteria: Criterion[]
}

export interface Filters {
  desirability_min?: number
  desirability_max?: number
  attainability_min?: number
  category?: string
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
  a_traiter:    { seen: false,                                           sort: 'category',     order: 'desc' },
  atteignables: { desirability_min: 50, attainability_min: 40,           sort: 'desirability', order: 'desc' },
  favoris:      { verdict: 'favori',                                     sort: 'desirability', order: 'desc' },
  tout:         {                                                         sort: 'desirability', order: 'desc' },
}

// ── Store ──────────────────────────────────────────────────────────────────

export const useOffersStore = defineStore('offers', () => {
  const config = useRuntimeConfig()

  const offers = ref<OfferRow[]>([])
  const openedOffer = ref<OfferDetail | null>(null)
  const openedReview = ref<ReviewOut | null>(null)
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
      if (filters.value.attainability_min !== undefined) params.attainability_min = filters.value.attainability_min
      if (filters.value.category !== undefined) params.category = filters.value.category
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
    const [data] = await Promise.all([
      $fetch<OfferDetail>(`${config.public.apiBase}/offers/${id}`),
    ])
    openedOffer.value = data
    openedReview.value = await $fetch<ReviewOut>(
      `${config.public.apiBase}/offers/${id}/review`
    ).catch(() => null)
    const idx = offers.value.findIndex(o => o.id === id)
    if (idx !== -1) offers.value[idx].seen = true
  }

  async function saveReview(
    id: number,
    ratingsJson: Record<string, { note: number | null; justif: string }>,
    globalAuditText: string | null,
    globalScore: number | null,
  ) {
    await $fetch(`${config.public.apiBase}/offers/${id}/review`, {
      method: 'PUT',
      body: { ratings_json: ratingsJson, global_audit_text: globalAuditText, global_score: globalScore },
    })
    openedReview.value = await $fetch<ReviewOut>(
      `${config.public.apiBase}/offers/${id}/review`
    )
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
    openedReview,
    activeView,
    filters,
    loading,
    fetchOffers,
    openDetail,
    setVerdict,
    clearVerdict,
    setView,
    saveReview,
  }
})
