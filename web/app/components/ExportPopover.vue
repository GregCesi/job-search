<template>
  <div class="relative">
    <button
      class="text-xs text-indigo-600 hover:underline font-medium"
      @click="open = !open"
    >
      Exporter
    </button>

    <div
      v-if="open"
      class="absolute right-0 top-8 z-50 w-56 bg-white border border-gray-200 rounded-lg shadow-lg p-3"
    >
      <p class="text-xs font-semibold text-gray-700 mb-2">Champs à inclure</p>

      <label
        v-for="field in FIELDS" :key="field.key"
        class="flex items-center gap-2 py-0.5 text-xs text-gray-600 cursor-pointer"
      >
        <input v-model="selected" type="checkbox" :value="field.key" class="rounded border-gray-300 text-indigo-600 focus:ring-indigo-500" />
        {{ field.label }}
      </label>

      <button
        class="mt-3 w-full text-xs font-medium rounded-md px-3 py-1.5 transition-colors"
        :class="copied
          ? 'bg-green-100 text-green-700'
          : 'bg-indigo-600 text-white hover:bg-indigo-700'"
        :disabled="copying"
        @click="doCopy"
      >
        {{ copied ? 'Copié ✓' : 'Copier' }}
      </button>
    </div>

    <!-- backdrop -->
    <div v-if="open" class="fixed inset-0 z-40" @click="open = false" />
  </div>
</template>

<script setup lang="ts">
import { useOffersStore } from '~/stores/offers'

const config = useRuntimeConfig()
const store = useOffersStore()

const FIELDS = [
  { key: 'company',     label: 'Entreprise' },
  { key: 'category',    label: 'Catégorie' },
  { key: 'techs',       label: 'Techs' },
  { key: 'domain',      label: 'Domaine' },
  { key: 'role',        label: 'Role' },
  { key: 'location',    label: 'Localisation' },
  { key: 'contract',    label: 'Contrat' },
  { key: 'url',         label: 'URL' },
  { key: 'description', label: 'Description' },
]

const selected = ref<string[]>(['company', 'category', 'techs'])
const open = ref(false)
const copying = ref(false)
const copied = ref(false)

async function doCopy() {
  copying.value = true
  copied.value = false
  try {
    const params = new URLSearchParams()

    // Filtres actifs du store
    const f = store.filters
    if (f.category !== undefined) params.set('category', f.category)
    if (f.hors_perimetre !== undefined) params.set('hors_perimetre', String(f.hors_perimetre))
    if (f.etat_review !== undefined) params.set('etat_review', f.etat_review)
    if (f.remote !== undefined) params.set('remote', String(f.remote))
    if (f.source !== undefined) params.set('source', f.source)
    if (f.verdict !== undefined) params.set('verdict', f.verdict)
    if (f.q) params.set('q', f.q)
    params.set('sort', f.sort)
    params.set('order', f.order)

    // Champs à inclure
    if (selected.value.length > 0) {
      params.set('include', selected.value.join(','))
    }

    const url = `${config.public.apiBase}/export/offers?${params.toString()}`
    const text = await $fetch<string>(url, { responseType: 'text' })
    await navigator.clipboard.writeText(text)
    copied.value = true
    setTimeout(() => { copied.value = false }, 2000)
  } catch (e) {
    console.error('Export copy failed', e)
  } finally {
    copying.value = false
  }
}
</script>
