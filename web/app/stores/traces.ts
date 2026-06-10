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
  temperature: number
  timestamp: string
  prompt_system: string
  prompt_user: string
  raw_response: string
  parsed_facts: TraceParsedFacts
  parse_failed: boolean
  note: string | null
}

// ── Store ──────────────────────────────────────────────────────────────────

export const useTracesStore = defineStore('traces', () => {
  const config = useRuntimeConfig()

  const traces = ref<TraceOut[]>([])
  const loading = ref(false)

  async function fetchTraces() {
    loading.value = true
    try {
      traces.value = await $fetch<TraceOut[]>(`${config.public.apiBase}/traces`)
    } finally {
      loading.value = false
    }
  }

  async function saveNote(trace_key: string, note: string) {
    await $fetch(`${config.public.apiBase}/traces/${encodeURIComponent(trace_key)}/note`, {
      method: 'PUT',
      body: { note },
    })
    const idx = traces.value.findIndex(t => t.trace_key === trace_key)
    if (idx !== -1) traces.value[idx].note = note || null
  }

  return { traces, loading, fetchTraces, saveNote }
})
