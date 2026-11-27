<template>
  <div class="space-y-3">
    <!-- Les deux files (critère 5) : nombres rendus par l'API. -->
    <div class="flex flex-wrap items-center gap-2">
      <button
        v-for="f in FILES"
        :key="f.cle"
        :class="chipClass(store.file === f.cle)"
        @click="store.choisirFile(f.cle)"
      >
        {{ f.libelle }} ({{ nombreFile(f.cle) }})
      </button>
    </div>

    <!-- Une phrase par groupe de « À étudier », toutes deux sur « Tous » (EXE-222). -->
    <p v-if="store.file === 'a_etudier' && store.groupe !== 'trop_senior'" class="text-sm text-gray-600">
      Postes data et analyse, sortis de la liste principale le 25 novembre 2026. Gardés ici pour les étudier avec le chat avant de décider si la famille reste.
    </p>
    <p v-if="store.file === 'a_etudier' && store.groupe !== 'interessant'" class="text-sm text-gray-600">
      Offres que le modèle lit comme senior, sorties de la liste principale le 27 novembre 2026. Tu peux encore en retenir une depuis sa page.
    </p>

    <!-- Filtres (critères 22, 25, 26) : familles sur la file principale seule. -->
    <div class="flex flex-wrap items-center gap-2">
      <template v-if="store.file === 'principale'">
        <button :class="chipClass(store.famille === null)" @click="store.choisirFamille(null)">
          Toutes ({{ store.nombres.file_principale }})
        </button>
        <button
          v-for="f in FAMILLES_PRINCIPALE"
          :key="f.cle"
          :class="chipClass(store.famille === f.cle)"
          @click="store.choisirFamille(f.cle)"
        >
          {{ f.libelle }} ({{ store.nombres.familles[f.libelle] ?? 0 }})
        </button>
        <span class="w-px h-5 bg-gray-200 mx-1" />
      </template>
      <!-- Groupes de « À étudier » (EXE-222) : nombres rendus par l'API. -->
      <template v-else>
        <button :class="chipClass(store.groupe === null)" @click="store.choisirGroupe(null)">
          Tous ({{ store.nombres.file_a_etudier }})
        </button>
        <button
          v-for="g in GROUPES"
          :key="g.cle"
          :class="chipClass(store.groupe === g.cle)"
          @click="store.choisirGroupe(g.cle)"
        >
          {{ g.libelle }} ({{ store.nombres.groupes[g.nom] ?? 0 }})
        </button>
        <span class="w-px h-5 bg-gray-200 mx-1" />
      </template>
      <button :class="chipClass(store.recentes)" @click="store.basculerRecentes()">
        Récentes ({{ store.nombres.recentes }})
      </button>
      <form class="ml-auto" @submit.prevent="store.chercher(mot)">
        <input
          v-model="mot"
          type="search"
          aria-label="Rechercher"
          placeholder="Poste ou entreprise"
          class="px-3 py-1 rounded-md border border-gray-200 text-sm"
        />
      </form>
    </div>

    <!-- Offres sorties des files (EXE-222) : annonces expirées et doublons seuls. -->
    <p v-if="store.file === 'principale' && sorties" class="text-sm text-gray-600">
      {{ sorties }}
    </p>

    <div class="overflow-x-auto rounded-lg border border-gray-200 bg-white shadow-sm">
      <div
        v-if="store.lignes.length === 0 && !store.loading"
        class="py-16 text-center text-sm text-gray-400"
      >
        Aucune offre ici. Lance un run ou ajoute une offre.
      </div>

      <table
        v-else-if="store.lignes.length"
        aria-label="Liste à postuler"
        class="min-w-full divide-y divide-gray-100 text-sm"
      >
        <thead class="bg-gray-50 text-xs font-medium text-gray-500 uppercase tracking-wide">
          <tr>
            <th v-for="col in COLONNES" :key="col.libelle" class="px-3 py-3 text-left">
              <button
                v-if="col.cle"
                class="uppercase tracking-wide hover:text-gray-700"
                @click="store.trier(col.cle)"
              >
                {{ col.libelle }}
              </button>
              <span v-else>{{ col.libelle }}</span>
              <span v-if="col.cle && store.colonne === col.cle" class="ml-1 text-gray-400">
                {{ store.ordre === 'asc' ? '↑' : '↓' }}
              </span>
            </th>
          </tr>
        </thead>
        <tbody class="divide-y divide-gray-50">
          <tr
            v-for="ligne in store.lignes"
            :key="ligne.id"
            :data-offer-id="ligne.id"
            class="cursor-pointer text-gray-800 hover:bg-indigo-50 transition-colors"
            @click="router.push(`/offers/${ligne.id}`)"
          >
            <td class="px-3 py-3 whitespace-nowrap font-semibold text-gray-500">{{ ligne.rang }}</td>
            <td class="px-3 py-3 max-w-sm">
              <span class="block truncate font-medium" :title="ligne.titre">{{ ligne.titre || '—' }}</span>
              <span v-if="postuler(ligne)" class="block text-xs text-gray-600">Postuler : <a :href="postuler(ligne)!.href" target="_blank" rel="noopener noreferrer" class="text-indigo-600 hover:underline" @click.stop>{{ postuler(ligne)!.texte }}</a></span>
              <span v-if="ligne.jumelles.length" class="block text-xs text-gray-500">
                aussi chez {{ ligne.jumelles.map(j => j.source).join(', ') }}
              </span>
              <span v-if="ligne.technos_absentes.length" class="block text-xs text-gray-500">
                Absentes : {{ ligne.technos_absentes.join(', ') }}
              </span>
              <span v-if="ligne.marques.length" class="flex flex-wrap gap-1 mt-0.5">
                <span
                  v-for="m in ligne.marques"
                  :key="m"
                  class="text-xs px-1.5 py-0.5 rounded bg-amber-50 text-amber-700"
                >
                  {{ m }}
                </span>
              </span>
            </td>
            <td class="px-3 py-3 whitespace-nowrap">{{ ligne.entreprise || '—' }}</td>
            <td class="px-3 py-3 whitespace-nowrap text-gray-500">{{ ligne.contrat || '—' }}</td>
            <td class="px-3 py-3 whitespace-nowrap text-gray-500">{{ ligne.lieu || '—' }}</td>
            <td class="px-3 py-3 whitespace-nowrap">
              {{ ligne.famille }}
              <span v-if="ligne.groupe" class="block text-xs text-gray-500">{{ ligne.groupe }}</span>
            </td>
            <td class="px-3 py-3 whitespace-nowrap text-gray-500">{{ NIVEAUX[ligne.niveau] ?? ligne.niveau }}</td>
            <td class="px-3 py-3 whitespace-nowrap text-gray-400 text-xs">
              {{ age(ligne.jours) }}
              <span v-if="dateJJMMAAAA(ligne.en_ligne_depuis)" class="block">
                en ligne depuis le {{ dateJJMMAAAA(ligne.en_ligne_depuis) }}
              </span>
            </td>
            <td class="px-3 py-3 whitespace-nowrap text-gray-600" data-testid="atteignabilite">{{ Math.round(ligne.atteignabilite) }}</td>
          </tr>
        </tbody>
      </table>

      <div v-if="store.loading" class="py-8 text-center text-sm text-gray-400 animate-pulse">
        Chargement…
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { useAPostulerStore } from '~/stores/aPostuler'
import type {
  FamilleCle, FileAPostuler, GroupeCle, LigneAPostuler, TriAPostuler,
} from '~/stores/aPostuler'

