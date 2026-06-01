<template>
  <span :class="cls" class="inline-flex items-center px-2 py-0.5 rounded text-xs font-semibold tabular-nums">
    {{ score !== null ? score.toFixed(0) : '—' }}
  </span>
</template>

<script setup lang="ts">
const props = defineProps<{ score: number | null }>()

const cls = computed(() => {
  if (props.score === null) return 'bg-gray-100 text-gray-400'
  if (props.score >= 70) return 'bg-green-100 text-green-800'
  if (props.score >= 40) return 'bg-amber-100 text-amber-800'
  return 'bg-red-100 text-red-700'
})
</script>
