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
  seen: boolean
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
  description: string | null
  url: string | null
  source: string
  extracted_facts: ExtractedFacts | null
}

export interface Filters {
  category?: string
  hors_perimetre?: boolean
  etat_review?: string
  remote?: boolean
  source?: string
  verdict?: string
  seen?: boolean
  q?: string
  sort: string
  order: 'asc' | 'desc'
}

export type ActiveView = 'a_traiter' | 'a_relire' | 'favoris' | 'hors_perimetre' | 'tout'

const VIEW_PRESETS: Record<ActiveView, Omit<Partial<Filters>, 'sort' | 'order'> & { sort: string; order: 'asc' | 'desc' }> = {
  a_traiter:      { etat_review: 'non_relue', hors_perimetre: false, sort: 'category',   order: 'desc' },
  a_relire:       { hors_perimetre: false,                           sort: 'category',   order: 'desc' },
  favoris:        { verdict: 'favori',                               sort: 'fetched_at', order: 'desc' },
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
  const profileSkills = ref<Set<string>>(new Set())

  async function fetchProfileSkills() {
    const data = await $fetch<string[]>(`${config.public.apiBase}/profile/skills`)
    profileSkills.value = new Set(data.map(s => s.toLowerCase()))
  }

  async function fetchOffers() {
    loading.value = true
    try {
      const params: Record<string, string | number | boolean> = {
        sort: filters.value.sort,
        order: filters.value.order,
      }
      if (filters.value.category !== undefined) params.category = filters.value.category
      if (filters.value.hors_perimetre !== undefined) params.hors_perimetre = filters.value.hors_perimetre
      if (filters.value.etat_review !== undefined) params.etat_review = filters.value.etat_review
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
    if (idx !== -1) offers.value[idx]!.seen = true
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
    profileSkills,
    fetchOffers,
    fetchProfileSkills,
    openDetail,
    submitCategoryReview,
    setVerdict,
    clearVerdict,
    setView,
  }
})
