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
            class="px-2.5 py-1.5 rounded-md border border-gray-300 text-sm font-normal text-gray-800 focus:outline-none focus:ring-2 focus:ring-indigo-500"
          />
          <span class="font-normal text-gray-400">
            Une offre sans URL ne pourra pas être vérifiée à l'expiration.
          </span>
        </label>

        <label class="flex flex-col gap-1 text-xs font-medium text-gray-600">
          Texte de l'offre
          <textarea
            ref="texteInput"
            v-model="form.texte"
            rows="10"
            class="px-2.5 py-1.5 rounded-md border border-gray-300 text-sm font-normal text-gray-800 focus:outline-none focus:ring-2 focus:ring-indigo-500"
          />
        </label>

        <label class="flex flex-col gap-1 text-xs font-medium text-gray-600">
          <span>Titre <span class="font-normal text-gray-400">(facultatif)</span></span>
          <input
            ref="titreInput"
            v-model="form.titre"
            class="px-2.5 py-1.5 rounded-md border border-gray-300 text-sm font-normal text-gray-800 focus:outline-none focus:ring-2 focus:ring-indigo-500"
          />
        </label>
        <div class="flex gap-3">
          <label class="flex-1 flex flex-col gap-1 text-xs font-medium text-gray-600">
            <span>Entreprise <span class="font-normal text-gray-400">(facultatif)</span></span>
            <input
              v-model="form.entreprise"
              class="px-2.5 py-1.5 rounded-md border border-gray-300 text-sm font-normal text-gray-800 focus:outline-none focus:ring-2 focus:ring-indigo-500"
            />
          </label>
          <label class="flex-1 flex flex-col gap-1 text-xs font-medium text-gray-600">
            <span>Lieu <span class="font-normal text-gray-400">(facultatif)</span></span>
            <input
              v-model="form.lieu"
              class="px-2.5 py-1.5 rounded-md border border-gray-300 text-sm font-normal text-gray-800 focus:outline-none focus:ring-2 focus:ring-indigo-500"
            />
          </label>
        </div>

        <p v-if="vide" class="text-xs text-red-700" role="alert">
          Saisir une URL ou coller le texte de l'offre.
        </p>

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
const form = ref<Required<AjoutForm>>({ url: '', texte: '', titre: '', entreprise: '', lieu: '' })
const vide = ref(false)
const urlInput = ref<HTMLInputElement | null>(null)
const texteInput = ref<HTMLTextAreaElement | null>(null)
const titreInput = ref<HTMLInputElement | null>(null)

// Chaque ouverture repart de l'état initial fourni : URL et texte déjà envoyés quand
// une notification rouvre le formulaire. Le focus va au premier champ à remplir.
watch(
  () => ajouts.formulaire.ouvert,
  async ouvert => {
    if (!ouvert) return
    form.value = { url: '', texte: '', titre: '', entreprise: '', lieu: '', ...ajouts.formulaire.initial }
    vide.value = false
    await nextTick()
    if (form.value.texte.trim()) titreInput.value?.focus()
    else if (form.value.url.trim()) texteInput.value?.focus()
    else urlInput.value?.focus()
  },
)

function submit() {
  if (!form.value.url.trim() && !form.value.texte.trim()) {
    vide.value = true
    return
  }
  // Envoyé tel que saisi : seuls les champs laissés vides sont omis.
  const body: AjoutForm = {}
  for (const champ of ['url', 'texte', 'titre', 'entreprise', 'lieu'] as const) {
    if (form.value[champ].trim()) body[champ] = form.value[champ]
  }
  // Pas d'attente : le formulaire se ferme et l'ajout se suit en tâche de fond.
  ajouts.envoyer(body)
}
</script>
