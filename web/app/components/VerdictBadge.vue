<template>
  <span v-if="verdict" :class="cls" class="inline-flex items-center px-2 py-0.5 rounded-full text-xs font-medium">
    {{ label }}
  </span>
  <span v-else class="text-gray-300 text-xs">—</span>
</template>

<script setup lang="ts">
const props = defineProps<{ verdict: string | null; etape?: string | null }>()

const MAP: Record<string, { cls: string; label: string }> = {
  retenu:                 { cls: 'bg-blue-100 text-blue-800',     label: '★ retenu' },
  candidaté:              { cls: 'bg-purple-100 text-purple-800', label: '✓ candidaté' },
  rejeté:                 { cls: 'bg-red-100 text-red-700',       label: '✗ rejeté' },
  masqué:                 { cls: 'bg-gray-100 text-gray-500',     label: '· masqué' },
  hors_perimetre_ok:      { cls: 'bg-green-100 text-green-700',   label: '✓ confirmé HP' },
  hors_perimetre_faux_pos:{ cls: 'bg-red-100 text-red-700',       label: '✗ faux positif' },
}

// Étape de candidature (EXE-144) : remplace le badge générique « retenu »
// dans les tableaux, l'API la rend déjà calculée (frontend.md — zéro calcul
// métier côté front).
const ETAPE_MAP: Record<string, { cls: string; label: string }> = {
  retenue:             { cls: 'bg-blue-100 text-blue-800',       label: '★ retenue' },
  prete_a_l_envoi:     { cls: 'bg-amber-100 text-amber-800',     label: '➜ prête à l\'envoi' },
  candidature_envoyee: { cls: 'bg-emerald-100 text-emerald-800', label: '✓ candidature envoyée' },
}

const entry = computed(() => {
  if (props.verdict === 'retenu' && props.etape) {
    return ETAPE_MAP[props.etape] ?? MAP.retenu
  }
  return props.verdict ? MAP[props.verdict] : null
})
const cls   = computed(() => entry.value?.cls ?? '')
const label = computed(() => entry.value?.label ?? '')
</script>
