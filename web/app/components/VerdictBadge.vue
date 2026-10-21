<template>
  <span class="inline-flex items-center gap-1">
    <span v-if="triEntry" :class="triEntry.cls" class="inline-flex items-center px-2 py-0.5 rounded-full text-xs font-medium">
      {{ triEntry.label }}
    </span>
    <span v-if="revueEntry" :class="revueEntry.cls" class="inline-flex items-center px-2 py-0.5 rounded-full text-xs font-medium">
      {{ revueEntry.label }}
    </span>
    <span v-if="!triEntry && !revueEntry" class="text-gray-300 text-xs">—</span>
  </span>
</template>

<script setup lang="ts">
// EXE-194, critère 21 : tri (ou étape) et revue hors périmètre sont deux axes
// indépendants, affichés côte à côte, jamais l'un masquant l'autre — l'ancien
// prop `verdict` fusionnait les deux et faisait disparaître le tri d'une
// offre écartée ou retenue dès qu'elle portait une revue.
const props = defineProps<{ tri: string; etape?: string | null; revue?: string | null }>()

const REVUE_MAP: Record<string, { cls: string; label: string }> = {
  hors_perimetre_ok:      { cls: 'bg-green-100 text-green-700', label: '✓ confirmé HP' },
  hors_perimetre_faux_pos:{ cls: 'bg-red-100 text-red-700',     label: '✗ faux positif' },
}

const ECARTEE_ENTRY = { cls: 'bg-red-100 text-red-700', label: '✗ écartée' }

// Étape de candidature (EXE-144, TCK-311) : remplace le badge générique
// « retenu » dans les tableaux, l'API la rend déjà calculée (frontend.md —
// zéro calcul métier côté front).
const ETAPE_MAP: Record<string, { cls: string; label: string }> = {
  retenue:             { cls: 'bg-blue-100 text-blue-800',       label: '★ retenue' },
  prete_a_l_envoi:     { cls: 'bg-amber-100 text-amber-800',     label: '➜ prête à l\'envoi' },
  candidature_envoyee: { cls: 'bg-emerald-100 text-emerald-800', label: '✓ candidature envoyée' },
  entretien:           { cls: 'bg-indigo-100 text-indigo-800',   label: '◆ entretien' },
  offre_recue:         { cls: 'bg-emerald-100 text-emerald-800', label: '✓ offre reçue' },
  refusee:             { cls: 'bg-red-100 text-red-700',         label: '✗ refusée' },
  sans_suite:          { cls: 'bg-gray-100 text-gray-500',       label: '· sans suite' },
  abandonnee:          { cls: 'bg-gray-100 text-gray-500',       label: '· abandonnée' },
}

// Une offre à trier n'a pas de badge de tri (critère 21).
const triEntry = computed(() => {
  if (props.etape) return ETAPE_MAP[props.etape] ?? null
  if (props.tri === 'ecartee') return ECARTEE_ENTRY
  return null
})
const revueEntry = computed(() => (props.revue ? REVUE_MAP[props.revue] ?? null : null))
</script>
