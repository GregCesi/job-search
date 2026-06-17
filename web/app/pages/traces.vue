<template>
  <div class="min-h-screen bg-gray-50 flex flex-col">

    <!-- Header ─────────────────────────────────────────────────────────── -->
    <header class="bg-white border-b border-gray-200 px-6 py-3 flex items-center gap-4 sticky top-0 z-10 shadow-sm">
      <NuxtLink to="/" class="text-sm font-semibold text-gray-800 tracking-tight hover:text-indigo-600 transition-colors">
        ← job-search
      </NuxtLink>
      <span class="text-sm font-medium text-gray-500">Traces LLM — error analysis</span>
      <span class="ml-auto text-xs text-gray-400">
        {{ store.loading ? 'Chargement…' : `${store.traces.length} traces · ${groups.length} offres` }}
      </span>
      <a
        :href="store.exportUrl()"
        download="traces_annotated.jsonl"
        class="ml-2 px-3 py-1.5 rounded bg-indigo-600 text-white text-xs font-medium hover:bg-indigo-700 transition-colors"
      >
        Exporter JSONL annoté
      </a>
    </header>

    <!-- Liste ───────────────────────────────────────────────────────────── -->
    <main class="flex-1 px-6 py-6 max-w-6xl w-full mx-auto">

      <p v-if="store.loading" class="text-sm text-gray-400">Chargement des traces…</p>

      <div v-for="group in groups" :key="group.offer_id" :id="'offer-' + group.offer_id" class="mb-8">

        <!-- Group heading -->
        <div class="flex items-baseline gap-2 mb-2 px-1">
          <span class="text-xs font-semibold text-gray-700 truncate">
            {{ group.offer_title ?? group.offer_id }}
          </span>
          <span class="text-xs text-gray-400 truncate shrink-0">{{ group.offer_company ?? '—' }}</span>
          <span class="text-xs text-gray-300 font-mono">{{ group.offer_id }}</span>
          <span
            v-if="group.traces.length > 1"
            class="ml-1 px-1.5 py-0.5 rounded-full bg-orange-100 text-orange-600 text-xs font-medium shrink-0"
          >
            {{ group.traces.length }} traces
          </span>
        </div>

        <!-- Cards -->
        <div v-for="trace in group.traces" :key="trace.trace_key"
             class="mb-2 rounded-lg border border-gray-200 bg-white shadow-sm overflow-hidden">

          <!-- Card header (collapsed) ─────────────────────────────────── -->
          <button
            class="w-full flex items-center gap-3 px-4 py-3 text-left hover:bg-gray-50 transition-colors"
            @click="toggle(trace.trace_key)"
          >
            <!-- Chevron -->
            <span class="text-gray-400 text-xs shrink-0 w-3">
              {{ isExpanded(trace.trace_key) ? '▾' : '▸' }}
            </span>

            <!-- Facts summary -->
            <span class="text-xs text-gray-500 font-mono shrink-0">
              {{ trace.parsed_facts.domain ?? '?' }}
              · {{ trace.parsed_facts.seniority_required ?? '?' }}
              · {{ trace.parsed_facts.role_level ?? '?' }}
            </span>

            <!-- Divider -->
            <span class="text-gray-200 shrink-0">|</span>

            <!-- Model + temperature -->
            <span class="text-xs text-gray-400 shrink-0 font-mono">
              {{ trace.model.split(':').pop() }} · {{ trace.temperature }}°
            </span>

            <!-- Timestamp -->
            <span class="text-xs text-gray-300 font-mono shrink-0">{{ fmtTs(trace.timestamp) }}</span>

            <!-- Spacer -->
            <span class="flex-1" />

            <!-- Note pastille -->
            <span
              v-if="trace.note"
              class="w-2 h-2 rounded-full bg-amber-400 shrink-0"
              title="Note d'error analysis"
            />
          </button>

          <!-- Card expanded ────────────────────────────────────────────── -->
          <div v-if="isExpanded(trace.trace_key)"
               class="border-t border-gray-100 grid grid-cols-3 min-h-64">

            <!-- ── Gauche 1/3 — NOTE + ANNOTATION ─────────────────────── -->
            <div class="border-r border-gray-100 p-4 flex flex-col gap-2">
              <span class="text-xs font-semibold text-gray-500 uppercase tracking-wide">Note error analysis</span>
              <textarea
                v-model="localNotes[trace.trace_key]"
                placeholder="Observations, patterns de défauts, hypothèses…"
                class="flex-1 w-full resize-none rounded border border-gray-200 bg-gray-50 px-3 py-2 text-sm text-gray-800 placeholder-gray-300 focus:outline-none focus:ring-1 focus:ring-indigo-300 focus:border-indigo-300 min-h-40"
                @blur="onAnnotationSave(trace.trace_key)"
              />
              <div class="flex gap-2">
                <div class="flex-1">
                  <label class="text-xs text-gray-400 mb-0.5 block">Cause</label>
                  <select
                    v-model="localCauses[trace.trace_key]"
                    class="w-full rounded border border-gray-200 bg-gray-50 px-2 py-1.5 text-xs text-gray-700 focus:outline-none focus:ring-1 focus:ring-indigo-300"
                    @change="onAnnotationSave(trace.trace_key)"
                  >
                    <option :value="null">—</option>
                    <option value="ok">ok</option>
                    <option value="troncature">troncature</option>
                    <option value="bug_llm">bug_llm</option>
                  </select>
                </div>
                <div class="flex-1">
                  <label class="text-xs text-gray-400 mb-0.5 block">Sévérité</label>
                  <select
                    v-model="localSeverites[trace.trace_key]"
                    class="w-full rounded border border-gray-200 bg-gray-50 px-2 py-1.5 text-xs text-gray-700 focus:outline-none focus:ring-1 focus:ring-indigo-300"
                    @change="onAnnotationSave(trace.trace_key)"
                  >
                    <option :value="null">—</option>
                    <option value="mineure">mineure</option>
                    <option value="majeure">majeure</option>
                    <option value="critique">critique</option>
                  </select>
                </div>
              </div>
              <span v-if="savedKeys.includes(trace.trace_key)"
                    class="text-xs text-green-600">✓ enregistré</span>
            </div>

            <!-- ── Droite 2/3 — TRACE ─────────────────────────────────── -->
            <div class="col-span-2 p-4 flex flex-col gap-5 overflow-auto">

              <!-- Bloc 1 — Métadonnées -->
              <div>
                <div class="text-xs font-semibold text-gray-500 uppercase tracking-wide mb-2">Métadonnées</div>
                <dl class="grid grid-cols-2 gap-x-6 gap-y-1 text-xs">
                  <div class="flex gap-2">
                    <dt class="text-gray-400 shrink-0">offer_id</dt>
                    <dd class="font-mono text-gray-700">{{ trace.offer_id }}</dd>
                  </div>
                  <div class="flex gap-2">
                    <dt class="text-gray-400 shrink-0">timestamp</dt>
                    <dd class="font-mono text-gray-700">{{ trace.timestamp }}</dd>
                  </div>
                  <div class="flex gap-2">
                    <dt class="text-gray-400 shrink-0">model</dt>
                    <dd class="font-mono text-gray-700">{{ trace.model }}</dd>
                  </div>
                  <div class="flex gap-2">
                    <dt class="text-gray-400 shrink-0">temperature</dt>
                    <dd class="font-mono text-gray-700">{{ trace.temperature }}</dd>
                  </div>
                </dl>
              </div>

              <!-- Bloc 2 — Entrée Wyss -->
              <div>
                <div class="text-xs font-semibold text-gray-500 uppercase tracking-wide mb-2">Entrée — prompt</div>
                <div class="mb-2">
                  <div class="text-xs text-gray-400 mb-1">system</div>
                  <pre class="whitespace-pre-wrap font-mono text-xs bg-slate-50 border border-slate-200 rounded p-3 text-gray-700 leading-relaxed overflow-auto max-h-48">{{ trace.prompt_system }}</pre>
                </div>
                <div>
                  <div class="text-xs text-gray-400 mb-1">user</div>
                  <pre class="whitespace-pre-wrap font-mono text-xs bg-slate-50 border border-slate-200 rounded p-3 text-gray-700 leading-relaxed overflow-auto max-h-96">{{ trace.prompt_user }}</pre>
                </div>
              </div>

              <!-- Bloc 3 — Sortie Husain -->
              <div>
                <div class="text-xs font-semibold text-gray-500 uppercase tracking-wide mb-2">Sortie — réponse LLM</div>
                <div class="grid grid-cols-2 gap-4">
                  <div>
                    <div class="text-xs text-gray-400 mb-1">raw_response</div>
                    <pre class="whitespace-pre-wrap font-mono text-xs bg-slate-50 border border-slate-200 rounded p-3 text-gray-700 leading-relaxed overflow-auto max-h-64">{{ trace.raw_response }}</pre>
                  </div>
                  <div>
                    <div class="text-xs text-gray-400 mb-1">parsed_facts</div>
                    <div class="bg-slate-50 border border-slate-200 rounded p-3 text-xs font-mono text-gray-700 space-y-1">
                      <div><span class="text-gray-400">domain</span> {{ trace.parsed_facts.domain ?? '—' }}</div>
                      <div><span class="text-gray-400">seniority</span> {{ trace.parsed_facts.seniority_required ?? '—' }}</div>
                      <div><span class="text-gray-400">role_level</span> {{ trace.parsed_facts.role_level ?? '—' }}</div>
                      <div>
                        <span class="text-gray-400">techs</span>
                        <span v-if="!trace.parsed_facts.techs_required.length"> —</span>
                        <span v-else>
                          {{ trace.parsed_facts.techs_required.map(techLabel).join(', ') }}
                        </span>
                      </div>
                      <div v-if="trace.parse_failed"
                           class="mt-2 text-orange-600 font-medium">
                        parse_failed: true
                      </div>
                    </div>
                  </div>
                </div>
              </div>

            </div>
          </div>
        </div>
      </div>

    </main>
  </div>
