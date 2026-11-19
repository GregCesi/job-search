<template>
  <div
    v-if="anglaise"
    role="group"
    aria-label="Langue de l'aperçu"
    class="flex items-center gap-0.5 rounded-lg border border-gray-200 p-0.5 text-xs font-medium"
  >
    <button
      type="button"
      @click="choisir('fr')"
      :aria-pressed="langue === 'fr'"
      :class="langue === 'fr' ? 'bg-indigo-600 text-white' : 'text-gray-500 hover:bg-gray-50'"
      class="px-2 py-1 rounded"
    >FR</button>
    <button
      type="button"
      @click="choisir('en')"
      :aria-pressed="langue === 'en'"
      :class="langue === 'en' ? 'bg-indigo-600 text-white' : 'text-gray-500 hover:bg-gray-50'"
      class="px-2 py-1 rounded"
    >EN</button>
  </div>
</template>

<script setup lang="ts">
// Bascule FR/EN de l'aperçu plein écran de la lettre (EXE-209, critère 8) :
// en EN, rend la mise en page anglaise servie par l'API ; en FR, `null`
// (l'aperçu reprend la page française).
const props = defineProps<{ lettreUrl: string }>()
const emit = defineEmits<{ html: [html: string | null] }>()

const anglaise = ref(false)
const langue = ref<'fr' | 'en'>('fr')

async function choisir(l: 'fr' | 'en') {
  langue.value = l
  if (l === 'fr') {
    emit('html', null)
    return
  }
  try {
    emit('html', await $fetch<string>(`${props.lettreUrl}/en/mise-en-page`, { responseType: 'text' }))
  } catch {
    langue.value = 'fr'
    emit('html', null)
  }
}

onMounted(async () => {
  emit('html', null)
  try {
    const carte = await $fetch<{ texte: string | null }>(`${props.lettreUrl}/en`)
    anglaise.value = carte.texte !== null
  } catch {
    anglaise.value = false
  }
})
</script>
