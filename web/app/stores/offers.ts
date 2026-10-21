import { defineStore } from 'pinia'

// ── Types ──────────────────────────────────────────────────────────────────

export interface GesteEtat {
  geste: string
  permis: boolean
  libelle: string
  raison: string | null
}

export interface OfferRow {
  id: number
  title: string | null
  company: string | null
  location: string | null
  remote: boolean
  contract_type: string | null
  category: string | null            // parfait | reve | atteignable | hors
  verdict: string | null
  // EXE-200, critère 11 : tri et revue hors périmètre, deux axes séparés —
  // ne jamais les recombiner côté front (architecture.md, TCK-311).
  tri: string                        // a_trier | retenue | ecartee
  revue_hors_perimetre: string | null
  etape: string | null               // dérivé API, offre retenue seulement (EXE-144)
  gestes_permis: string[]
  gestes: GesteEtat[]                // chaque geste de la table, permis ou non + raison (critère 14)
  hors_perimetre_reason: string | null
  perimetre_causes: string[]
  // dérivés, offre écartée seulement (EXE-194, critères 9, 11)
  ecartee_le: string | null
  motif_ecart: string | null
  seen_candidat: boolean
  fetched_at: string
  // review humaine
  categorie_suggeree: string | null
  categorie_corrigee: string | null
  categorie_finale: string | null    // dérivé API
  etat_review: string | null         // non_relue | validee | corrigee | a_revoir
  remarque: string | null
  reviewed_at: string | null
  review_stale: boolean
  suggestion_actuelle: string | null
  expired: boolean // vérification d'expiration (EXE-76/77)
}

export interface ExpirationCheck {
  url: string
  status_code: number | null
  checked_at: string
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
  langues_requises: string[]
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
  fiche?: FicheEntreprise | null
  employer_url: string | null // EXE-76
  last_checked_at: string | null // EXE-76
  expiration_checks: ExpirationCheck[] // EXE-76
  ad_language: string | null // EXE-183 : fr | en | nl | other | null
  etapes_affichees: string[] // séquence fixe en tête d'une offre retenue (critère 15)
  etapes_acquises: string[] // sous-ensemble réellement acquis (EXE-194, critère 22)
  tout_telecharger_possible: boolean // critère 16
  tout_telecharger_raison: string | null
  // EXE-196, critères 7, 8, 10 : pièces qui partent (sans lettre : le CV
  // seul) et libellé du bouton — décidés par l'API, jamais recalculés ici.
  tout_telecharger_pieces: string[]
  tout_telecharger_libelle: string
}

export type FicheTas = 'lettre' | 'entretien' | 'rien'

export interface FichePoint {
  position: string
  citation: string | null
  url: string | null
  tas: FicheTas | null
  explication: string | null
  sujet_libelle: string | null // EXE-162, critère 23 : absent si le point n'a pas de sujet
}

export interface FicheSource {
  titre: string | null
  url: string | null
}

export interface FicheEntreprise {
  statut: 'pending' | 'done' | 'error'
  mode: 'entreprise' | 'offre_seule' | null
  presentation: string | null
  employeur_nom: string | null
  employeur_entite: string | null
  employeur_methode: string | null
  employeur_confiance: string | null
  employeur_site: string | null
  points: FichePoint[]
  manques: string[]
  alertes: string[]
  sources: FicheSource[]
  avis: string | null
  session_id: string | null
  cost_usd: number | null
  error_message: string | null
  propose_intermediaire: boolean
}

export interface CvSkillGroup {
  label: string
  items: string[]
}

export type CvStatut = 'pending' | 'done' | 'error'