</template>

<script setup lang="ts">
import { useTracesStore } from '~/stores/traces'
import type { TraceOut } from '~/stores/traces'

const store = useTracesStore()
const route = useRoute()

onMounted(async () => {
  await store.fetchTraces()
  const hash = route.hash
  if (hash?.startsWith('#offer-')) {
    const offerId = hash.slice(7) // '#offer-'.length
    // Expand all traces of the targeted group
    const group = groups.value.find(g => g.offer_id === offerId)
    if (group) {
      for (const t of group.traces) {
        if (!expandedKeys.value.includes(t.trace_key)) {
          expandedKeys.value.push(t.trace_key)
          localNotes[t.trace_key] = t.note ?? ''
          localCauses[t.trace_key] = t.cause ?? null
          localSeverites[t.trace_key] = t.severite ?? null
        }
      }
      await nextTick()
      document.getElementById(`offer-${offerId}`)?.scrollIntoView({ behavior: 'smooth', block: 'start' })
    }
  }
})

// ── Groupement par offer_id ──────────────────────────────────────────────────

const groups = computed(() => {
  const map = new Map<string, TraceOut[]>()
  for (const t of store.traces) {
    if (!map.has(t.offer_id)) map.set(t.offer_id, [])
    map.get(t.offer_id)!.push(t)
  }
  return [...map.entries()].map(([offer_id, traces]) => ({
    offer_id,
    offer_title:   traces[0].offer_title,
    offer_company: traces[0].offer_company,
    traces,
  }))
})

