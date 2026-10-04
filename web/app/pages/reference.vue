<template>
  <div class="min-h-screen bg-gray-50 flex flex-col">
    <header class="bg-white border-b border-gray-200 px-6 py-3 flex items-center gap-4 sticky top-0 z-10 shadow-sm">
      <NuxtLink to="/operateur" class="text-gray-400 hover:text-gray-600 text-sm">← Opérateur</NuxtLink>
      <span class="text-sm font-semibold text-gray-800 tracking-tight">Relecture du jeu de référence</span>
      <span class="ml-auto text-xs text-gray-400">{{ relues }} relue{{ relues !== 1 ? 's' : '' }} sur {{ total }}</span>
    </header>

    <div class="flex-1 flex overflow-hidden">
      <!-- Liste des offres du jeu -->
      <aside class="w-80 border-r border-gray-200 bg-white overflow-y-auto">
        <button
          v-for="e in entries" :key="e.id"
          @click="select(e.id)"
          class="w-full text-left px-4 py-3 border-b border-gray-100 flex items-center gap-2 text-sm"
          :class="selectedId === e.id ? 'bg-indigo-50' : 'hover:bg-gray-50'"
        >
          <span class="flex-1 truncate">{{ e.title }}</span>
          <span v-if="e.relu" class="text-green-600 text-xs shrink-0">relue</span>
          <span v-else class="text-gray-300 text-xs shrink-0">à relire</span>
        </button>
        <p v-if="!entries.length" class="p-4 text-sm text-gray-400 italic">Jeu vide.</p>
      </aside>

      <!-- Détail : texte à gauche, formulaire à droite -->
      <main v-if="detail" class="flex-1 flex overflow-hidden">
        <div class="w-1/2 overflow-y-auto p-6 whitespace-pre-wrap text-sm text-gray-700 border-r border-gray-100">
          <h2 class="text-base font-semibold text-gray-900 mb-3">{{ detail.title }}</h2>
          {{ detail.text }}
        </div>

        <form class="w-1/2 overflow-y-auto p-6 space-y-5" @submit.prevent>
          <div>
            <label class="block text-xs font-medium text-gray-500 mb-1">Séniorité</label>
            <select v-model="form.seniority_required" class="w-full border border-gray-200 rounded px-2 py-1.5 text-sm">
              <option v-for="s in SENIORITY" :key="s" :value="s">{{ s }}</option>
            </select>
          </div>

          <div>
            <label class="block text-xs font-medium text-gray-500 mb-1">Rôle</label>
            <select v-model="form.role_level" class="w-full border border-gray-200 rounded px-2 py-1.5 text-sm">
              <option v-for="r in ROLES" :key="r" :value="r">{{ r }}</option>
            </select>
          </div>

          <div>
            <label class="block text-xs font-medium text-gray-500 mb-1">Domaine</label>
            <select v-model="form.domain" class="w-full border border-gray-200 rounded px-2 py-1.5 text-sm">
              <option v-for="d in DOMAINS" :key="d" :value="d">{{ d }}</option>
            </select>
          </div>

          <div>
            <div class="flex items-center justify-between mb-1">
              <label class="text-xs font-medium text-gray-500">Technos</label>
              <button type="button" @click="addTech" class="text-xs text-indigo-600 hover:underline">+ techno</button>
            </div>
            <div v-for="(t, i) in form.techs_required" :key="i" class="flex items-center gap-2 mb-1.5">
              <input v-model="t.name" class="flex-1 border border-gray-200 rounded px-2 py-1 text-sm" />
              <select v-model="t.importance" class="border border-gray-200 rounded px-2 py-1 text-sm">
                <option v-for="imp in IMPORTANCES" :key="imp" :value="imp">{{ imp }}</option>
              </select>
              <button type="button" @click="removeTech(i)" class="text-xs text-gray-400 hover:text-red-500">retirer</button>
            </div>
          </div>

          <div>
            <div class="flex items-center justify-between mb-1">
              <label class="text-xs font-medium text-gray-500">Langues</label>
              <button type="button" @click="addLangue" class="text-xs text-indigo-600 hover:underline">+ langue</button>
            </div>
            <div v-for="(l, i) in form.langues_requises" :key="i" class="flex items-center gap-2 mb-1.5">
              <input v-model="form.langues_requises[i]" class="flex-1 border border-gray-200 rounded px-2 py-1 text-sm" />
              <button type="button" @click="removeLangue(i)" class="text-xs text-gray-400 hover:text-red-500">retirer</button>
            </div>
          </div>

          <p v-if="saveError" class="text-sm text-red-600">{{ saveError }}</p>

          <button
            type="button"
            @click="enregistrerRelu"
            :disabled="saving"
            class="px-4 py-2 rounded-lg bg-indigo-600 text-white text-sm font-medium hover:bg-indigo-700 disabled:opacity-50"
          >
            {{ saving ? 'Enregistrement…' : 'Enregistrer comme relu' }}
          </button>
        </form>
      </main>
      <div v-else class="flex-1 flex items-center justify-center text-sm text-gray-400">
        Choisis une offre à relire.
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import type { ExtractedFacts, TechInfo } from '~/stores/offers'

