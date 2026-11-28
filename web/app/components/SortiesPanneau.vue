<template>
  <!-- Offres sorties de la file affichée (EXE-224) : motif, signe, preuve et
       date rendus par GET /a-postuler/sorties, jamais calculés ici. -->
  <div v-if="store.sortiesDeLaFile.length" class="space-y-2">
    <button
      class="px-3 py-1 rounded-md text-xs font-medium bg-gray-100 text-gray-700 hover:bg-gray-200 transition-colors"
      :aria-expanded="store.panneauSorties"
      @click="store.basculerSorties()"
    >
      Sorties ({{ store.sortiesDeLaFile.length }})
    </button>

    <ul
      v-if="store.panneauSorties"
      aria-label="Sorties"
      class="divide-y divide-gray-100 rounded-lg border border-gray-200 bg-white text-sm shadow-sm"
    >
      <li
        v-for="s in store.sortiesDeLaFile"
        :key="s.id"
        :data-offer-id="s.id"
        class="flex flex-wrap items-baseline gap-x-3 gap-y-1 px-3 py-2"
      >
        <NuxtLink :to="`/offers/${s.id}`" class="font-medium text-gray-800 hover:underline">
          {{ s.titre || '—' }}
        </NuxtLink>
        <span class="text-gray-600">{{ s.entreprise || '—' }}</span>
        <span class="text-gray-600" data-testid="raison">{{ raison(s) }}</span>
        <span v-if="jourDeBruxelles(s.verifiee_le)" class="text-xs text-gray-400">
          vérifiée le {{ jourDeBruxelles(s.verifiee_le) }}
        </span>
        <a
          :href="s.preuve"
          target="_blank"
          rel="noopener noreferrer"
          class="text-xs text-indigo-600 hover:underline"
        >
          Voir la preuve
        </a>
        <button
          class="ml-auto px-2 py-0.5 rounded text-xs font-medium bg-indigo-50 text-indigo-700 hover:bg-indigo-100"
          @click="store.remettre(s.id)"
        >
          Remettre dans la liste
        </button>
      </li>
    </ul>
  </div>
</template>

<script setup lang="ts">
import { useAPostulerStore } from '~/stores/aPostuler'
import type { SortieAPostuler } from '~/stores/aPostuler'
import { jourDeBruxelles } from '~/utils/jourDeBruxelles'

const store = useAPostulerStore()

// Libellés d'affichage des états rendus par l'API dans `meme_offre_que.etat`.
const ETATS: Record<string, string> = {
  retenue: 'retenue',
  candidature_envoyee: 'candidature envoyée',
  entretien: 'entretien',
  offre_recue: 'offre reçue',
  refusee: 'refusée',
  sans_suite: 'sans suite',
  abandonnee: 'abandonnée',
  ecartee: 'écartée',
}

// La raison mise en mots, depuis les champs rendus par l'API (H4).
function raison(s: SortieAPostuler): string {
  if (s.motif === 'annonce expirée' && s.signe) {
    const entre = [s.site, s.code].filter(v => v !== null && v !== '').join(', ')
    let texte = `${s.motif} : ${s.signe}`
    if (entre) texte += ` (${entre})`
    if (s.phrase) texte += ` « ${s.phrase} »`
    return texte
  }
  if (s.motif === 'lieu') {
    const lieu = [s.lieu_reel, s.code_postal].filter(Boolean).join(' ')
    return lieu ? `${s.motif} : ${lieu}` : s.motif
  }
  if (s.motif === 'doublon' && s.meme_offre_que) {
    return `doublon de ${s.meme_offre_que.titre}`
  }
  if (s.motif === 'déjà traitée' && s.meme_offre_que?.etat) {
    const etat = s.meme_offre_que.etat
    return `${s.motif} : ${ETATS[etat] ?? etat}`
  }
  return s.motif
}
</script>
