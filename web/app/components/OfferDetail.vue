<template>
  <Teleport to="body">
    <div class="fixed inset-0 z-40 flex justify-end" @click.self="$emit('close')">
      <div
        class="relative w-full max-w-xl bg-white shadow-2xl flex flex-col h-full overflow-hidden"
        @click.stop
      >
        <!-- Header -->
        <div class="flex items-start justify-between px-6 py-4 border-b border-gray-100">
          <div class="flex-1 min-w-0 pr-4">
            <h2 class="text-base font-semibold text-gray-900 leading-snug">
              {{ offer.title ?? '(sans titre)' }}
            </h2>
            <p class="text-sm text-gray-500 mt-0.5">
              {{ offer.company ?? '—' }}
              <span v-if="offer.location || offer.remote" class="before:content-['·'] before:mx-1">
                <span v-if="offer.remote" class="text-teal-600 font-medium">Remote</span>
                <span v-else>{{ offer.location }}</span>
              </span>
            </p>
          </div>
          <button @click="$emit('close')" class="text-gray-400 hover:text-gray-600 flex-shrink-0 mt-0.5">
            <svg class="w-5 h-5" fill="none" stroke="currentColor" stroke-width="2" viewBox="0 0 24 24">
              <path stroke-linecap="round" stroke-linejoin="round" d="M6 18L18 6M6 6l12 12"/>
            </svg>
          </button>
        </div>

        <!-- Meta bar -->
        <div class="flex items-center gap-3 px-6 py-3 bg-gray-50 border-b border-gray-100 text-xs text-gray-500 flex-wrap">
          <span v-if="props.mode === 'operateur'" :class="etatClass" class="px-2 py-0.5 rounded font-semibold">{{ etatLabel }}</span>
          <span>{{ offer.contract_type ?? '—' }}</span>
          <span>{{ offer.fetched_at?.slice(0, 10) }}</span>
          <VerdictBadge :verdict="offer.verdict" />
          <div class="ml-auto flex items-center gap-3">
            <NuxtLink
              v-if="store.hasTraces(offer.source_id)"
              :to="'/traces#offer-' + offer.source_id"
              class="text-indigo-600 hover:underline font-medium"
            >
              Voir la trace
            </NuxtLink>
            <span
              v-else
              class="text-gray-300 cursor-not-allowed"
              title="Aucune trace pour cette offre"
            >
              Voir la trace
            </span>
            <a v-if="offer.url" :href="offer.url" target="_blank" rel="noopener noreferrer"
               class="text-indigo-600 hover:underline font-medium">
              Voir l'annonce ↗
            </a>
          </div>
        </div>

        <!-- Body -->
        <div class="flex-1 overflow-y-auto px-6 py-4 space-y-6 text-sm text-gray-700">

          <!-- Review de catégorie — opérateur uniquement -->
          <section v-if="props.mode === 'operateur'">
            <h3 class="text-xs font-semibold text-gray-400 uppercase tracking-wide mb-3">Catégorie</h3>
            <div class="flex flex-wrap gap-2">
              <button
                v-for="cat in CATEGORIES" :key="cat.value"
                :class="[
                  'px-3 py-1.5 rounded-lg text-xs font-medium border transition-all',
                  selectedCategory === cat.value
                    ? cat.activeClass
                    : 'bg-white border-gray-200 text-gray-600 hover:border-gray-300 hover:bg-gray-50',
                ]"
                @click="selectCategory(cat.value)"
              >
                {{ cat.label }}
                <span v-if="suggestedCategory === cat.value && offer.etat_review === 'non_relue'"
                      class="ml-1 text-[10px] opacity-60">(suggestion)</span>
              </button>
            </div>
            <!-- Remarque -->
            <textarea
              v-model="remarque"
              placeholder="Remarque (optionnelle)"
              rows="2"
              class="mt-3 w-full rounded border border-gray-200 px-2 py-1.5 text-xs text-gray-600 placeholder-gray-300 focus:outline-none focus:border-indigo-300 resize-none"
            />
            <!-- Submit -->
            <div class="flex items-center justify-between mt-2">
              <span v-if="offer.reviewed_at" class="text-[10px] text-gray-400">
                Relue {{ offer.reviewed_at.slice(0, 16).replace('T', ' ') }}
              </span>
              <span v-else class="text-[10px] text-gray-300">Non relue</span>
              <button
                @click="handleReview"
                :disabled="saving"
                :class="[
                  'px-3 py-1 rounded text-xs font-medium transition-all',
                  saved
                    ? 'bg-green-50 border border-green-200 text-green-700'
                    : 'bg-indigo-600 text-white hover:bg-indigo-700 disabled:opacity-50',
                ]"
              >
                {{ saved ? '✓ Enregistré' : saving ? '…' : selectedCategory === suggestedCategory ? 'Valider' : 'Corriger' }}
              </button>
            </div>
          </section>

          <!-- Verdicts -->
          <section>
            <h3 class="text-xs font-semibold text-gray-400 uppercase tracking-wide mb-3">Verdict</h3>
            <div class="flex flex-wrap gap-2">
              <button
                v-for="v in displayedVerdicts" :key="v.status"
                :class="[
                  'px-3 py-1.5 rounded-lg text-xs font-medium border transition-all',
                  offer.verdict === v.status
                    ? v.activeClass
                    : 'bg-white border-gray-200 text-gray-600 hover:border-gray-300 hover:bg-gray-50',
                ]"
                @click="toggleVerdict(v.status)"
              >
                {{ v.label }}
              </button>
              <button
                v-if="offer.verdict"
                class="px-3 py-1.5 rounded-lg text-xs font-medium border border-dashed border-gray-300 text-gray-400 hover:bg-gray-50 transition-all"
                @click="store.clearVerdict(offer.id)"
              >
                Retirer
              </button>
            </div>
          </section>

          <!-- Hors-périmètre banner -->
          <section v-if="offer.hors_perimetre_reason">
            <div :class="offer.hors_perimetre_reason === 'no_tech' ? 'bg-orange-50 border-orange-200' : 'bg-slate-50 border-slate-200'"
                 class="rounded-lg border px-4 py-3">
              <p class="text-sm font-medium" :class="offer.hors_perimetre_reason === 'no_tech' ? 'text-orange-700' : 'text-slate-600'">
                {{ offer.hors_perimetre_reason === 'no_tech' ? '⊘ Aucune techno exigée' : '⊘ Rôle managérial' }}
              </p>
              <p class="text-xs mt-1" :class="offer.hors_perimetre_reason === 'no_tech' ? 'text-orange-500' : 'text-slate-400'">
                {{ offer.hors_perimetre_reason === 'no_tech'
                  ? 'Offre sans techno requise — possible bug d\'extraction. À inspecter.'
                  : 'Poste manager — pas de valeur d\'apprentissage technique.' }}
              </p>
            </div>
          </section>

          <!-- Faits extraits + badges techs (L7) -->
          <section v-if="offer.extracted_facts">
            <h3 class="text-xs font-semibold text-gray-400 uppercase tracking-wide mb-3">Faits extraits</h3>
            <div class="rounded-lg border border-gray-100 bg-gray-50 px-4 py-3 space-y-2">
              <!-- Domain + Role + Seniority -->
              <div class="flex flex-wrap gap-x-4 gap-y-1 text-xs">
                <span><span class="text-gray-400">Domaine</span> <span class="font-medium text-gray-700">{{ offer.extracted_facts.domain }}</span></span>
                <span v-if="offer.extracted_facts.role_level"><span class="text-gray-400">Rôle</span> <span class="font-medium text-gray-700">{{ offer.extracted_facts.role_level }}</span></span>
                <span><span class="text-gray-400">Séniorité</span> <span class="font-medium text-gray-700">{{ offer.extracted_facts.seniority_required }}</span></span>
              </div>
              <!-- Tech badges — split by profile ownership -->
              <template v-if="offer.extracted_facts.techs_required.length > 0">
                <div v-if="ownedTechs.length" class="flex flex-wrap items-center gap-1.5 mt-1">
                  <span class="text-[10px] text-gray-400 mr-0.5">Possédées</span>
                  <span
                    v-for="tech in ownedTechs" :key="tech.name"
                    :class="techBadgeClass(tech.importance)"
                    class="inline-flex items-center px-2 py-0.5 rounded text-xs font-medium"
                    :title="tech.importance ?? 'importance inconnue'"
                  >
                    {{ tech.name }}
                  </span>
                </div>
                <div v-if="missingTechs.length" class="flex flex-wrap items-center gap-1.5 mt-1">
                  <span class="text-[10px] text-gray-400 mr-0.5">Manquantes</span>
                  <span
                    v-for="tech in missingTechs" :key="tech.name"
                    :class="techBadgeClass(tech.importance)"
                    class="inline-flex items-center px-2 py-0.5 rounded text-xs font-medium ring-1 ring-red-300"
                    :title="tech.importance ?? 'importance inconnue'"
                  >
                    {{ tech.name }}
                  </span>
                </div>
              </template>
              <p v-else class="text-xs text-orange-500 italic">Aucune techno exigée</p>
            </div>
          </section>

          <!-- Description (Markdown rendu) -->
          <section v-if="offer.description">
            <h3 class="text-xs font-semibold text-gray-400 uppercase tracking-wide mb-2">Description</h3>
            <div class="prose prose-sm prose-gray max-w-none leading-relaxed text-gray-600" v-html="renderedDescription" />
          </section>
        </div>
      </div>
    </div>
  </Teleport>
