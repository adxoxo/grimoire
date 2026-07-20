<script lang="ts">
  import { api, type InboxItem, type ScopeTree } from '../lib/api'
  import { RUNE, SCOPE } from '../lib/theme'
  import { link } from '../lib/router.svelte'
  import { refreshGraph } from '../lib/appstate.svelte'
  import { liveRefresh } from '../lib/useLive.svelte'

  // The primary human-in-the-loop surface outside chat: unclassified nodes, each with
  // the AI's proposed placement pre-selected, filed into an index with one click.
  let items = $state<InboxItem[] | null>(null)
  let scopes = $state<ScopeTree | null>(null)
  let error = $state<string | null>(null)
  let busy = $state<string | null>(null)
  // The chosen index per row (defaults to the proposal); keyed by node id.
  let choice = $state<Record<string, string>>({})

  // Inline scope creation.
  let newDomain = $state('')
  let newIndexTitle = $state('')
  let newIndexDomain = $state('')
  let creating = $state(false)

  function load() {
    Promise.all([api.inbox(), api.scopes()])
      .then(([inb, sc]) => {
        items = inb.items
        scopes = sc
        for (const it of inb.items) {
          if (choice[it.id] === undefined) choice[it.id] = it.proposal?.proposed.index_id ?? ''
        }
      })
      .catch((e) => (error = String(e)))
  }
  $effect(load)
  liveRefresh(load, { enabled: () => busy === null && !creating })

  const hasIndexes = $derived((scopes?.domains ?? []).some((d) => d.indexes.length > 0))

  async function file(id: string) {
    const indexId = choice[id]
    if (!indexId) return
    busy = id
    try {
      await api.classifyNode(id, indexId)
      items = items ? items.filter((i) => i.id !== id) : items
      refreshGraph()
    } catch (e) {
      error = String(e)
    } finally {
      busy = null
    }
  }

  async function createDomain() {
    const title = newDomain.trim()
    if (!title) return
    creating = true
    try {
      const d = await api.createDomain(title)
      newDomain = ''
      newIndexDomain = d.id
      await reloadScopes()
    } finally {
      creating = false
    }
  }

  async function createIndex() {
    const title = newIndexTitle.trim()
    if (!title || !newIndexDomain) return
    creating = true
    try {
      await api.createIndex(newIndexDomain, title)
      newIndexTitle = ''
      await reloadScopes()
    } finally {
      creating = false
    }
  }

  async function reloadScopes() {
    scopes = await api.scopes()
    refreshGraph()
  }
</script>

