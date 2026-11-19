<template>
  <section v-if="carte?.disponible" class="space-y-2" aria-label="Version anglaise">
    <div class="flex items-center gap-2">
      <div
        v-if="carte.texte !== null"
        role="group"
        aria-label="Langue de la lettre"
        class="flex items-center gap-0.5 rounded-lg border border-gray-200 p-0.5 text-xs font-medium"
      >
        <button
          type="button"
          @click="emit('update:langue', 'fr')"
          :aria-pressed="langue === 'fr'"
          :class="langue === 'fr' ? 'bg-indigo-600 text-white' : 'text-gray-500 hover:bg-gray-50'"
          class="px-2 py-1 rounded"
        >FR</button>
        <button
          type="button"
          @click="emit('update:langue', 'en')"
          :aria-pressed="langue === 'en'"
          :class="langue === 'en' ? 'bg-indigo-600 text-white' : 'text-gray-500 hover:bg-gray-50'"
          class="px-2 py-1 rounded"
        >EN</button>
      </div>
      <button
        v-if="carte.bouton"
        type="button"
        @click="generer"
        :disabled="busy"
        class="text-xs px-2 py-1 rounded bg-indigo-50 text-indigo-700 hover:bg-indigo-100 disabled:opacity-50"
      >{{ carte.bouton }}</button>
      <span v-if="busy" role="status" class="flex items-center gap-1.5 text-xs text-gray-500">
        <span class="inline-block w-3 h-3 rounded-full border-2 border-indigo-200 border-t-indigo-600 animate-spin" />
        Traduction en cours…
      </span>
    </div>
    <p v-if="carte.message" class="text-xs text-amber-800 bg-amber-50 border border-amber-200 rounded px-2 py-1">{{ carte.message }}</p>
    <p v-if="erreur" class="text-xs text-red-600">{{ erreur }}</p>

    <template v-if="langue === 'en' && carte.texte !== null">
      <textarea
        v-model="texteEdit"
        aria-label="Texte anglais de la lettre"
        rows="14"
        class="w-full rounded-lg border border-gray-200 p-3 text-sm text-gray-800 leading-relaxed"
      />
      <div class="flex items-center gap-2">
        <button
          type="button"
          @click="enregistrer"
          class="px-4 py-2.5 rounded-lg bg-indigo-600 text-white text-sm font-medium hover:bg-indigo-700 transition-colors"
        >Enregistrer</button>
        <button
          type="button"
          @click="telechargerPdf"
          class="text-xs px-2 py-1 rounded bg-indigo-50 text-indigo-700 hover:bg-indigo-100"
        >Télécharger le PDF anglais</button>
      </div>
    </template>
  </section>
</template>

<script setup lang="ts">
// Version anglaise de la lettre (EXE-209) : bouton Générer / Régénérer, bascule
// FR/EN, éditeur du texte anglais et son PDF. Le libellé du bouton et la
// fraîcheur viennent de l'API (GET /lettre/en), jamais calculés ici.
interface CarteAnglaise {
  disponible: boolean
  texte: string | null
  perimee: boolean
  message: string | null
  bouton: string | null
}

const props = defineProps<{ lettreUrl: string, texteFr: string | null, langue: 'fr' | 'en' }>()
const emit = defineEmits<{ 'update:langue': [langue: 'fr' | 'en'] }>()

const carte = ref<CarteAnglaise | null>(null)
const texteEdit = ref('')
const busy = ref(false)
const erreur = ref<string | null>(null)

function poser(c: CarteAnglaise) {
  carte.value = c
  texteEdit.value = c.texte ?? ''
  if (c.texte === null && props.langue === 'en') emit('update:langue', 'fr')
}

async function detail(e: unknown): Promise<string> {
  const data = (e as { data?: unknown })?.data
  if (data instanceof Blob) {
    try {
      return (JSON.parse(await data.text()) as { detail?: string }).detail ?? 'Action impossible.'
    } catch {
      return 'Action impossible.'
    }
  }
  return (data as { detail?: string } | undefined)?.detail ?? 'Action impossible.'
}

async function charger() {
  try {
    poser(await $fetch<CarteAnglaise>(`${props.lettreUrl}/en`))
  } catch (e) {
    erreur.value = await detail(e)
  }
}

async function generer() {
  erreur.value = null
  busy.value = true
  try {
    poser(await $fetch<CarteAnglaise>(`${props.lettreUrl}/en`, { method: 'POST' }))
  } catch (e) {
    erreur.value = await detail(e)
  } finally {
    busy.value = false
  }
}

async function enregistrer() {
  erreur.value = null
  try {
    poser(await $fetch<CarteAnglaise>(`${props.lettreUrl}/en/texte`, { method: 'PUT', body: { texte: texteEdit.value } }))
  } catch (e) {
    erreur.value = await detail(e)
  }
}

async function telechargerPdf() {
  erreur.value = null
  try {
    const res = await $fetch.raw(`${props.lettreUrl}/en/pdf`, { responseType: 'blob' })
    const match = res.headers.get('content-disposition')?.match(/filename="?([^"]+)"?/)
    if (!match) {
      erreur.value = 'Le nom du fichier est manquant : téléchargement annulé.'
      return
    }
    const url = URL.createObjectURL(res._data as Blob)
    const a = document.createElement('a')
    a.href = url
    a.download = match[1]!
    a.click()
    URL.revokeObjectURL(url)
  } catch (e) {
    erreur.value = await detail(e)
  }
}

onMounted(charger)
// Le texte français a changé (enregistrement, régénération) : la fraîcheur se relit.
watch(() => props.texteFr, charger)
</script>
