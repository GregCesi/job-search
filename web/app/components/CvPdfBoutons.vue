<template>
  <template v-if="anglais">
    <button
      @click="$emit('telecharger', 'fr')"
      class="text-xs px-2 py-1 rounded bg-indigo-50 text-indigo-700 hover:bg-indigo-100"
    >PDF FR</button>
    <button
      @click="$emit('telecharger', 'en')"
      class="text-xs px-2 py-1 rounded bg-indigo-50 text-indigo-700 hover:bg-indigo-100"
    >PDF EN</button>
  </template>
  <button
    v-else
    @click="$emit('telecharger', 'fr')"
    class="text-xs px-2 py-1 rounded bg-indigo-50 text-indigo-700 hover:bg-indigo-100"
  >Télécharger le PDF</button>
</template>

<script setup lang="ts">
// Boutons de téléchargement du PDF du CV (EXE-207) : les mêmes dans l'aperçu
// plein écran et dans Modifier. `anglais` dit si le CV a sa version anglaise.
defineProps<{ anglais: boolean }>()
defineEmits<{ telecharger: [lang: 'fr' | 'en'] }>()
</script>
