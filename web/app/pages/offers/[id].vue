<template>
  <div class="h-screen overflow-hidden flex flex-col">

    <!-- En-tête fixe -->
    <header class="bg-white border-b border-gray-200 px-6 py-4 flex items-center gap-4 flex-shrink-0">
      <button
        @click="router.back()"
        class="text-gray-400 hover:text-gray-600 flex-shrink-0"
        aria-label="Retour"
      >
        <svg class="w-5 h-5" fill="none" stroke="currentColor" stroke-width="2" viewBox="0 0 24 24">
          <path stroke-linecap="round" stroke-linejoin="round" d="M15 19l-7-7 7-7"/>
        </svg>
      </button>

      <div v-if="offer" class="flex-1 min-w-0">
        <h1 class="text-base font-semibold text-gray-900 leading-snug truncate">
          {{ offer.title ?? '(sans titre)' }}
        </h1>
        <p class="text-sm text-gray-500 mt-0.5">
          {{ offer.company ?? '—' }}
        </p>
      </div>
      <div v-else class="flex-1 min-w-0">
        <div class="h-4 bg-gray-200 rounded w-64 animate-pulse mb-1.5"></div>
        <div class="h-3 bg-gray-100 rounded w-32 animate-pulse"></div>
      </div>

      <div class="flex items-center gap-3 flex-shrink-0">
        <button
          v-if="offer"
          @click="retirerDesRetenues"
          class="text-sm text-gray-400 hover:text-red-500 transition-colors"
        >
          Retirer des retenues
        </button>
        <a
          v-if="offer?.url"
          :href="offer.url"
          target="_blank"
          rel="noopener noreferrer"
          class="text-indigo-600 hover:underline font-medium text-sm"
        >
          Voir l'annonce ↗
        </a>
      </div>
    </header>

    <!-- Corps -->
    <div class="flex-1 overflow-hidden flex">

      <!-- Colonne gauche (2/3) -->
      <div class="w-2/3 flex flex-col gap-4 overflow-hidden border-r border-gray-100 p-6">
        <div v-if="!offer" class="flex items-center justify-center h-full text-gray-400 text-sm">
          Chargement…
        </div>

        <template v-if="offer">
          <!-- Frise de statut -->
          <div class="flex items-center gap-0 flex-shrink-0">
            <template v-for="(step, idx) in STEPS" :key="step">
              <div
                tabindex="-1"
                class="flex items-center gap-1.5 px-3 py-1.5 rounded-full text-xs font-medium select-none"
                :class="step === 'Retenue'
                  ? 'bg-indigo-600 text-white'
                  : 'text-gray-400'"
              >
                <span>{{ step }}</span>
              </div>
              <svg v-if="idx < STEPS.length - 1" class="w-4 h-4 text-gray-300 flex-shrink-0" fill="none" stroke="currentColor" stroke-width="2" viewBox="0 0 24 24">
                <path stroke-linecap="round" stroke-linejoin="round" d="M9 5l7 7-7 7"/>
              </svg>
            </template>
          </div>

          <!-- Synthèse d'extraction -->
          <div class="rounded-lg border border-gray-200 bg-gray-50 px-4 py-3 space-y-2 flex-shrink-0 text-xs">
            <!-- Lieu + remote + contrat + date + source -->
            <div class="flex flex-wrap gap-x-4 gap-y-1 text-gray-600">
              <span v-if="offer.remote" class="px-2 py-0.5 rounded bg-teal-50 text-teal-700 font-medium">Remote</span>
              <span v-else-if="offer.location">{{ offer.location }}</span>
              <span v-if="offer.contract_type"><span class="text-gray-400">Contrat</span> <span class="font-medium">{{ offer.contract_type }}</span></span>
              <span v-if="offer.fetched_at"><span class="text-gray-400">Ajoutée</span> {{ offer.fetched_at.slice(0, 10) }}</span>
              <span v-if="offer.source"><span class="text-gray-400">Source</span> <span class="font-medium">{{ offer.source }}</span></span>
              <span v-if="offer.categorie_finale ?? offer.category">
                <span class="text-gray-400">Catégorie</span>
                <span :class="categoryBadgeClass(offer.categorie_finale ?? offer.category)" class="ml-1 px-1.5 py-0.5 rounded border font-medium">
                  {{ categoryLabel(offer.categorie_finale ?? offer.category) }}
                </span>
              </span>
            </div>
            <!-- Faits extraits -->
            <div v-if="offer.extracted_facts" class="flex flex-wrap gap-x-4 gap-y-1 text-gray-600">
              <span v-if="offer.extracted_facts.seniority_required"><span class="text-gray-400">Séniorité</span> <span class="font-medium">{{ offer.extracted_facts.seniority_required }}</span></span>
              <span v-if="offer.extracted_facts.role_level"><span class="text-gray-400">Rôle</span> <span class="font-medium">{{ offer.extracted_facts.role_level }}</span></span>
              <span v-if="offer.extracted_facts.domain"><span class="text-gray-400">Domaine</span> <span class="font-medium">{{ offer.extracted_facts.domain }}</span></span>
            </div>
            <!-- Technos -->
            <template v-if="offer.extracted_facts && offer.extracted_facts.techs_required.length > 0">
              <div v-if="ownedTechs.length" class="flex flex-wrap items-center gap-1.5">
                <span class="text-[10px] text-gray-400 mr-0.5">Possédées</span>
                <span
                  v-for="tech in ownedTechs" :key="tech.name"
                  :class="techBadgeClass(tech.importance)"
                  class="inline-flex items-center px-2 py-0.5 rounded font-medium"
                  :title="tech.importance ?? 'importance inconnue'"
                >{{ tech.name }}</span>
              </div>
              <div v-if="missingTechs.length" class="flex flex-wrap items-center gap-1.5">
                <span class="text-[10px] text-gray-400 mr-0.5">Manquantes</span>
                <span
                  v-for="tech in missingTechs" :key="tech.name"
                  :class="techBadgeClass(tech.importance)"
                  class="inline-flex items-center px-2 py-0.5 rounded font-medium ring-1 ring-red-300"
                  :title="tech.importance ?? 'importance inconnue'"
                >{{ tech.name }}</span>
              </div>
            </template>
          </div>

          <!-- Bloc annonce -->
          <div class="flex-1 overflow-y-auto prose prose-sm prose-gray max-w-none leading-relaxed text-gray-600" v-html="renderedDescription" />
        </template>
      </div>

      <!-- Colonne droite (1/3) -->
      <div class="w-1/3 flex flex-col gap-3 p-6 bg-gray-50">
        <template v-if="offer">
          <!-- Trois cartes -->
          <div
            v-for="card in CARDS" :key="card.title"
            @click="openCard(card.title)"
            class="rounded-lg border border-gray-200 bg-white p-4 cursor-pointer hover:border-indigo-200 hover:shadow-sm transition-all flex flex-col gap-2"
          >
            <div class="flex items-center justify-between">
              <span class="text-sm font-medium text-gray-700">{{ card.title }}</span>
              <span class="text-[10px] px-2 py-0.5 rounded-full bg-gray-100 text-gray-400 font-medium">à produire</span>
            </div>
            <div class="h-10 rounded bg-gray-50 border border-dashed border-gray-200 flex items-center justify-center">
              <span class="text-xs text-gray-300 italic">Vide</span>
            </div>
          </div>

          <!-- Bouton Envoyer -->
          <div class="mt-auto pt-2">
            <button
              @click="() => {}"
              class="w-full px-4 py-2.5 rounded-lg bg-indigo-600 text-white text-sm font-medium hover:bg-indigo-700 transition-colors"
            >
              Envoyer
            </button>
          </div>
        </template>
      </div>

    </div>
  </div>

  <!-- Overlay -->
  <div
    v-if="activeCard"
    class="fixed inset-0 z-50 bg-white flex flex-col"
    @click.self="activeCard = null"
  >
    <div class="flex items-center justify-between px-6 py-4 border-b border-gray-200 flex-shrink-0">
      <h2 class="text-base font-semibold text-gray-900">{{ activeCard }}</h2>
      <button @click="activeCard = null" class="text-gray-400 hover:text-gray-600">
        <svg class="w-5 h-5" fill="none" stroke="currentColor" stroke-width="2" viewBox="0 0 24 24">
          <path stroke-linecap="round" stroke-linejoin="round" d="M6 18L18 6M6 6l12 12"/>
        </svg>
      </button>
    </div>
    <div class="flex-1 flex items-center justify-center text-sm text-gray-400 italic">
      Aucun contenu — à produire
    </div>
  </div>
