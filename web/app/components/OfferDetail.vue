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

          <!-- Scoring double-axe -->
          <section>
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
                <span :class="reachClass(offer.attainability)" class="inline-block px-2 py-0.5 rounded text-xs font-semibold">
                  {{ reachLabel(offer.attainability) }}
                </span>
                <div v-if="offer.attainability_detail" class="mt-2 space-y-1 text-xs text-gray-500">
                  <p v-if="offer.attainability_detail.techs_matched.length > 0">
                    <span class="text-green-600 font-medium">✓</span>
                    {{ offer.attainability_detail.techs_matched.join(', ') }}
                  </p>
                  <p v-if="offer.attainability_detail.techs_missing.length > 0">
                    <span class="text-red-500 font-medium">✗</span>
                    {{ offer.attainability_detail.techs_missing.join(', ') }}
                  </p>
                  <p class="text-gray-400">
                    Écart séniorité : {{ offer.attainability_detail.seniority_gap > 0 ? '+' : '' }}{{ offer.attainability_detail.seniority_gap }}
                  </p>
                </div>
              </div>
            </div>
            <!-- Faits extraits -->
            <div v-if="offer.extracted_facts" class="mt-2 rounded-lg border border-gray-100 bg-gray-50 px-4 py-3 text-xs text-gray-500">
              <span class="font-medium text-gray-700">{{ offer.extracted_facts.domain }}</span>
              · {{ offer.extracted_facts.seniority_required }}
              · {{ offer.extracted_facts.techs_required.join(', ') || '—' }}
              <span v-if="offer.extracted_facts.parse_failed" class="ml-1 text-amber-600">⚠ parse_failed</span>
            </div>
          </section>

          <!-- Description -->
          <section v-if="offer.description">
            <h3 class="text-xs font-semibold text-gray-400 uppercase tracking-wide mb-2">Description</h3>
            <p class="whitespace-pre-line leading-relaxed text-gray-600">{{ offer.description }}</p>
          </section>

          <!-- Zone V2 — réservée, vide en V1 -->
          <!--
            V2 : note perso, suivi CV/LM, compétences entretien
          -->
          <section class="rounded-lg border border-dashed border-gray-200 px-4 py-3 text-xs text-gray-300">
            Zone V2 — suivi candidature (note perso, CV/LM, compétences entretien)
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

function reachLabel(a: string | null) {
  if (a === 'at_level') return '✓ À portée'
  if (a === 'one_step_up') return '↑ Un cran au-dessus'
  if (a === 'out_of_reach') return '✗ Hors de portée'
  return '—'
}

function reachClass(a: string | null) {
  if (a === 'at_level') return 'bg-green-50 text-green-700'
  if (a === 'one_step_up') return 'bg-amber-50 text-amber-700'
  if (a === 'out_of_reach') return 'bg-red-50 text-red-600'
  return 'bg-gray-100 text-gray-400'
}

function scoreBarClass(score: number) {
  if (score >= 70) return 'bg-green-400'
  if (score >= 40) return 'bg-amber-400'
  return 'bg-red-400'
}
</script>
