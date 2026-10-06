<template>
  <button
    type="button"
    role="switch"
    :aria-checked="pret"
    :disabled="disabled"
    @click="$emit('toggle')"
    class="inline-flex items-center gap-2 text-xs font-medium flex-shrink-0 disabled:cursor-not-allowed disabled:opacity-40"
  >
    <span
      class="relative inline-flex h-5 w-9 items-center rounded-full transition-colors duration-200 ease-in-out"
      :class="pret ? 'bg-green-500' : 'bg-gray-300'"
    >
      <span
        class="inline-block h-3.5 w-3.5 transform rounded-full bg-white shadow transition-transform duration-200 ease-in-out"
        :class="pret ? 'translate-x-4' : 'translate-x-1'"
      />
    </span>
    <span :class="pret ? 'text-green-700' : 'text-gray-500'">Prête</span>
  </button>
</template>

<script setup lang="ts">
defineProps<{ pret: boolean, disabled: boolean }>()
defineEmits<{ toggle: [] }>()
</script>
