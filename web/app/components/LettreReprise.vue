<template>
  <!-- EXE-206 : mes lettres marquées Prêtes sur d'autres offres, rendues par
       l'API dans l'ordre de leur marque (la plus récente d'abord). Choisir une
       ligne copie son texte tel quel sur la lettre de l'offre courante. -->
  <div class="w-full max-w-md rounded-lg border border-gray-200 bg-white text-left" aria-label="Mes lettres">
    <p v-if="chargement" class="px-4 py-3 text-xs text-gray-400">Chargement…</p>
    <ul v-else class="divide-y divide-gray-100">
      <li v-for="l in lettres" :key="l.offer_id">
        <button
          type="button"
          :disabled="copieEnCours"
          class="w-full px-4 py-2.5 text-left text-sm hover:bg-indigo-50 disabled:opacity-50"
          @click="copier(l.offer_id)"
        >
          <span class="font-medium text-gray-800">{{ l.entreprise ?? '—' }}</span>
          <span class="text-gray-600"> · {{ l.intitule }}</span>
          <span class="block text-xs text-gray-400">Prête le {{ dateFr(l.marque_pret_at) }}</span>
        </button>
      </li>
    </ul>
    <p v-if="erreur" class="px-4 py-2 text-xs text-red-600">{{ erreur }}</p>
  </div>
</template>

<script setup lang="ts">
import type { MaLettre } from '~/stores/offers'

const props = defineProps<{ lettreUrl: string }>()
const emit = defineEmits<{ copiee: [] }>()

const lettres = ref<MaLettre[]>([])
const chargement = ref(true)
const copieEnCours = ref(false)
const erreur = ref<string | null>(null)

function dateFr(iso: string): string {
  return new Intl.DateTimeFormat('fr-FR', { day: 'numeric', month: 'long', year: 'numeric' }).format(new Date(iso))
}

function detail(e: unknown): string {
  return (e as { data?: { detail?: string } })?.data?.detail ?? 'Action impossible.'
}

onMounted(async () => {
  try {
    lettres.value = await $fetch<MaLettre[]>(`${props.lettreUrl}/mes-lettres`)
  } catch (e) {
    erreur.value = detail(e)
  } finally {
    chargement.value = false
  }
})

async function copier(sourceOfferId: number) {
  erreur.value = null
  copieEnCours.value = true
  try {
    await $fetch(`${props.lettreUrl}/copier`, { method: 'POST', body: { source_offer_id: sourceOfferId } })
    emit('copiee')
  } catch (e) {
    erreur.value = detail(e)
  } finally {
    copieEnCours.value = false
  }
}
</script>
