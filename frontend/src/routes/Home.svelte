<script lang="ts">
  import { api, type Graph, type GraphNode } from '../lib/api'
  import { RUNE, type NodeType } from '../lib/theme'
  import { router } from '../lib/router.svelte'
  import { appState, refreshGraph } from '../lib/appstate.svelte'
  import { liveRefresh } from '../lib/useLive.svelte'
  import { fly } from 'svelte/transition'
  import { dur } from '../lib/motion.svelte'
  import Constellation from '../components/Constellation.svelte'
  import NodeDetailPanel from '../components/NodeDetailPanel.svelte'
  import KnowledgeScribe from '../components/KnowledgeScribe.svelte'

  const ALL_TYPES: NodeType[] = ['project', 'document', 'memory', 'entity']

  let graph = $state<Graph | null>(null)
  let error = $state<string | null>(null)
  let selected = $state<GraphNode | null>(null)
  let query = $state('')
  let hidden = $state<Set<NodeType>>(new Set())
  let showFilter = $state(false)
  // Focus mode: the default view is one node's local neighbourhood, not the whole
  // hairball. The global view stays behind the "All" toggle.
  let mode = $state<'focus' | 'all'>('focus')
  let focusId = $state<string | null>(null)
  let depth = $state(1)

  const highlightType = $derived((router.query.type as NodeType | undefined) ?? null)

  // Land on the most recently active quest line's local view (nodes arrive ordered by
  // updated_at DESC). If the focused node vanished (deleted), refocus the same way.
  $effect(() => {
    if (!graph) return
    if (focusId && graph.nodes.some((n) => n.id === focusId)) return
    const recent = graph.nodes.find((n) => n.type === 'project')
    if (recent) {
      focusId = recent.id
    } else {
      focusId = null
      mode = 'all'
    }
  })

  // The focus neighbourhood: BFS out to `depth` hops, undirected, with the same entity
  // supernode cap as retrieval, so a shared rune never bridges unrelated clusters
  // (unless it is itself the focus).
  const focusIds = $derived.by(() => {
    if (mode !== 'focus' || !focusId || !graph) return null
    const typeById = new Map(graph.nodes.map((n) => [n.id, n.type]))
    const adj = new Map<string, string[]>()
    const add = (a: string, b: string) => {
      const list = adj.get(a)
      if (list) list.push(b)
      else adj.set(a, [b])
    }
    for (const e of graph.edges) {
      add(e.src, e.dst)
      add(e.dst, e.src)
    }
    const seen = new Set<string>([focusId])
    let frontier = [focusId]
    for (let d = 0; d < depth; d++) {
      const next: string[] = []
      for (const id of frontier) {
        if (id !== focusId && typeById.get(id) === 'entity') continue
        for (const nb of adj.get(id) ?? []) {
          if (!seen.has(nb)) {
            seen.add(nb)
            next.push(nb)
          }
        }
      }
      frontier = next
    }
    return seen
  })

  const focusTitle = $derived(
    focusId && graph ? (graph.nodes.find((n) => n.id === focusId)?.title ?? null) : null,
  )

  // Clicking a node opens its panel and, in focus mode, recenters the local view on it
  // (the Obsidian local-graph behaviour).
  function handleSelect(node: GraphNode) {
    selected = node
    if (mode === 'focus') focusId = node.id
  }

  // Refetch on first mount and whenever a write bumps the graph version.
  $effect(() => {
    appState.graphVersion
    api.graph().then((g) => (graph = g)).catch((e) => (error = String(e)))
  })
  // Live updates of the constellation (new/removed nodes appear without a reload).
  liveRefresh(() => api.graph().then((g) => (graph = g)).catch(() => {}))

  const connections = $derived.by(() => {
    if (!graph || !selected) return 0
    return graph.edges.filter((e) => e.src === selected!.id || e.dst === selected!.id).length
  })

  const selectedEdges = $derived.by(() => {
    if (!graph || !selected) return []
    return graph.edges
      .filter((e) => e.src === selected!.id || e.dst === selected!.id)
      .map((e) => {
        const otherId = e.src === selected!.id ? e.dst : e.src
        const other = graph!.nodes.find((n) => n.id === otherId)
        return { ...e, otherTitle: other?.title ?? otherId }
      })
  })

  function toggleType(t: NodeType) {
    const next = new Set(hidden)
    next.has(t) ? next.delete(t) : next.add(t)
    hidden = next
  }

  async function runSearch(e: Event) {
    e.preventDefault()
    if (!graph || !query.trim()) return
    try {
      const { results } = await api.search(query.trim())
      for (const r of results) {
        const node = graph.nodes.find((n) => n.id === r.node_id)
        if (node) {
          selected = node
          return
        }
      }
    } catch {
      /* retrieval unavailable: the live type-filter already narrowed the graph */
    }
  }

  async function prune(edge: { src: string; dst: string; rel: string }) {
    await api.deleteEdge(edge.src, edge.dst, edge.rel)
    refreshGraph()
  }

  async function deleteNode(node: GraphNode) {
    await api.deleteNode(node.id)
    selected = null
    refreshGraph()
  }
</script>

