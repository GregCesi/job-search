<template>
  <span v-if="verdict" :class="cls" class="inline-flex items-center px-2 py-0.5 rounded-full text-xs font-medium">
    {{ label }}
  </span>
  <span v-else class="text-gray-300 text-xs">—</span>
</template>

<script setup lang="ts">
const props = defineProps<{ verdict: string | null }>()

const MAP: Record<string, { cls: string; label: string }> = {
  favori:                 { cls: 'bg-blue-100 text-blue-800',     label: '★ favori' },
  candidaté:              { cls: 'bg-purple-100 text-purple-800', label: '✓ candidaté' },
  rejeté:                 { cls: 'bg-red-100 text-red-700',       label: '✗ rejeté' },
  masqué:                 { cls: 'bg-gray-100 text-gray-500',     label: '· masqué' },
  hors_perimetre_ok:      { cls: 'bg-green-100 text-green-700',   label: '✓ confirmé HP' },
  hors_perimetre_faux_pos:{ cls: 'bg-red-100 text-red-700',       label: '✗ faux positif' },
}

const entry = computed(() => (props.verdict ? MAP[props.verdict] : null))
const cls   = computed(() => entry.value?.cls ?? '')
const label = computed(() => entry.value?.label ?? '')
</script>