export interface Cv {
  statut: CvStatut
  html: string | null
  titre: string | null
  localisation: string | null
  au_cv: string[]
  groupes: CvSkillGroup[]
  notions: string[]
  demande_sans_y_etre: string[]
  ajouts_permis: string[]
  seuil_utilise: number | null
  cost_usd: number | null
  error_message: string | null
  created_at: string
  en_html: string | null // EXE-183
  en_error_message: string | null // EXE-183
  profil: 'base' | 'claude' | null // EXE-184
  profil_motif_libelle: string | null // EXE-184
  profil_affiche: 'base' | 'claude' | null // EXE-185 : constaté sur le texte du CV
  profil_phrase: string // EXE-185
}

export type LettreStatut = 'aucune' | 'pending' | 'done' | 'error'

export interface FaitRetenu {
  position: string
  citation: string | null
  url: string | null
  tas: FicheTas | null
  explication: string | null
  sujet_libelle?: string | null
}

export interface Jugement {
  rien_a_redire: boolean
  ressenti: string
  details: string
  reussites: string
  verdict: string
}

export interface Releve {
  tournures: string[]
  lieux: { lieu: string, phrase: string }[]
  affirmations: { passage: string, manque: string }[]
}

// Étape en cours de la boucle (EXE-167, critères 2, 3) — présente seulement
// pendant une génération ou une régénération.
export interface LettreEtape {
  etape: string
  tour: number
  max_tours: number
  pourcentage: number
}

export interface Lettre {
  statut: LettreStatut
  texte: string | null
  tournures_signalees: string[]
  nb_mots: number | null
  depasse_longueur: boolean
  modele: string | null
  modele_juge: string | null // EXE-169 : toujours opus, à part du modèle choisi
  cost_usd: number | null
  error_message: string | null
  created_at: string
  regeneration_en_cours: boolean
  regeneration_error: string | null
  fait_retenu: FaitRetenu | null // EXE-162 : null = lettre générique
  texte_type_id: string | null
  nb_tours: number | null
  raison_fin: string | null
  jugement: Jugement | null
  releve: Releve | null
  faits_ecartes: FaitRetenu[]
  etape: LettreEtape | null
  angle: string | null // EXE-171 : mon angle d'accroche, remplace le choix du tamis
}

export interface LettreVersion {
  id: number // EXE-174 : identifie la version pour la demande à part des appels
  texte: string
  tournures_signalees: string[]
  nb_mots: number
  depasse_longueur: boolean
  origine: 'modele' | 'moi'
  fait_retenu: FaitRetenu | null
  created_at: string
  modele: string | null // EXE-166 : absent pour une version « moi »
  modele_juge: string | null // EXE-169 : absent pour une version « moi »
  jugement: Jugement | null // EXE-169 : absent pour une version « moi »
  nb_tours: number | null // EXE-169 : absent pour une version « moi »
  raison_fin: string | null // EXE-169 : absent pour une version « moi »
  angle_utilise: string | null // EXE-171 : angle qui a produit cette version ; absent sinon
  repartie_de_ma_lettre: boolean // EXE-173 : vraie seulement pour la version finale d'une boucle repartie d'une version « moi »
  // EXE-174, critères 1, 4, 5 : nombre et coût total des appels de la
  // génération qui a produit cette version — 0/null pour une version écrite
  // à la main ou une version d'avant ce ticket. Le détail (demande, réponse)
  // se lit à part, par `fetchLettreVersionAppels`.
  nb_appels: number
  cout_total: number | null
  trace_id: string | null // EXE-174, critère 8 : identifiant de la trace MLflow ; absent sinon
}

// EXE-174, critères 1, 6 : détail complet d'un appel de la boucle, rendu par
// `fetchLettreVersionAppels` — jamais inclus dans `LettreVersion` (critère 5).
export interface AppelTrace {
  noeud: 'tamis' | 'redaction' | 'juge' | 'verificateur'
  modele: string
  tour: number
  duree_s: number
  cout_usd: number | null
  demande: string
  reponse: string
  nb_jetons: number | null
}

export type PieceStatut = 'a_faire' | 'en_cours' | 'prete'

