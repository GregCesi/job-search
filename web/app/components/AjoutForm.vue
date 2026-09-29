<template>
  <Teleport to="body">
    <div
      v-if="ajouts.formulaire.ouvert"
      class="fixed inset-0 z-50 bg-black/30 flex items-start justify-center pt-24"
      @click.self="ajouts.fermerFormulaire()"
    >
      <form
        class="w-full max-w-lg bg-white rounded-lg shadow-2xl p-5 flex flex-col gap-3"
        @submit.prevent="submit"
      >
        <h2 class="text-sm font-semibold text-gray-800">Ajouter une offre</h2>

        <label class="flex flex-col gap-1 text-xs font-medium text-gray-600">
          URL
          <input
            ref="urlInput"
            v-model="form.url"
            type="url"
            required
            class="px-2.5 py-1.5 rounded-md border border-gray-300 text-sm font-normal text-gray-800 focus:outline-none focus:ring-2 focus:ring-indigo-500"
          />
        </label>

        <template v-if="ajouts.formulaire.texte">
          <label class="flex flex-col gap-1 text-xs font-medium text-gray-600">
            Titre
            <input
              v-model="form.titre"
              required
              class="px-2.5 py-1.5 rounded-md border border-gray-300 text-sm font-normal text-gray-800 focus:outline-none focus:ring-2 focus:ring-indigo-500"
            />
          </label>
          <div class="flex gap-3">
            <label class="flex-1 flex flex-col gap-1 text-xs font-medium text-gray-600">
              Entreprise
              <input
                v-model="form.entreprise"
                class="px-2.5 py-1.5 rounded-md border border-gray-300 text-sm font-normal text-gray-800 focus:outline-none focus:ring-2 focus:ring-indigo-500"
              />
            </label>
            <label class="flex-1 flex flex-col gap-1 text-xs font-medium text-gray-600">
              Lieu
              <input
                v-model="form.lieu"
                class="px-2.5 py-1.5 rounded-md border border-gray-300 text-sm font-normal text-gray-800 focus:outline-none focus:ring-2 focus:ring-indigo-500"
              />
            </label>
          </div>
          <label class="flex flex-col gap-1 text-xs font-medium text-gray-600">
            Texte de l'offre
            <textarea
              v-model="form.texte"
              required
              rows="10"
              class="px-2.5 py-1.5 rounded-md border border-gray-300 text-sm font-normal text-gray-800 focus:outline-none focus:ring-2 focus:ring-indigo-500"
            />
          </label>
        </template>

        <div class="flex justify-end gap-2 pt-1">
          <button
            type="button"
            class="px-3 py-1.5 rounded-md text-sm font-medium text-gray-600 hover:bg-gray-100 transition-colors"
            @click="ajouts.fermerFormulaire()"
          >
            Annuler
          </button>
          <button
            type="submit"
            class="px-3 py-1.5 rounded-md text-sm font-medium bg-indigo-600 text-white hover:bg-indigo-700 transition-colors"
          >
            Envoyer
          </button>
        </div>
      </form>
    </div>
  </Teleport>
</template>

<script setup lang="ts">
import { useAjoutsStore } from '~/stores/ajouts'
import type { AjoutForm } from '~/stores/ajouts'

const ajouts = useAjoutsStore()
const form = ref<AjoutForm>({ url: '' })
const urlInput = ref<HTMLInputElement | null>(null)

// Chaque ouverture repart de l'état initial fourni (URL pré-remplie pour « texte à coller »).
watch(
  () => ajouts.formulaire.ouvert,
  async ouvert => {
    if (!ouvert) return
    form.value = { texte: '', titre: '', entreprise: '', lieu: '', ...ajouts.formulaire.initial }
    await nextTick()
    urlInput.value?.focus()
  },
)

function submit() {
  const body: AjoutForm = { url: form.value.url }
  if (ajouts.formulaire.texte) {
    body.texte = form.value.texte
    body.titre = form.value.titre
    if (form.value.entreprise?.trim()) body.entreprise = form.value.entreprise
    if (form.value.lieu?.trim()) body.lieu = form.value.lieu
  }
  // Pas d'attente : le formulaire se ferme et l'ajout se suit en tâche de fond.
  ajouts.envoyer(body)
}
</script>
