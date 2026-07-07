import { defineStore } from 'pinia'

// ── Types ──────────────────────────────────────────────────────────────────

export interface OfferRow {
  id: number
  title: string | null
  company: string | null
  location: string | null
  remote: boolean
  contract_type: string | null
  category: string | null            // parfait | reve | atteignable | hors
  verdict: string | null
  hors_perimetre_reason: string | null
  seen_candidat: boolean
  fetched_at: string
  // review humaine
  categorie_suggeree: string | null
  categorie_corrigee: string | null
  categorie_finale: string | null    // dérivé API
  etat_review: string | null         // non_relue | validee | corrigee
  remarque: string | null
  reviewed_at: string | null
}

export interface TechInfo {
  name: string
  importance: string | null  // core | required | nice_to_have
}

export interface ExtractedFacts {
  seniority_required: string
  techs_required: TechInfo[]
  domain: string
  role_level: string | null  // ic | lead | manager
  parse_failed: boolean
}

export interface OfferDetail extends OfferRow {
  source_id: string
  description: string | null
  url: string | null
  source: string
  extracted_facts: ExtractedFacts | null
  techs_matched: string[]
  techs_missing: string[]
  score_breakdown?: string | null
}

export interface Filters {
  category?: string
  exclude_category?: string
  hors_perimetre?: boolean
  etat_review?: string
  remote?: boolean
  source?: string
  verdict?: string
  seen_candidat?: boolean
  q?: string
  sort: string
  order: string
}

// Candidat (page /)
export type CandidateView = 'cibles' | 'gaps' | 'filet' | 'retenues'
// Opérateur (page /operateur)
export type OperatorView = 'a_traiter' | 'hors_perimetre' | 'tout'

export type ActiveView = CandidateView | OperatorView

const VIEW_PRESETS: Record<ActiveView, Omit<Partial<Filters>, 'sort' | 'order'> & { sort: string; order: string }> = {
  // Candidat
  cibles:      { category: 'parfait',     hors_perimetre: false, sort: 'seen_candidat,fetched_at', order: 'asc,desc' },
  gaps:        { category: 'reve',        hors_perimetre: false, sort: 'seen_candidat,fetched_at', order: 'asc,desc' },
  filet:       { category: 'atteignable', hors_perimetre: false, sort: 'seen_candidat,fetched_at', order: 'asc,desc' },
  retenues:    { verdict: 'retenu', hors_perimetre: false, exclude_category: 'hors', sort: 'fetched_at', order: 'desc' },
  // Opérateur
  a_traiter:      { etat_review: 'non_relue', hors_perimetre: false, sort: 'category',   order: 'desc' },
  hors_perimetre: { hors_perimetre: true,                            sort: 'fetched_at', order: 'desc' },
  tout:           {                                                   sort: 'category',   order: 'desc' },
}

// ── Store ──────────────────────────────────────────────────────────────────

export const useOffersStore = defineStore('offers', () => {
  const config = useRuntimeConfig()

  const offers = ref<OfferRow[]>([])
  const openedOffer = ref<OfferDetail | null>(null)
  const activeView = ref<ActiveView>('a_traiter')
  const filters = ref<Filters>({ ...VIEW_PRESETS.a_traiter })
  const loading = ref(false)
  const traceCounts = ref<Record<string, number>>({})

  async function fetchTraceCounts() {
    const data = await $fetch<Record<string, number>>(`${config.public.apiBase}/traces/counts`)
    traceCounts.value = data
  }

  function hasTraces(sourceId: string): boolean {
    return (traceCounts.value[sourceId] ?? 0) > 0
  }

  async function fetchOffers() {
    loading.value = true
    try {
      const params: Record<string, string | number | boolean> = {
        sort: filters.value.sort,
        order: filters.value.order,
      }
      if (filters.value.category !== undefined) params.category = filters.value.category
      if (filters.value.exclude_category !== undefined) params.exclude_category = filters.value.exclude_category
      if (filters.value.hors_perimetre !== undefined) params.hors_perimetre = filters.value.hors_perimetre
      if (filters.value.etat_review !== undefined) params.etat_review = filters.value.etat_review
      if (filters.value.remote !== undefined) params.remote = filters.value.remote
      if (filters.value.source !== undefined) params.source = filters.value.source
      if (filters.value.verdict !== undefined) params.verdict = filters.value.verdict
      if (filters.value.seen_candidat !== undefined) params.seen_candidat = filters.value.seen_candidat
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
    if (idx !== -1) offers.value[idx]!.seen_candidat = true
  }

  async function submitCategoryReview(
    id: number,
    categorie_corrigee: string | null,
    remarque: string | null,
  ) {
    await $fetch(`${config.public.apiBase}/offers/${id}/category-review`, {
      method: 'PUT',
      body: { categorie_corrigee, remarque },
    })
    // Refresh detail + list row
    const data = await $fetch<OfferDetail>(`${config.public.apiBase}/offers/${id}`)
    openedOffer.value = data
    const idx = offers.value.findIndex(o => o.id === id)
    if (idx !== -1) {
      const row = offers.value[idx]!
      row.etat_review = data.etat_review
      row.categorie_finale = data.categorie_finale
      row.categorie_corrigee = data.categorie_corrigee
      row.categorie_suggeree = data.categorie_suggeree
      row.reviewed_at = data.reviewed_at
      row.remarque = data.remarque
    }
  }

  async function setVerdict(id: number, status: string) {
    await $fetch(`${config.public.apiBase}/offers/${id}/verdict`, {
      method: 'PUT',
      body: { status },
    })
    const idx = offers.value.findIndex(o => o.id === id)
    if (idx !== -1) {
      offers.value[idx]!.verdict = status
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
    if (idx !== -1) offers.value[idx]!.verdict = null
    if (openedOffer.value?.id === id) openedOffer.value.verdict = null
  }

  function setView(view: ActiveView) {
    activeView.value = view
    filters.value = { ...VIEW_PRESETS[view] }
    fetchOffers()
  }

  return {
    offers,
    openedOffer,
    activeView,
    filters,
    loading,
    traceCounts,
    fetchOffers,
    fetchTraceCounts,
    hasTraces,
    openDetail,
    submitCategoryReview,
    setVerdict,
    clearVerdict,
    setView,
  }
})