<main class="relative w-full h-[calc(100vh-3.5rem)] md:h-screen bg-bg-page overflow-hidden">
  <!-- Search overlay + filter -->
  <div class="absolute top-6 md:top-8 left-1/2 -translate-x-1/2 w-full max-w-2xl px-4 z-30">
    <form
      onsubmit={runSearch}
      class="relative bg-bg-panel/80 backdrop-blur-md border border-border-default rounded-full shadow-[0_4px_30px_rgba(0,0,0,0.5)] flex items-center px-4 py-3 group focus-within:border-rune-quest focus-within:shadow-[0_0_20px_rgba(212,169,63,0.2)] transition-all duration-300"
    >
      <span class="material-symbols-outlined text-text-muted group-focus-within:text-rune-quest transition-colors mr-3">search</span>
      <input
        bind:value={query}
        class="bg-transparent border-none text-on-surface placeholder:text-text-tertiary w-full font-body-md text-body-md outline-none"
        placeholder="Search the grimoire..."
        type="text"
      />
      <button
        type="button"
        onclick={() => (showFilter = !showFilter)}
        class="material-symbols-outlined text-text-muted hover:text-primary ml-3 transition-colors"
        style="color:{hidden.size ? '#d4a93f' : ''}"
        aria-label="Filter node types"
        aria-expanded={showFilter}
      >
        tune
      </button>
    </form>

    {#if showFilter}
      <div transition:fly={{ y: -8, duration: dur(180) }} class="mt-2 ml-auto w-56 bg-bg-panel border border-border-default rounded-lg p-3 shadow-[0_8px_30px_rgba(0,0,0,0.6)] float-right">
        <p class="font-label-md text-label-md text-text-muted uppercase tracking-widest mb-2">Show node types</p>
        {#each ALL_TYPES as t (t)}
          {@const rune = RUNE[t]}
          {@const visible = !hidden.has(t)}
          <button onclick={() => toggleType(t)} class="w-full flex items-center gap-2 py-1.5 text-left" style="opacity:{visible ? 1 : 0.4}">
            <span class="material-symbols-outlined text-[18px]" style="color:{rune.color}">
              {visible ? 'check_box' : 'check_box_outline_blank'}
            </span>
            <span class="font-body-sm text-body-sm text-on-surface">{rune.nav}</span>
          </button>
        {/each}
      </div>
    {/if}
  </div>

  {#if graph && graph.nodes.length > 0}
    <Constellation
      {graph}
      selectedId={selected?.id ?? null}
      {highlightType}
      filterText={query}
      hiddenTypes={hidden}
      {focusIds}
      focusCenterId={mode === 'focus' ? focusId : null}
      colorByCommunity={mode === 'all'}
      communityLabels={graph.communities}
      onSelect={handleSelect}
    />

    <!-- Focus controls: local view vs the whole constellation, plus hop depth -->
    <div class="absolute bottom-6 left-6 z-30 flex items-center gap-3 bg-bg-panel/80 backdrop-blur-md border border-border-default rounded-lg px-3 py-2 shadow-[0_4px_20px_rgba(0,0,0,0.4)]">
      <div class="flex rounded-md overflow-hidden border border-border-default">
        {#each ['focus', 'all'] as const as m (m)}
          <button
            onclick={() => (mode = m)}
            class="px-3 py-1 font-label-md text-label-md transition-colors"
            style="background:{mode === m ? 'rgba(212,169,63,0.14)' : 'transparent'};color:{mode === m ? '#e3d3a0' : '#6b6789'}"
          >
            {m === 'focus' ? 'Focus' : 'All'}
          </button>
        {/each}
      </div>
      {#if mode === 'focus'}
        <label class="flex items-center gap-2 font-label-md text-label-md text-text-muted">
          Depth
          <input type="range" min="1" max="3" step="1" bind:value={depth} class="w-20" style="accent-color:#d4a93f" />
          <span class="text-on-surface w-3 text-center">{depth}</span>
        </label>
        {#if focusTitle}
          <span class="font-body-sm text-body-sm text-text-tertiary max-w-44 truncate">{focusTitle}</span>
        {/if}
      {/if}
    </div>
  {/if}

  {#if selected}
    <NodeDetailPanel node={selected} {connections} edges={selectedEdges} onPrune={prune} onDelete={deleteNode} onClose={() => (selected = null)} />
  {/if}

  {#if !graph && !error}
    <div class="absolute inset-0 flex items-center justify-center">
      <p class="font-headline-md text-headline-md text-text-tertiary animate-pulse">Inscribing the grimoire...</p>
    </div>
  {/if}
  {#if graph && graph.nodes.length === 0}
    <div class="absolute inset-0 flex items-center justify-center text-center px-6">
      <div>
        <p class="font-headline-md text-headline-md text-text-muted">The grimoire is empty</p>
        <p class="font-body-md text-body-md text-text-tertiary mt-2">Scribe your first node to begin the constellation.</p>
      </div>
    </div>
  {/if}
  {#if error}
    <div class="absolute inset-0 flex items-center justify-center text-center px-6">
      <div>
        <p class="font-headline-sm text-headline-sm text-status-error">Could not reach the knowledge service</p>
        <p class="font-body-sm text-body-sm text-text-tertiary mt-2">{error}. Is the API running on :8731?</p>
      </div>
    </div>
  {/if}

  <KnowledgeScribe onScribed={refreshGraph} />
</main>