</template>

<script setup lang="ts">
import DOMPurify from 'dompurify'
import { marked } from 'marked'
import type { OfferDetail, TechInfo } from '~/stores/offers'

const config = useRuntimeConfig()
const router = useRouter()
const route = useRoute()

const id = computed(() => Number(route.params.id))
const offer = ref<OfferDetail | null>(null)

onMounted(async () => {
  offer.value = await $fetch<OfferDetail>(`${config.public.apiBase}/offers/${id.value}`)
})

async function retirerDesRetenues() {
  await $fetch(`${config.public.apiBase}/offers/${id.value}/verdict`, { method: 'DELETE' })
  router.back()
}

// ── Frise ────────────────────────────────────────────────────────────────
const STEPS = ['Retenue', 'Prête à l\'envoi', 'Candidature envoyée', 'Entretien à préparer']

// ── Cartes + overlay ──────────────────────────────────────────────────────
const CARDS = [
  { title: 'Entreprise' },
  { title: 'CV' },
  { title: 'Lettre de motivation' },
]
const activeCard = ref<string | null>(null)
function openCard(title: string) { activeCard.value = title }

// ── Markdown rendering ────────────────────────────────────────────────────
const renderedDescription = computed(() =>
  offer.value?.description ? DOMPurify.sanitize(marked(offer.value.description) as string) : '',
)