<div class="min-h-screen overflow-y-auto px-margin py-lg max-w-3xl mx-auto">
  <a href={link('/')} class="font-label-md text-label-md text-text-muted hover:text-primary uppercase tracking-widest inline-flex items-center gap-1">
    <span class="material-symbols-outlined text-[16px]">arrow_back</span> Constellation
  </a>

  <header class="mt-6 mb-lg flex items-center gap-3 border-b border-border-subtle pb-6">
    <span class="material-symbols-outlined text-primary-container text-[32px]" style="filter:drop-shadow(0 0 8px #d4a93f)">move_to_inbox</span>
    <div>
      <span class="font-label-md text-label-md text-primary-container uppercase tracking-widest">Classification inbox</span>
      <h1 class="font-headline-lg text-headline-lg text-primary leading-none">Awaiting a home</h1>
    </div>
    {#if items}
      <span class="ml-auto font-body-sm text-body-sm text-text-tertiary">{items.length} unclassified</span>
    {/if}
  </header>

  <!-- Scope creation: an index (grouped under a domain) is the unit of filing. -->
  <section class="mb-lg grid gap-3 sm:grid-cols-2">
    <div class="bg-bg-panel border border-border-default rounded-lg p-4">
      <div class="flex items-center gap-2 mb-2">
        <span class="material-symbols-outlined text-[18px]" style="color:{SCOPE.domain.color}">{SCOPE.domain.icon}</span>
        <span class="font-label-md text-label-md uppercase tracking-wider" style="color:{SCOPE.domain.color}">New domain</span>
      </div>
      <div class="flex gap-2">
        <input bind:value={newDomain} placeholder="e.g. Content automation"
          class="flex-1 min-w-0 bg-bg-surface border border-border-default rounded px-3 py-1.5 font-body-sm text-body-sm text-on-surface" />
        <button onclick={createDomain} disabled={creating || !newDomain.trim()}
          class="px-3 py-1.5 border border-primary-container text-primary-container rounded font-label-md text-label-md uppercase tracking-wider disabled:opacity-40">Add</button>
      </div>
    </div>
    <div class="bg-bg-panel border border-border-default rounded-lg p-4">
      <div class="flex items-center gap-2 mb-2">
        <span class="material-symbols-outlined text-[18px]" style="color:{SCOPE.index.color}">{SCOPE.index.icon}</span>
        <span class="font-label-md text-label-md uppercase tracking-wider" style="color:{SCOPE.index.color}">New index</span>
      </div>
      <div class="flex gap-2">
        <select bind:value={newIndexDomain}
          class="min-w-0 bg-bg-surface border border-border-default rounded px-2 py-1.5 font-body-sm text-body-sm text-on-surface">
          <option value="">Domain…</option>
          {#each scopes?.domains ?? [] as d (d.id)}
            <option value={d.id}>{d.title}</option>
          {/each}
        </select>
        <input bind:value={newIndexTitle} placeholder="e.g. YouTube"
          class="flex-1 min-w-0 bg-bg-surface border border-border-default rounded px-3 py-1.5 font-body-sm text-body-sm text-on-surface" />
        <button onclick={createIndex} disabled={creating || !newIndexTitle.trim() || !newIndexDomain}
          class="px-3 py-1.5 border border-primary-container text-primary-container rounded font-label-md text-label-md uppercase tracking-wider disabled:opacity-40">Add</button>
      </div>
    </div>
  </section>

  {#if error}
    <p class="font-body-sm text-body-sm text-status-error mb-3">{error}</p>
  {/if}
  {#if !items && !error}
    <p class="font-headline-md text-headline-md text-text-tertiary animate-pulse">Gathering the unfiled...</p>
  {/if}
  {#if items && items.length === 0}
    <p class="font-body-lg text-body-lg text-text-tertiary">The inbox is clear. Every node has a home.</p>
  {/if}
  {#if items && items.length > 0 && !hasIndexes}
    <p class="font-body-sm text-body-sm text-text-muted mb-3">Create a domain and an index above before filing.</p>
  {/if}

  <ul class="space-y-3">
    {#each items ?? [] as item (item.id)}
      {@const rune = RUNE[item.type]}
      <li
        class="bg-bg-panel border border-border-default rounded-lg p-4 border-l-4"
        style="border-left-color:{rune?.color ?? '#9b96b8'}"
      >
        <div class="flex items-start justify-between gap-4">
          <div class="min-w-0">
            <div class="flex items-center gap-2 mb-1">
              <span class="w-2 h-2 rounded-full svg-pulse" style="background-color:{rune?.color}; box-shadow:0 0 8px {rune?.color}"></span>
              <span class="font-label-md text-label-md uppercase tracking-wider" style="color:{rune?.color}">{rune?.label ?? item.type}</span>
            </div>
            <p class="font-body-md text-body-md text-on-surface truncate">{item.title}</p>
            {#if item.context_summary}
              <p class="font-body-sm text-body-sm text-text-muted mt-1 line-clamp-2">{item.context_summary.slice(0, 160)}</p>
            {/if}
            {#if item.proposal}
              <p class="font-body-sm text-body-sm mt-2" style="color:{SCOPE.index.color}">
                <span class="material-symbols-outlined text-[14px] align-middle">auto_awesome</span>
                Suggested: {item.proposal.proposed.domain ?? '—'} / {item.proposal.proposed.index}
                <span class="text-text-tertiary">({Math.round(item.proposal.confidence * 100)}%)</span>
              </p>
            {/if}
          </div>
          <div class="shrink-0 flex flex-col items-end gap-2 w-56">
            <select
              bind:value={choice[item.id]}
              class="w-full bg-bg-surface border border-border-default rounded px-2 py-1.5 font-body-sm text-body-sm text-on-surface"
            >
              <option value="">Choose an index…</option>
              {#each scopes?.domains ?? [] as d (d.id)}
                {#if d.indexes.length}
                  <optgroup label={d.title}>
                    {#each d.indexes as i (i.id)}
                      <option value={i.id}>{i.title}</option>
                    {/each}
                  </optgroup>
                {/if}
              {/each}
            </select>
            <button
              onclick={() => file(item.id)}
              disabled={busy === item.id || !choice[item.id]}
              class="py-1.5 px-4 bg-surface text-primary-container border border-primary-container rounded hover:bg-bg-surface hover:shadow-[0_0_15px_0px_rgba(212,169,63,0.3)] transition-all duration-300 font-label-md text-label-md uppercase tracking-wider disabled:opacity-40"
            >
              {busy === item.id ? '...' : 'File'}
            </button>
          </div>
        </div>
      </li>
    {/each}
  </ul>
</div>