export interface PieceInfo {
  statut: PieceStatut
  marque_pret_le: string | null
}

// Carte Lettre (EXE-195) : statut affiché et boutons rendus par l'API — le
// front ne décide jamais lui-même si Générer / Ne pas faire / Revenir est
// visible, actif ou pourquoi (frontend.md, architecture.md).
export type LettreCarteStatut =
  | 'a_decider'
  | 'demandee'
  | 'en_generation'
  | 'generee'
  | 'prete'
  | 'sans_lettre'

export interface BoutonLettre {
  bouton: 'generer' | 'ne_pas_faire' | 'revenir'
  visible: boolean
  actif: boolean
  libelle: string
  raison: string | null
}

export interface LettreCarte {
  statut: LettreCarteStatut
  message: string | null
  boutons: BoutonLettre[]
}

export interface Pieces {
  cv: PieceInfo
  lettre: PieceInfo
  lettre_carte: LettreCarte
  prete_a_l_envoi: boolean
  envoyee_le: string | null
}

export interface MailCandidature {
  objet: string
  corps: string
  origine: 'modele' | 'moi' | null
  modele: string | null
  created_at: string | null
}

// Avancement d'une pièce (EXE-127) — distinct de PieceStatut : dit si la
// génération tourne, a fini ou a échoué, pas si la pièce est marquée Prête.
export type AvancementEtat = 'en_attente' | 'en_cours' | 'terminee' | 'en_erreur'

export interface AvancementPiece {
  etat: AvancementEtat
  raison: string | null
}

export interface Avancement {
  fiche: AvancementPiece
  cv: AvancementPiece
  lettre: AvancementPiece
  mail: AvancementPiece
}

