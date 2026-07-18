<script lang="ts">
  import { api, type GraphEdge, type ReviewItem } from '../lib/api'
  import { RUNE } from '../lib/theme'
  import { link } from '../lib/router.svelte'
  import { refreshGraph } from '../lib/appstate.svelte'
  import { liveRefresh } from '../lib/useLive.svelte'

  let items = $state<ReviewItem[] | null>(null)
  let edges = $state<GraphEdge[]>([])
  let error = $state<string | null>(null)
  let busy = $state<string | null>(null)

  function load() {
    Promise.all([api.review(), api.graph()])
      .then(([r, g]) => {
        items = r.items
        edges = g.edges
      })
      .catch((e) => (error = String(e)))
  }
  $effect(load)
  liveRefresh(load, { enabled: () => busy === null })

  // each item's outgoing belongs_to links (its "approved links")
  const linksByNode = $derived.by(() => {
    const m = new Map<string, GraphEdge[]>()
    for (const e of edges) {
      if (e.rel !== 'belongs_to') continue
      const arr = m.get(e.src) ?? []
      arr.push(e)
      m.set(e.src, arr)
    }
    return m
  })

  async function sanction(id: string) {
    busy = id
    try {
      await api.markReviewed(id)
      items = items ? items.filter((i) => i.id !== id) : items
    } finally {
      busy = null
    }
  }

  async function pruneLinks(id: string) {
    busy = id
    try {
      for (const e of linksByNode.get(id) ?? []) {
        await api.deleteEdge(e.src, e.dst, e.rel)
      }
      refreshGraph()
      load()
    } finally {
      busy = null
    }
  }
</script>

<div class="min-h-screen overflow-y-auto px-margin py-lg max-w-3xl">
  <a href={link('/')} class="font-label-md text-label-md text-text-muted hover:text-primary uppercase tracking-widest inline-flex items-center gap-1">
    <span class="material-symbols-outlined text-[16px]">arrow_back</span> Constellation
  </a>

  <header class="mt-6 mb-lg flex items-center gap-3 border-b border-border-subtle pb-6">
    <span class="material-symbols-outlined text-primary-container text-[32px]" style="filter:drop-shadow(0 0 8px #d4a93f)">fort</span>
    <div>
      <span class="font-label-md text-label-md text-primary-container uppercase tracking-widest">Review sanctum</span>
      <h1 class="font-headline-lg text-headline-lg text-primary leading-none">Unreviewed</h1>
    </div>
  </header>

  {#if error}
    <p class="font-body-sm text-body-sm text-status-error">{error}</p>
  {/if}
  {#if !items && !error}
    <p class="font-headline-md text-headline-md text-text-tertiary animate-pulse">Gathering the unsanctioned...</p>
  {/if}
  {#if items && items.length === 0}
    <p class="font-body-lg text-body-lg text-text-tertiary">The sanctum is clear. All knowledge has been sanctioned.</p>
  {/if}

  <ul class="space-y-3">
    {#each items ?? [] as item (item.id)}
      {@const rune = RUNE[item.type]}
      {@const hasLinks = (linksByNode.get(item.id) ?? []).length > 0}
      <li
        class="bg-bg-panel border border-border-default rounded-lg p-4 border-l-4 flex items-start justify-between gap-4"
        style="border-left-color:{rune.color}"
      >
        <div class="min-w-0">
          <div class="flex items-center gap-2 mb-1">
            <span class="w-2 h-2 rounded-full svg-pulse" style="background-color:{rune.color}; box-shadow:0 0 8px {rune.color}"></span>
            <span class="font-label-md text-label-md uppercase tracking-wider" style="color:{rune.color}">{rune.label}</span>
          </div>
          <p class="font-body-md text-body-md text-on-surface truncate">{item.title}</p>
          {#if item.context_summary}
            <p class="font-body-sm text-body-sm text-text-muted mt-1 line-clamp-2">{item.context_summary.slice(0, 160)}</p>
          {/if}
        </div>
        <div class="shrink-0 flex items-center gap-2">
          {#if hasLinks}
            <button
              onclick={() => pruneLinks(item.id)}
              disabled={busy === item.id}
              title="Prune this node's links"
              class="py-1.5 px-3 border border-border-default rounded text-text-muted hover:text-status-error hover:border-status-error transition-all duration-200 font-label-md text-label-md uppercase tracking-wider flex items-center gap-1 disabled:opacity-50"
            >
              <span class="material-symbols-outlined text-[16px]">content_cut</span> Prune
            </button>
          {/if}
          <button
            onclick={() => sanction(item.id)}
            disabled={busy === item.id}
            class="py-1.5 px-3 bg-surface text-primary-container border border-primary-container rounded hover:bg-bg-surface hover:shadow-[0_0_15px_0px_rgba(212,169,63,0.3)] transition-all duration-300 font-label-md text-label-md uppercase tracking-wider disabled:opacity-50"
          >
            {busy === item.id ? '...' : 'Sanction'}
          </button>
        </div>
      </li>
    {/each}
  </ul>
</div>