</template>

<script setup lang="ts">
import DOMPurify from 'dompurify'
import { marked } from 'marked'
import { useOffersStore } from '~/stores/offers'
import type { OfferDetail } from '~/stores/offers'

const props = withDefaults(defineProps<{ offer: OfferDetail; mode?: 'candidat' | 'operateur' }>(), { mode: 'candidat' })
defineEmits<{ close: [] }>()

const store = useOffersStore()

// ── Markdown rendering ──────────────────────────────────────────────────
const renderedDescription = computed(() =>
  props.offer.description ? DOMPurify.sanitize(marked(props.offer.description) as string) : '',
)

// ── Tech split — source unique : back (techs_matched/techs_missing) ─────
const ownedTechs = computed(() => {
  const names = new Set(props.offer.techs_matched ?? [])
  return (props.offer.extracted_facts?.techs_required ?? []).filter(t => names.has(t.name))
})
const missingTechs = computed(() => {
  const names = new Set(props.offer.techs_missing ?? [])
  return (props.offer.extracted_facts?.techs_required ?? []).filter(t => names.has(t.name))
})

// ── Review state ─────────────────────────────────────────────────────────
const CATEGORIES = [
  { value: 'parfait',        label: '★ Parfait',        activeClass: 'bg-green-50 border-green-300 text-green-700' },
  { value: 'reve',           label: '◈ Rêve',           activeClass: 'bg-indigo-50 border-indigo-300 text-indigo-700' },
  { value: 'atteignable',    label: '✓ Atteignable',    activeClass: 'bg-amber-50 border-amber-300 text-amber-700' },
  { value: 'hors',           label: '✗ Hors',           activeClass: 'bg-gray-100 border-gray-400 text-gray-600' },
  { value: 'hors_perimetre', label: '⊘ Hors-périmètre', activeClass: 'bg-slate-100 border-slate-400 text-slate-600' },
]

