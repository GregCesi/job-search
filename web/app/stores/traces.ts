import { defineStore } from 'pinia'

// ── Types ──────────────────────────────────────────────────────────────────

export interface TraceParsedFacts {
  seniority_required: string | null
  techs_required: Array<string | { name: string; importance: string }>
  domain: string | null
  role_level: string | null
  parse_failed: boolean
}

export interface TraceOut {
  trace_key: string
  offer_id: string
  offer_title: string | null
  offer_company: string | null
  model: string
  extraction_version: string | null
  temperature: number
  timestamp: string
  prompt_system: string
  prompt_user: string
  raw_response: string
  parsed_facts: TraceParsedFacts
  parse_failed: boolean
  note: string | null
  cause: string | null
  severite: string | null
}

export interface TraceVersionCount {
  version: string
  count: number
}

// ── Store ──────────────────────────────────────────────────────────────────

export const useTracesStore = defineStore('traces', () => {
  const config = useRuntimeConfig()

  const traces = ref<TraceOut[]>([])
  const versions = ref<TraceVersionCount[]>([])
  const loading = ref(false)
  const selectedVersion = ref<string | null>(null)

  async function fetchTraces(version: string | null = null) {
    loading.value = true
    try {
      traces.value = await $fetch<TraceOut[]>(`${config.public.apiBase}/traces`, {
        query: version ? { version } : {},
      })
    } finally {
      loading.value = false
    }
  }

  async function fetchVersions() {
    versions.value = await $fetch<TraceVersionCount[]>(`${config.public.apiBase}/traces/versions`)
  }

  async function selectVersion(version: string | null) {
    selectedVersion.value = version
    await fetchTraces(version)
  }

  async function saveNote(trace_key: string, note: string, cause: string | null = null, severite: string | null = null) {
    await $fetch(`${config.public.apiBase}/traces/${encodeURIComponent(trace_key)}/note`, {
      method: 'PUT',
      body: { note, cause, severite },
    })
    const idx = traces.value.findIndex(t => t.trace_key === trace_key)
    if (idx !== -1) {
      traces.value[idx].note = note || null
      traces.value[idx].cause = cause
      traces.value[idx].severite = severite
    }
  }

  function exportUrl(): string {
    return `${config.public.apiBase}/traces/export`
  }

  return {
    traces,
    versions,
    loading,
    selectedVersion,
    fetchTraces,
    fetchVersions,
    selectVersion,
    saveNote,
    exportUrl,
  }
})
