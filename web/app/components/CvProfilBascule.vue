<template>
  <!-- Bascule de profil du CV, dans Modifier (EXE-184, EXE-207). Le bouton mis
       en évidence suit le profil constaté sur le texte du CV, rendu par l'API
       (EXE-185) : rien n'est calculé ici. Profil développeur : EXE-208. -->
  <div class="flex items-center gap-0.5 rounded-lg border border-gray-200 p-0.5 text-xs font-medium">
    <button
      v-for="option in OPTIONS"
      :key="option.profil"
      @click="$emit('choisir', option.profil)"
      :disabled="busy || profilAffiche === option.profil"
      :class="profilAffiche === option.profil ? 'bg-indigo-600 text-white' : 'text-gray-500 hover:bg-gray-50'"
      class="px-2 py-1 rounded disabled:opacity-50"
    >{{ option.label }}</button>
  </div>
</template>

<script setup lang="ts">
import type { CvProfil } from '~/stores/offers'

const OPTIONS: { profil: CvProfil, label: string }[] = [
  { profil: 'base', label: 'Profil base' },
  { profil: 'claude', label: 'Profil Claude' },
  { profil: 'dev', label: 'Profil développeur' },
]

defineProps<{ profilAffiche: CvProfil | null, busy: boolean }>()
defineEmits<{ choisir: [profil: CvProfil] }>()
</script>