// ── Expand / collapse ────────────────────────────────────────────────────────

const expandedKeys = ref<string[]>([])

function isExpanded(key: string) {
  return expandedKeys.value.includes(key)
}

function toggle(key: string) {
  const idx = expandedKeys.value.indexOf(key)
  if (idx >= 0) {
    expandedKeys.value.splice(idx, 1)
  } else {
    expandedKeys.value.push(key)
    if (!(key in localNotes)) {
      const t = store.traces.find(t => t.trace_key === key)
      localNotes[key] = t?.note ?? ''
      localCauses[key] = t?.cause ?? null
      localSeverites[key] = t?.severite ?? null
    }
  }
}

// ── Notes locales + auto-save ────────────────────────────────────────────────

const localNotes     = reactive<Record<string, string>>({})
const localCauses    = reactive<Record<string, string | null>>({})
const localSeverites = reactive<Record<string, string | null>>({})
const savedKeys      = ref<string[]>([])

async function onAnnotationSave(trace_key: string) {
  const note     = localNotes[trace_key] ?? ''
  const cause    = localCauses[trace_key] ?? null
  const severite = localSeverites[trace_key] ?? null
  await store.saveNote(trace_key, note, cause, severite)
  savedKeys.value.push(trace_key)
  setTimeout(() => {
    const idx = savedKeys.value.indexOf(trace_key)
    if (idx >= 0) savedKeys.value.splice(idx, 1)
  }, 2000)
}

// ── Helpers ──────────────────────────────────────────────────────────────────

function techLabel(t: string | { name: string; importance: string }): string {
  return typeof t === 'string' ? t : t.name
}

function fmtTs(ts: string): string {
  try {
    return new Date(ts).toLocaleString('fr-FR', {
      day: '2-digit', month: '2-digit', hour: '2-digit', minute: '2-digit',
    })
  } catch {
    return ts
  }
}
</script>