const store = useAPostulerStore()
const router = useRouter()
const mot = ref(store.q)

const FILES: { cle: FileAPostuler, libelle: string }[] = [
  { cle: 'principale', libelle: 'À postuler' },
  { cle: 'a_etudier', libelle: 'À étudier' },
]

// Libellés tels que l'API les rend dans `nombres.familles` (EXE-210).
const FAMILLES_PRINCIPALE: { cle: FamilleCle, libelle: string }[] = [
  { cle: 'ia', libelle: 'IA et automatisation' },
  { cle: 'developpeur', libelle: 'Développeur' },
]

// `nom` : le groupe tel que l'API le rend dans `nombres.groupes` (EXE-221).
const GROUPES: { cle: GroupeCle, libelle: string, nom: string }[] = [
  { cle: 'trop_senior', libelle: 'Trop senior ?', nom: 'trop senior ?' },
  { cle: 'interessant', libelle: 'Est-ce intéressant ?', nom: 'est-ce intéressant ?' },
]

const COLONNES: { libelle: string, cle: TriAPostuler | null }[] = [
  { libelle: 'Rang', cle: 'rang' },
  { libelle: 'Poste', cle: null },
  { libelle: 'Entreprise', cle: 'entreprise' },
  { libelle: 'Contrat', cle: 'contrat' },
  { libelle: 'Lieu', cle: 'lieu' },
  { libelle: 'Famille', cle: 'famille' },
  { libelle: 'Niveau', cle: null },
  { libelle: 'Récupérée', cle: 'recuperee' },
  { libelle: 'Atteignabilité', cle: 'atteignabilite' },
]

