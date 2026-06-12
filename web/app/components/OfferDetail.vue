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
          <ScoreBadge :score="offer.desirability" />
          <span>{{ offer.contract_type ?? '—' }}</span>
          <span>{{ offer.fetched_at?.slice(0, 10) }}</span>
          <VerdictBadge :verdict="offer.verdict" />
          <a v-if="offer.url" :href="offer.url" target="_blank" rel="noopener noreferrer"
             class="ml-auto text-indigo-600 hover:underline font-medium">
            Voir l'annonce ↗
          </a>
        </div>

        <!-- Body -->
        <div class="flex-1 overflow-y-auto px-6 py-4 space-y-6 text-sm text-gray-700">

          <!-- Verdicts -->
          <section>
            <h3 class="text-xs font-semibold text-gray-400 uppercase tracking-wide mb-3">Verdict</h3>
            <div class="flex flex-wrap gap-2">
              <button
                v-for="v in VERDICTS" :key="v.status"
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
              <div class="flex gap-2 mt-3">
                <button
                  :class="[
                    'px-3 py-1.5 rounded-lg text-xs font-medium border transition-all',
                    offer.verdict === 'hors_perimetre_ok'
                      ? 'bg-green-50 border-green-300 text-green-700'
                      : 'bg-white border-gray-200 text-gray-600 hover:border-gray-300 hover:bg-gray-50',
                  ]"
                  @click="toggleVerdict('hors_perimetre_ok')"
                >
                  ✓ Confirmé
                </button>
                <button
                  :class="[
                    'px-3 py-1.5 rounded-lg text-xs font-medium border transition-all',
                    offer.verdict === 'hors_perimetre_faux_pos'
                      ? 'bg-red-50 border-red-300 text-red-700'
                      : 'bg-white border-gray-200 text-gray-600 hover:border-gray-300 hover:bg-gray-50',
                  ]"
                  @click="toggleVerdict('hors_perimetre_faux_pos')"
                >
                  ✗ Faux positif
                </button>
                <button
                  v-if="offer.verdict === 'hors_perimetre_ok' || offer.verdict === 'hors_perimetre_faux_pos'"
                  class="px-3 py-1.5 rounded-lg text-xs font-medium border border-dashed border-gray-300 text-gray-400 hover:bg-gray-50 transition-all"
                  @click="store.clearVerdict(offer.id)"
                >
                  Retirer
                </button>
              </div>
            </div>
          </section>

          <!-- Scoring double-axe (masqué si hors-périmètre) -->
          <section v-if="!offer.hors_perimetre_reason">
            <h3 class="text-xs font-semibold text-gray-400 uppercase tracking-wide mb-3">Scoring</h3>
            <div class="grid grid-cols-2 gap-3">
              <!-- Désirabilité -->
              <div class="rounded-lg border border-gray-100 bg-gray-50 px-4 py-3">
                <p class="text-xs font-semibold text-gray-500 uppercase tracking-wide mb-1">Désirabilité</p>
                <div class="flex items-center gap-2">
                  <ScoreBadge :score="offer.desirability" />
                  <div class="flex-1 h-1.5 rounded-full bg-gray-200 overflow-hidden">
                    <div
                      :style="{ width: `${offer.desirability ?? 0}%` }"
                      :class="scoreBarClass(offer.desirability ?? 0)"
                      class="h-full rounded-full transition-all"
                    />
                  </div>
                </div>
                <div v-if="offer.desirability_detail" class="mt-2 space-y-0.5">
                  <div v-for="(v, k) in offer.desirability_detail" :key="k"
                       class="flex justify-between text-xs text-gray-400">
                    <span>{{ k }}</span>
                    <span :class="(v as any).score === 1 ? 'text-green-600' : 'text-red-400'">
                      {{ (v as any).score === 1 ? '✓' : '✗' }}
                    </span>
                  </div>
                </div>
              </div>
              <!-- Atteignabilité -->
              <div class="rounded-lg border border-gray-100 bg-gray-50 px-4 py-3">
                <p class="text-xs font-semibold text-gray-500 uppercase tracking-wide mb-1">Atteignabilité</p>
                <div class="flex items-center gap-2 mb-1">
                  <ScoreBadge :score="offer.attainability" />
                  <div class="flex-1 h-1.5 rounded-full bg-gray-200 overflow-hidden">
                    <div
                      :style="{ width: `${offer.attainability ?? 0}%` }"
                      :class="scoreBarClass(offer.attainability ?? 0)"
                      class="h-full rounded-full transition-all"
                    />
                  </div>
                </div>
                <span :class="categoryClass(offer.category)" class="inline-block px-2 py-0.5 rounded text-xs font-semibold">
                  {{ categoryLabel(offer.category) }}
                </span>
                <div v-if="offer.attainability_detail" class="mt-2 space-y-1 text-xs text-gray-500">
                  <p>
                    tech <span class="font-medium text-gray-700">{{ offer.attainability_detail.attain_tech.toFixed(0) }}</span>
                    · rôle <span class="font-medium text-gray-700">{{ offer.attainability_detail.attain_role.toFixed(0) }}</span>
                    <span v-if="offer.attainability_detail.blocked_by" class="ml-1 text-amber-600">
                      ← bloqué par {{ offer.attainability_detail.blocked_by }}
                    </span>
                  </p>
                  <p v-if="offer.attainability_detail.techs_matched.length > 0">
                    <span class="text-green-600 font-medium">✓</span>
                    {{ offer.attainability_detail.techs_matched.join(', ') }}
                  </p>
                  <p v-if="offer.attainability_detail.techs_missing.length > 0">
                    <span class="text-red-500 font-medium">✗</span>
                    {{ offer.attainability_detail.techs_missing.join(', ') }}
                  </p>
                </div>
              </div>
            </div>
            <!-- Faits extraits -->
            <div v-if="offer.extracted_facts" class="mt-2 rounded-lg border border-gray-100 bg-gray-50 px-4 py-3 text-xs text-gray-500">
              <span class="font-medium text-gray-700">{{ offer.extracted_facts.domain }}</span>
              · {{ offer.extracted_facts.seniority_required }}
              · {{ offer.extracted_facts.techs_required.join(', ') || '—' }}
            </div>
          </section>

          <!-- Description -->
          <section v-if="offer.description">
            <h3 class="text-xs font-semibold text-gray-400 uppercase tracking-wide mb-2">Description</h3>
            <p class="whitespace-pre-line leading-relaxed text-gray-600">{{ offer.description }}</p>
          </section>

          <!-- Calibration — avis humain par critère -->
          <section v-if="offer.criteria.length > 0">
            <h3 class="text-xs font-semibold text-gray-400 uppercase tracking-wide mb-3">Calibration</h3>

            <!-- Warning offre non vue -->
            <div v-if="!offer.seen" class="mb-3 flex items-center gap-2 rounded-lg bg-amber-50 border border-amber-200 px-3 py-2 text-xs text-amber-700">
              <span>⚠</span>
              <span>Offre non consultée — l'avis sera marqué <code>seen_at_review=false</code>.</span>
            </div>

            <!-- Grille critères — L4 (lecture seule IA) + L5 (champs avis) -->
            <div class="space-y-2">
              <div
                v-for="c in offer.criteria" :key="c.nom"
                class="rounded-lg border border-gray-100 bg-gray-50 px-3 py-2.5 text-xs"
              >
                <!-- Ligne critère IA (L4 — lecture seule) -->
                <div class="flex items-start justify-between gap-2 mb-2">
                  <div class="flex-1 min-w-0">
                    <span class="font-semibold text-gray-700 capitalize">{{ c.nom.replace('_', ' ') }}</span>
                    <span class="ml-1.5 text-gray-400 text-[10px] uppercase tracking-wide">{{ c.axe }}</span>
                    <p class="text-gray-400 mt-0.5 leading-snug">{{ c.justif }}</p>
                  </div>
                  <span :class="noteClass(c.note)" class="flex-shrink-0 font-bold text-sm tabular-nums px-1.5">
                    {{ c.note }}/10
                  </span>
                </div>

                <!-- Champs avis humain (L5) -->
                <div class="flex items-center gap-2 pt-2 border-t border-gray-200">
                  <label class="text-gray-400 shrink-0">Note :</label>
                  <input
                    v-model.number="review[c.nom].note"
                    type="number" min="0" max="10" step="1"
                    placeholder="—"
                    class="w-16 rounded border border-gray-200 px-1.5 py-0.5 text-xs text-gray-700 focus:outline-none focus:border-indigo-300"
                  />
                  <input
                    v-model="review[c.nom].justif"
                    type="text"
                    placeholder="justif (optionnel)"
                    class="flex-1 rounded border border-gray-200 px-1.5 py-0.5 text-xs text-gray-500 placeholder-gray-300 focus:outline-none focus:border-indigo-300"
                  />
                </div>
              </div>
            </div>

            <!-- Bloc audit global (L6) -->
            <div class="mt-3 space-y-2">
              <div class="flex items-center gap-2">
                <label class="text-xs text-gray-500 shrink-0">Note globale :</label>
                <input
                  v-model.number="globalScore"
                  type="number" min="0" max="10" step="1"
                  placeholder="—"
                  class="w-16 rounded border border-gray-200 px-1.5 py-0.5 text-xs text-gray-700 focus:outline-none focus:border-indigo-300"
                />
              </div>
              <textarea
                v-model="globalAudit"
                placeholder="Audit global (impression générale, biais repérés…)"
                rows="3"
                class="w-full rounded border border-gray-200 px-2 py-1.5 text-xs text-gray-600 placeholder-gray-300 focus:outline-none focus:border-indigo-300 resize-none"
              />
              <div class="flex items-center justify-between">
                <span v-if="store.openedReview" class="text-[10px] text-gray-400">
                  Sauvegardé {{ store.openedReview.created_at.slice(0, 16).replace('T', ' ') }}
                </span>
                <span v-else class="text-[10px] text-gray-300">Non sauvegardé</span>
                <button
                  @click="handleSave"
                  :disabled="saving"
                  :class="[
                    'px-3 py-1 rounded text-xs font-medium transition-all',
                    saved
                      ? 'bg-green-50 border border-green-200 text-green-700'
                      : 'bg-indigo-600 text-white hover:bg-indigo-700 disabled:opacity-50',
                  ]"
                >
                  {{ saved ? '✓ Sauvegardé' : saving ? '…' : 'Sauvegarder' }}
                </button>
              </div>
            </div>
          </section>

        </div>
      </div>
    </div>
  </Teleport>