// Même vocabulaire que l'extraction (orchestrator/job_search/sources/base.py et
// scoring/extractor.py:_DOMAIN_VALID) — dupliqué côté front comme les autres
// vocabulaires fermés de l'opérateur (CATEGORY_LABELS, TAS…), pas d'API dédiée
// à cette liste.
const SENIORITY = ['junior', 'intermediate', 'senior', 'lead']
const ROLES = ['ic', 'lead', 'manager']
const IMPORTANCES = ['core', 'required', 'nice_to_have']
const DOMAINS = [
  'ai_engineering', 'data_engineering', 'data_science',
  'backend', 'devops', 'fullstack', 'embedded', 'other',
]

interface ReferenceSummary {
  id: number
  title: string
  relu: boolean
}

interface ReferenceEntryDetail {
  title: string
  text: string
  attendu: ExtractedFacts
}

const config = useRuntimeConfig()

const entries = ref<ReferenceSummary[]>([])
const relues = ref(0)
const total = ref(0)
const selectedId = ref<number | null>(null)
const detail = ref<ReferenceEntryDetail | null>(null)
const form = ref<ExtractedFacts>({
  seniority_required: 'intermediate',
  techs_required: [],
  domain: 'other',
  role_level: 'ic',
  langues_requises: [],
  parse_failed: false,
})
const saving = ref(false)
const saveError = ref<string | null>(null)

onMounted(chargerListe)

async function chargerListe() {
  const body = await $fetch<{ entries: ReferenceSummary[], relues: number, total: number }>(
    `${config.public.apiBase}/reference`,
  )
  entries.value = body.entries
  relues.value = body.relues
  total.value = body.total
}

async function select(id: number) {
  selectedId.value = id
  saveError.value = null
  detail.value = await $fetch<ReferenceEntryDetail>(`${config.public.apiBase}/reference/${id}`)
  form.value = {
    seniority_required: detail.value.attendu.seniority_required,
    techs_required: detail.value.attendu.techs_required.map((t: TechInfo) => ({ ...t })),
    domain: detail.value.attendu.domain,
    role_level: detail.value.attendu.role_level ?? 'ic',
    langues_requises: [...detail.value.attendu.langues_requises],
    parse_failed: detail.value.attendu.parse_failed,
  }
}

function addTech() {
  form.value.techs_required.push({ name: '', importance: 'required' })
}
function removeTech(i: number) {
  form.value.techs_required.splice(i, 1)
}
function addLangue() {
  form.value.langues_requises.push('')
}
function removeLangue(i: number) {
  form.value.langues_requises.splice(i, 1)
}

function nextNonRelu(apresId: number): number | null {
  const idx = entries.value.findIndex(e => e.id === apresId)
  if (idx === -1) return null
  for (let i = idx + 1; i < entries.value.length; i++) {
    if (!entries.value[i].relu) return entries.value[i].id
  }
  for (let i = 0; i < idx; i++) {
    if (!entries.value[i].relu) return entries.value[i].id
  }
  return null
}

async function enregistrerRelu() {
  if (selectedId.value === null) return
  saving.value = true
  saveError.value = null
  try {
    await $fetch(`${config.public.apiBase}/reference/${selectedId.value}`, {
      method: 'PUT',
      body: { attendu: form.value, relu: true },
    })
    const courant = selectedId.value
    await chargerListe()
    const suivant = nextNonRelu(courant)
    if (suivant !== null) await select(suivant)
    else { selectedId.value = null; detail.value = null }
  } catch {
    saveError.value = 'Enregistrement impossible — vérifie les valeurs choisies.'
  } finally {
    saving.value = false
  }
}
</script>
