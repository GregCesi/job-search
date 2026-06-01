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
          <ScoreBadge :score="offer.score" />
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

          <!-- Critères de scoring -->
          <section v-if="offer.criteria.length > 0">
            <h3 class="text-xs font-semibold text-gray-400 uppercase tracking-wide mb-3">
              Scoring par critère
            </h3>
            <div class="space-y-3">
              <div
                v-for="c in offer.criteria" :key="c.key"
                class="rounded-lg border border-gray-100 bg-gray-50 px-4 py-3"
              >
                <div class="flex items-center justify-between mb-1.5">
                  <span class="text-xs font-semibold text-gray-700 uppercase tracking-wide">
                    {{ formatKey(c.key) }}
                  </span>
                  <div class="flex items-center gap-2">
                    <div class="w-24 h-1.5 rounded-full bg-gray-200 overflow-hidden">
                      <div
                        :style="{ width: `${c.score * 10}%` }"
                        :class="scoreBarClass(c.score)"
                        class="h-full rounded-full transition-all"
                      />
                    </div>
                    <ScoreBadge :score="c.score * 10" />
                  </div>
                </div>
                <p class="text-xs text-gray-500 leading-relaxed">{{ c.justification }}</p>
                <p v-if="c.parse_failed" class="mt-1 text-xs text-amber-600 font-medium">
                  ⚠ parse échoué
                </p>
              </div>
            </div>
          </section>

          <section v-else-if="offer.criteria.length === 0">
            <h3 class="text-xs font-semibold text-gray-400 uppercase tracking-wide mb-2">
              Scoring par critère
            </h3>
            <p class="text-xs text-gray-400 italic">Critères non disponibles pour cette offre.</p>
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

function formatKey(key: string) {
  return key.replace(/_/g, ' ')
}

function scoreBarClass(score: number) {
  if (score >= 7) return 'bg-green-400'
  if (score >= 4) return 'bg-amber-400'
  return 'bg-red-400'
}
</script>