</template>

<script setup lang="ts">
import { useOffersStore } from '~/stores/offers'
import type { OfferDetail } from '~/stores/offers'

const props = defineProps<{ offer: OfferDetail }>()
defineEmits<{ close: [] }>()

const store = useOffersStore()

// ── Calibration state (L5/L6) — local, persisted in C-3 ───────────────────
type CriterionReview = { note: number | null; justif: string }

const review = ref<Record<string, CriterionReview>>({})
const globalScore = ref<number | null>(null)
const globalAudit = ref('')

// Hydratation depuis la review existante (L8), sinon initialisation vide
watch(
  () => props.offer.id,
  () => {
    const existing = store.openedReview
    review.value = Object.fromEntries(
      props.offer.criteria.map(c => [
        c.nom,
        {
          note: existing?.ratings_json[c.nom]?.note ?? null,
          justif: existing?.ratings_json[c.nom]?.justif ?? '',
        },
      ])
    )
    globalScore.value = existing?.global_score ?? null
    globalAudit.value = existing?.global_audit_text ?? ''
  },
  { immediate: true },
)

// Ré-hydrate si la review change (après save)
watch(
  () => store.openedReview,
  (r) => {
    if (!r) return
    for (const c of props.offer.criteria) {
      review.value[c.nom] = {
        note: r.ratings_json[c.nom]?.note ?? null,
        justif: r.ratings_json[c.nom]?.justif ?? '',
      }
    }
    globalScore.value = r.global_score ?? null
    globalAudit.value = r.global_audit_text ?? ''
  },
)