// ── Tech split ────────────────────────────────────────────────────────────
const ownedTechs = computed((): TechInfo[] => {
  if (!offer.value) return []
  const names = new Set(offer.value.techs_matched ?? [])
  return (offer.value.extracted_facts?.techs_required ?? []).filter(t => names.has(t.name))
})
const missingTechs = computed((): TechInfo[] => {
  if (!offer.value) return []
  const names = new Set(offer.value.techs_missing ?? [])
  return (offer.value.extracted_facts?.techs_required ?? []).filter(t => names.has(t.name))
})

// ── Helpers ───────────────────────────────────────────────────────────────
function techBadgeClass(importance: string | null) {
  if (importance === 'core')         return 'bg-blue-100 text-blue-800'
  if (importance === 'required')     return 'bg-green-100 text-green-800'
  if (importance === 'nice_to_have') return 'bg-gray-100 text-gray-500'
  return 'bg-gray-100 text-gray-400'
}

const CATEGORY_LABELS: Record<string, string> = {
  parfait: '★ Parfait',
  reve: '◈ Rêve',
  atteignable: '✓ Atteignable',
  hors: '✗ Hors',
  hors_perimetre: '⊘ Hors-périmètre',
}

function categoryLabel(cat: string | null | undefined): string {
  return cat ? (CATEGORY_LABELS[cat] ?? cat) : '?'
}

function categoryBadgeClass(cat: string | null | undefined): string {
  if (cat === 'parfait')        return 'bg-green-50 border-green-300 text-green-700'
  if (cat === 'reve')           return 'bg-indigo-50 border-indigo-300 text-indigo-700'
  if (cat === 'atteignable')    return 'bg-amber-50 border-amber-300 text-amber-700'
  if (cat === 'hors')           return 'bg-gray-100 border-gray-400 text-gray-600'
  if (cat === 'hors_perimetre') return 'bg-slate-100 border-slate-400 text-slate-600'
  return 'bg-gray-100 border-gray-200 text-gray-500'
}
</script>
