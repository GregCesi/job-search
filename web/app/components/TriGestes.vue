<template>
  <div v-if="gestesTri.length || libelleTri" class="flex items-center gap-2 flex-wrap flex-shrink-0 text-xs">
    <span v-if="libelleTri" class="px-2 py-0.5 rounded-full bg-gray-100 text-gray-600 font-medium">{{ libelleTri }}</span>
    <button
      v-for="g in gestesTri"
      :key="g.geste"
      :disabled="busy"
      class="px-3 py-1.5 rounded-lg font-medium border bg-white border-gray-200 text-gray-600 hover:border-gray-300 hover:bg-gray-50 transition-all disabled:opacity-40"
      @click="appliquer(g.geste)"
    >
      {{ g.libelle }}
    </button>
    <p v-if="erreur" class="text-red-600 w-full">{{ erreur }}</p>
  </div>
</template>

<script setup lang="ts">
import { useOffersStore } from '~/stores/offers'
import type { OfferDetail } from '~/stores/offers'

// EXE-205 : boutons de tri de la page d'une offre. Visibilité et libellé
// viennent des gestes rendus par l'API pour l'offre (architecture.md, « Suivi
// des candidatures ») — un geste de tri non permis n'est pas affiché.
const props = defineProps<{ offer: OfferDetail }>()
const emit = defineEmits<{ applique: [] }>()

const store = useOffersStore()
const GESTES_TRI = ['retenir', 'ecarter', 'remettre_a_trier']

const gestesTri = computed(
  () => props.offer.gestes.filter(g => GESTES_TRI.includes(g.geste) && g.permis),
)
// Libellé d'affichage du tri, comme VerdictBadge : une offre à trier ou
// retenue n'en porte pas ici (la frise montre la retenue).
const LIBELLE_TRI: Record<string, string> = { ecartee: 'Écartée' }
const libelleTri = computed(() => LIBELLE_TRI[props.offer.tri] ?? null)

const busy = ref(false)
const erreur = ref<string | null>(null)

async function appliquer(geste: string) {
  erreur.value = null
  busy.value = true
  try {
    await store.appliquerGeste(props.offer.id, geste)
    emit('applique')
  } catch (e) {
    erreur.value = (e as { data?: { detail?: string } })?.data?.detail ?? 'Action impossible.'
  } finally {
    busy.value = false
  }
}
</script>