const saving = ref(false)
const saved = ref(false)

async function handleSave() {
  saving.value = true
  saved.value = false
  try {
    await store.saveReview(
      props.offer.id,
      review.value as Record<string, { note: number | null; justif: string }>,
      globalAudit.value || null,
      globalScore.value,
    )
    saved.value = true
    setTimeout(() => { saved.value = false }, 2000)
  } finally {
    saving.value = false
  }
}

const VERDICTS = [
  { status: 'favori',    label: '★ Favori',     activeClass: 'bg-blue-50 border-blue-300 text-blue-700' },
  { status: 'candidaté', label: '✓ Candidaté',  activeClass: 'bg-purple-50 border-purple-300 text-purple-700' },
  { status: 'rejeté',    label: '✗ Rejeté',     activeClass: 'bg-red-50 border-red-300 text-red-700' },
  { status: 'masqué',    label: '· Masqué',     activeClass: 'bg-gray-100 border-gray-400 text-gray-600' },
]

function toggleVerdict(status: string) {
  if (props.offer.verdict === status) {
    store.clearVerdict(props.offer.id)
  } else {
    store.setVerdict(props.offer.id, status)
  }
}

function categoryLabel(c: string | null) {
  if (c === 'parfait')     return '★ Parfait'
  if (c === 'reve')        return '◈ Rêve'
  if (c === 'atteignable') return '✓ Atteignable'
  if (c === 'hors')        return '✗ Hors de portée'
  return '—'
}

function categoryClass(c: string | null) {
  if (c === 'parfait')     return 'bg-green-50 text-green-700'
  if (c === 'reve')        return 'bg-indigo-50 text-indigo-700'
  if (c === 'atteignable') return 'bg-amber-50 text-amber-700'
  return 'bg-gray-100 text-gray-400'
}

function scoreBarClass(score: number) {
  if (score >= 70) return 'bg-green-400'
  if (score >= 40) return 'bg-amber-400'
  return 'bg-red-400'
}

function noteClass(note: number) {
  if (note >= 7) return 'text-green-600'
  if (note >= 4) return 'text-amber-600'
  return 'text-red-500'
}
</script>