const NIVEAUX: Record<string, string> = {
  junior: 'junior',
  intermediate: 'intermédiaire',
  senior: 'senior',
}

function nombreFile(cle: FileAPostuler): number {
  return cle === 'principale' ? store.nombres.file_principale : store.nombres.file_a_etudier
}

// Libellé de l'âge rendu par l'API en jours entiers.
function age(jours: number | null): string {
  if (jours === null) return '—'
  if (jours === 0) return 'aujourd\'hui'
  return jours === 1 ? 'il y a 1 jour' : `il y a ${jours} jours`
}

// Le lien où postuler, tiré de la fin du parcours rendue par l'API (EXE-222).
// Seul le nom de site se tire de l'adresse, sans « www. ».
function postuler(ligne: LigneAPostuler): { href: string, texte: string } | null {
  const adresse = ligne.fin_adresse
  if (!adresse) return null
  if (ligne.fin_forme === 'mail') return { href: `mailto:${adresse}`, texte: adresse }
  if (ligne.fin_forme === 'formulaire') return { href: adresse, texte: 'formulaire EDITx' }
  if (ligne.fin_forme !== 'page' && ligne.fin_forme !== 'accueil') return null
  try {
    return { href: adresse, texte: new URL(adresse).hostname.replace(/^www\./, '') }
  } catch {
    return null
  }
}

// AAAA-MM-JJ rendu par l'API, affiché JJ/MM/AAAA ; rien si la date manque.
function dateJJMMAAAA(iso: string | null): string {
  const m = iso?.match(/^(\d{4})-(\d{2})-(\d{2})/)
  return m ? `${m[3]}/${m[2]}/${m[1]}` : ''
}

// Les sorties comptées par l'API, pour les motifs « annonce expirée » et
// « doublon » seulement : les autres comptent des milliers d'offres hors zone.
const sorties = computed(() => {
  const expirees = store.horsFiles['annonce expirée'] ?? 0
  const doublons = store.horsFiles['doublon'] ?? 0
  const parties: string[] = []
  if (expirees) parties.push(`${expirees} annonce${expirees > 1 ? 's' : ''} expirée${expirees > 1 ? 's' : ''}`)
  if (doublons) parties.push(`${doublons} doublon${doublons > 1 ? 's' : ''}`)
  return parties.length ? `Sorties de la liste : ${parties.join(', ')}` : ''
})

function chipClass(actif: boolean): string[] {
  return [
    'px-3 py-1 rounded-full text-xs font-medium transition-colors',
    actif ? 'bg-indigo-600 text-white' : 'bg-gray-100 text-gray-600 hover:bg-gray-200',
  ]
}
</script>
