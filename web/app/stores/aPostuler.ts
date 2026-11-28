import { defineStore } from 'pinia'

// Liste « À postuler » et file « À étudier » (EXE-211), servies par
// GET /a-postuler (EXE-210). Rang, ordre, famille, âge, nombres, filtre et tri
// sont décidés par l'API : le store envoie les choix et garde ce qu'elle rend.

export type FileAPostuler = 'principale' | 'a_etudier'
export type FamilleCle = 'ia' | 'developpeur' | 'data'
export type GroupeCle = 'trop_senior' | 'interessant'
export type TriAPostuler =
  | 'rang' | 'entreprise' | 'contrat' | 'lieu' | 'famille' | 'recuperee' | 'atteignabilite'

export interface LigneAPostuler {
  id: number
  titre: string
  entreprise: string
  lieu: string
  source: string
  url: string
  contrat: string
  recuperee: string | null
  jours: number | null
  famille: string
  origine_famille: string
  niveau: string
  marques: string[]
  atteignabilite: number
  technos_connues: string[]
  technos_absentes: string[]
  rang: number
  // Groupe de « À étudier » (EXE-221) ; null dans la file principale.
  groupe: string | null
  // Offres de même poste regroupées sous la ligne (EXE-219).
  jumelles: { id: number, source: string }[]
  // Fin du parcours de candidature et date de mise en ligne (EXE-220).
  fin_forme: string | null
  fin_adresse: string | null
  en_ligne_depuis: string | null
  verifiee_le: string | null
}

export interface NombresAPostuler {
  file_principale: number
  file_a_etudier: number
  familles: Record<string, number>
  groupes: Record<string, number>
  recentes: number
}

// Une offre que la vérification a sortie d'une file (EXE-223), telle que
// GET /a-postuler/sorties la rend : motif, signe, preuve et date viennent de l'API.
export interface SortieAPostuler {
  id: number
  titre: string
  entreprise: string
  source: string
  file: FileAPostuler
  motif: string
  signe: string | null
  site: string | null
  code: number | null
  phrase: string | null
  lieu_reel: string | null
  code_postal: string | null
  meme_offre_que: { id: number, titre: string, etat: string | null } | null
  preuve: string
  verifiee_le: string | null
}

const NOMBRES_VIDES: NombresAPostuler = {
  file_principale: 0, file_a_etudier: 0, familles: {}, groupes: {}, recentes: 0,
}

export const useAPostulerStore = defineStore('aPostuler', () => {
  const config = useRuntimeConfig()

  const file = ref<FileAPostuler>('principale')
  const famille = ref<FamilleCle | null>(null)
  const groupe = ref<GroupeCle | null>(null)
  const recentes = ref(false)
  const q = ref('')
  const colonne = ref<TriAPostuler>('rang')
  const ordre = ref<'asc' | 'desc'>('asc')
  const lignes = ref<LigneAPostuler[]>([])
  const nombres = ref<NombresAPostuler>({ ...NOMBRES_VIDES })
  // Nombre d'offres sorties des files, par motif, tel que l'API le rend.
  const horsFiles = ref<Record<string, number>>({})
  // Sorties de la vérification, dans l'ordre de l'API (EXE-224) ; le panneau
  // est fermé à l'ouverture de la page.
  const sorties = ref<SortieAPostuler[]>([])
  const panneauSorties = ref(false)
  const sortiesDeLaFile = computed(() => sorties.value.filter(s => s.file === file.value))
  const loading = ref(false)

  async function chargerSorties() {
    sorties.value = await $fetch<SortieAPostuler[]>(`${config.public.apiBase}/a-postuler/sorties`)
  }

  function basculerSorties() {
    panneauSorties.value = !panneauSorties.value
  }

  // Seul le clic sur « Remettre dans la liste » l'appelle ; liste et panneau se
  // rechargent ensuite.
  async function remettre(id: number) {
    await $fetch(`${config.public.apiBase}/offers/${id}/remise`, { method: 'POST' })
    await charger()
  }

  async function charger() {
    loading.value = true
    const sortiesLues = chargerSorties()
    try {
      const params: Record<string, string | boolean> = {
        file: file.value,
        tri: colonne.value,
        ordre: ordre.value,
      }
      if (famille.value) params.famille = famille.value
      if (groupe.value) params.groupe = groupe.value
      if (recentes.value) params.recentes = true
      if (q.value.trim()) params.q = q.value.trim()
      const data = await $fetch<{
        lignes: LigneAPostuler[]
        nombres: NombresAPostuler
        hors_files: Record<string, number>
      }>(`${config.public.apiBase}/a-postuler`, { params })
      lignes.value = data.lignes
      nombres.value = data.nombres
      horsFiles.value = data.hors_files
      await sortiesLues
    } finally {
      loading.value = false
    }
  }

  // Les boutons de famille ne valent que pour la file principale (critère 28),
  // ceux de groupe que pour « À étudier », qui s'ouvre sur « Tous » (EXE-222).
  function choisirFile(nom: FileAPostuler) {
    file.value = nom
    famille.value = null
    groupe.value = null
    charger()
  }

  function choisirGroupe(cle: GroupeCle | null) {
    groupe.value = cle
    charger()
  }

  function choisirFamille(cle: FamilleCle | null) {
    famille.value = cle
    charger()
  }

  function basculerRecentes() {
    recentes.value = !recentes.value
    charger()
  }

  function chercher(mot: string) {
    q.value = mot
    charger()
  }

  // Premier clic sur un en-tête : croissant ; reclic : sens inverse.
  function trier(cle: TriAPostuler) {
    if (colonne.value === cle) {
      ordre.value = ordre.value === 'asc' ? 'desc' : 'asc'
    } else {
      colonne.value = cle
      ordre.value = 'asc'
    }
    charger()
  }

  return {
    file, famille, groupe, recentes, q, colonne, ordre, lignes, nombres, horsFiles, loading,
    sorties, sortiesDeLaFile, panneauSorties, basculerSorties, remettre,
    charger, choisirFile, choisirFamille, choisirGroupe, basculerRecentes, chercher, trier,
  }
})