const suggestedCategory = computed(() => {
  if (props.offer.hors_perimetre_reason) return 'hors_perimetre'
  return props.offer.category
})

const selectedCategory = ref<string | null>(null)
const remarque = ref('')
const saving = ref(false)
const saved = ref(false)

// Init / re-init on offer change
watch(
  () => props.offer.id,
  () => {
    selectedCategory.value = props.offer.categorie_finale ?? suggestedCategory.value
    remarque.value = props.offer.remarque ?? ''
    saved.value = false
  },
  { immediate: true },
)

function selectCategory(value: string) {
  selectedCategory.value = value
  saved.value = false
}

async function handleReview() {
  if (!selectedCategory.value) return
  saving.value = true
  saved.value = false
  try {
    const corrigee = selectedCategory.value === suggestedCategory.value
      ? null  // validation = pas de correction
      : selectedCategory.value
    await store.submitCategoryReview(
      props.offer.id,
      corrigee,
      remarque.value || null,
    )
    saved.value = true
    setTimeout(() => { saved.value = false }, 2000)
  } finally {
    saving.value = false
  }
}

// ── Verdicts ─────────────────────────────────────────────────────────────
const VERDICTS = [
  { status: 'retenu',    label: '★ Retenu',     activeClass: 'bg-blue-50 border-blue-300 text-blue-700' },
  { status: 'candidaté', label: '✓ Candidaté',  activeClass: 'bg-purple-50 border-purple-300 text-purple-700' },
  { status: 'rejeté',    label: '✗ Rejeté',     activeClass: 'bg-red-50 border-red-300 text-red-700' },
  { status: 'masqué',    label: '· Masqué',     activeClass: 'bg-gray-100 border-gray-400 text-gray-600' },
]

const displayedVerdicts = computed(() =>
  props.mode === 'candidat'
    ? VERDICTS.filter(v => v.status === 'retenu')
    : VERDICTS,
)

function toggleVerdict(status: string) {
  if (props.offer.verdict === status) {
    store.clearVerdict(props.offer.id)
  } else {
    store.setVerdict(props.offer.id, status)
  }
}

// ── Helpers ──────────────────────────────────────────────────────────────
const etatLabel = computed(() => {
  const e = props.offer.etat_review
  if (e === 'validee') return '✓ Validée'
  if (e === 'corrigee') return '✎ Corrigée'
  return '○ Non relue'
})

const etatClass = computed(() => {
  const e = props.offer.etat_review
  if (e === 'validee') return 'bg-green-50 text-green-700'
  if (e === 'corrigee') return 'bg-amber-50 text-amber-700'
  return 'bg-gray-100 text-gray-400'
})

function techBadgeClass(importance: string | null) {
  if (importance === 'core')         return 'bg-blue-100 text-blue-800'
  if (importance === 'required')     return 'bg-green-100 text-green-800'
  if (importance === 'nice_to_have') return 'bg-gray-100 text-gray-500'
  return 'bg-gray-100 text-gray-400'  // repli neutre
}
</script>
