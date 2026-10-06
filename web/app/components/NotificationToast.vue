<template>
  <div
    class="relative bg-white border border-gray-200 rounded-lg shadow-lg p-3 pr-8 text-sm"
    @mouseenter="pause"
    @mouseleave="reprendre"
  >
    <slot />
  </div>
</template>

<script setup lang="ts">
// Retrait automatique d'une notification de toast après un délai, sauf
// pendant que la souris est dessus (EXE-136). Le parent décide si une
// notification y est éligible via `autoRetrait` — jamais un échec ni une
// notification à bouton d'action.

const props = defineProps<{ autoRetrait: boolean }>()
const emit = defineEmits<{ fermer: [] }>()

const DELAI_MS = 8000

let timer: ReturnType<typeof setTimeout> | null = null

function demarrer() {
  if (!props.autoRetrait) return
  timer = setTimeout(() => emit('fermer'), DELAI_MS)
}

function pause() {
  if (timer !== null) {
    clearTimeout(timer)
    timer = null
  }
}

function reprendre() {
  if (props.autoRetrait && timer === null) demarrer()
}

onMounted(demarrer)
onUnmounted(pause)
</script>
