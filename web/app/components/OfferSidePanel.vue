<template>
  <div class="space-y-3 text-sm">
    <div>
      <h2 class="text-base font-semibold text-gray-900 leading-snug">{{ offer.title ?? '(sans titre)' }}</h2>
      <p class="text-gray-500 mt-0.5">{{ offer.company ?? '—' }}</p>
    </div>

    <div class="flex flex-wrap gap-x-4 gap-y-1 text-xs text-gray-600">
      <span v-if="offer.remote" class="px-2 py-0.5 rounded bg-teal-50 text-teal-700 font-medium">Remote</span>
      <span v-else-if="offer.location">{{ offer.location }}</span>
    </div>

    <div v-if="ownedTechs.length || missingTechs.length" class="space-y-1.5">
      <div v-if="ownedTechs.length" class="flex flex-wrap items-center gap-1.5">
        <span class="text-[10px] text-gray-400 mr-0.5">Possédées</span>
        <span
          v-for="tech in ownedTechs" :key="tech.name"
          class="inline-flex items-center px-2 py-0.5 rounded font-medium text-xs"
          :class="techBadgeClass(tech.importance)"
        >{{ tech.name }}</span>
      </div>
      <div v-if="missingTechs.length" class="flex flex-wrap items-center gap-1.5">
        <span class="text-[10px] text-gray-400 mr-0.5">Manquantes</span>
        <span
          v-for="tech in missingTechs" :key="tech.name"
          class="inline-flex items-center px-2 py-0.5 rounded font-medium text-xs ring-1 ring-red-300"
          :class="techBadgeClass(tech.importance)"
        >{{ tech.name }}</span>
      </div>
    </div>

    <div class="prose prose-sm prose-gray max-w-none leading-relaxed text-gray-600" v-html="renderedDescription" />
  </div>
</template>

<script setup lang="ts">
import type { OfferDetail, TechInfo } from '~/stores/offers'

defineProps<{
  offer: OfferDetail
  ownedTechs: TechInfo[]
  missingTechs: TechInfo[]
  renderedDescription: string
}>()

function techBadgeClass(importance: string | null) {
  if (importance === 'core')         return 'bg-blue-100 text-blue-800'
  if (importance === 'required')     return 'bg-green-100 text-green-800'
  if (importance === 'nice_to_have') return 'bg-gray-100 text-gray-500'
  return 'bg-gray-100 text-gray-400'
}
</script>