export interface Filters {
  category?: string
  exclude_category?: string
  hors_perimetre?: boolean
  hp_cause?: string
  extraction_status?: string
  exclude_ad_language?: string
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
export type CandidateView = 'cibles' | 'gaps' | 'filet' | 'retenues' | 'ecartees'
// Opérateur (page /operateur)
export type OperatorView = 'a_traiter' | 'hors_perimetre' | 'texte_manquant' | 'tout'

export type ActiveView = CandidateView | OperatorView

const VIEW_PRESETS: Record<ActiveView, Omit<Partial<Filters>, 'sort' | 'order'> & { sort: string; order: string }> = {
  // Candidat
  cibles:      { category: 'parfait',     verdict: 'a_trier', hors_perimetre: false, exclude_ad_language: 'nl', sort: 'seen_candidat,fetched_at', order: 'asc,desc' },
  gaps:        { category: 'reve',        verdict: 'a_trier', hors_perimetre: false, exclude_ad_language: 'nl', sort: 'seen_candidat,fetched_at', order: 'asc,desc' },
  filet:       { category: 'atteignable', verdict: 'a_trier', hors_perimetre: false, exclude_ad_language: 'nl', sort: 'seen_candidat,fetched_at', order: 'asc,desc' },
  retenues:    { verdict: 'retenu', hors_perimetre: false, exclude_category: 'hors', exclude_ad_language: 'nl', sort: 'fetched_at', order: 'desc' },
  // EXE-194, critère 9 : les offres écartées, la plus récemment écartée d'abord.
  ecartees:    { verdict: 'ecartee', exclude_ad_language: 'nl', sort: 'ecartee_le', order: 'desc' },
  // Opérateur
  a_traiter:      { etat_review: 'non_relue,a_revoir', hors_perimetre: false, sort: 'category',   order: 'desc' },
  hors_perimetre: { hors_perimetre: true,                            sort: 'hors_perimetre_reason', order: 'asc' },
  texte_manquant: { extraction_status: 'missing_text',               sort: 'fetched_at', order: 'desc' },
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
  const checkingExpirations = ref(false)
  const viewProfileActive = ref(true)
  const includeRemote = ref(false)
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
      if (filters.value.hp_cause !== undefined) params.hp_cause = filters.value.hp_cause
      if (filters.value.extraction_status !== undefined) params.extraction_status = filters.value.extraction_status
      if (filters.value.exclude_ad_language !== undefined) params.exclude_ad_language = filters.value.exclude_ad_language
      if (filters.value.etat_review !== undefined) params.etat_review = filters.value.etat_review
      if (filters.value.remote !== undefined) params.remote = filters.value.remote
      if (filters.value.source !== undefined) params.source = filters.value.source
      if (filters.value.verdict !== undefined) params.verdict = filters.value.verdict
      if (filters.value.seen_candidat !== undefined) params.seen_candidat = filters.value.seen_candidat
      if (filters.value.q) params.q = filters.value.q
      if (['cibles', 'gaps', 'filet', 'retenues'].includes(activeView.value)) {
        params.view_profile = viewProfileActive.value
        if (includeRemote.value) params.include_remote = true
      }

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
      row.review_stale = data.review_stale
      row.suggestion_actuelle = data.suggestion_actuelle
    }
  }

  // Après un geste, l'étape, le tri et les gestes permis sont recalculés côté
  // API — une mise à jour optimiste locale (verdict seul) les laissait
  // périmés (H1). On relit l'offre plutôt que de deviner son nouvel état.
  async function _resyncOffer(id: number) {
    const data = await $fetch<OfferDetail>(`${config.public.apiBase}/offers/${id}`)
    if (openedOffer.value?.id === id) openedOffer.value = data
    const idx = offers.value.findIndex(o => o.id === id)
    if (idx !== -1) {
      const row = offers.value[idx]!
      row.verdict = data.verdict
      row.tri = data.tri
      row.revue_hors_perimetre = data.revue_hors_perimetre
      row.etape = data.etape
      row.gestes_permis = data.gestes_permis
      row.gestes = data.gestes
    }
  }

  async function setVerdict(id: number, status: string, motif?: string | null) {
    await $fetch(`${config.public.apiBase}/offers/${id}/verdict`, {
      method: 'PUT',
      body: { status, motif: motif ?? null },
    })
    await _resyncOffer(id)
  }

  async function clearVerdict(id: number) {
    await $fetch(`${config.public.apiBase}/offers/${id}/verdict`, { method: 'DELETE' })
    await _resyncOffer(id)
  }

  // Retire la revue hors périmètre seule, distinct de l'annulation d'un geste
  // (EXE-194, critère 17) — ne touche jamais le tri ni l'historique.
  async function retirerRevue(id: number) {
    await $fetch(`${config.public.apiBase}/offers/${id}/revue`, { method: 'DELETE' })
    await _resyncOffer(id)
  }

  // Tout geste de la table du module d'états (EXE-194, critère 10 : Remettre
  // à trier depuis une offre écartée) — motif facultatif, ignoré des gestes
  // qui ne le lisent pas côté API.
  async function appliquerGeste(id: number, geste: string, motif?: string | null) {
    await $fetch(`${config.public.apiBase}/offers/${id}/geste`, {
      method: 'POST',
      body: { geste, motif: motif ?? null },
    })
    await _resyncOffer(id)
  }

  async function checkExpirations(offerIds?: number[]) {
    checkingExpirations.value = true
    try {
      const body = offerIds !== undefined ? { offer_ids: offerIds } : undefined
      await $fetch(`${config.public.apiBase}/offers/check-expirations`, { method: 'POST', body })
      await fetchOffers()
    } finally {
      checkingExpirations.value = false
    }
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
    checkingExpirations,
    viewProfileActive,
    includeRemote,
    traceCounts,
    fetchOffers,
    fetchTraceCounts,
    hasTraces,
    openDetail,
    submitCategoryReview,
    setVerdict,
    clearVerdict,
    retirerRevue,
    appliquerGeste,
    checkExpirations,
    setView,
  }
})
