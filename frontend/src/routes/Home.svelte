<script lang="ts">
  import { api, type Graph, type GraphNode } from '../lib/api'
  import { RUNE, type NodeType } from '../lib/theme'
  import { router, link } from '../lib/router.svelte'
  import { appState, refreshGraph } from '../lib/appstate.svelte'
  import { liveRefresh } from '../lib/useLive.svelte'
  import { fly } from 'svelte/transition'
  import { dur } from '../lib/motion.svelte'
  import Constellation from '../components/Constellation.svelte'
  import NodeDetailPanel from '../components/NodeDetailPanel.svelte'

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

  // A scope drill-down from the Galaxy: /?index=<id> or /?domain=<id> isolates that
  // partition's member stars. Reuses focus mode, so out-of-scope nodes fade and their
  // cross-scope edges dim, exactly the association-layer treatment the spec asks for.
  const scopeSel = $derived.by(() => {
    if (!graph) return null
    const indexId = router.query.index
    const domainId = router.query.domain
    if (indexId) {
      const node = graph.nodes.find((n) => n.id === indexId)
      return {
        kind: 'index' as const, id: indexId, title: node?.title ?? 'index',
        domainId: node?.domain_id ?? null,
        members: new Set(graph.nodes.filter((n) => n.index_id === indexId).map((n) => n.id)),
      }
    }
    if (domainId) {
      const node = graph.nodes.find((n) => n.id === domainId)
      return {
        kind: 'domain' as const, id: domainId, title: node?.title ?? 'domain', domainId,
        members: new Set(graph.nodes.filter((n) => n.domain_id === domainId).map((n) => n.id)),
      }
    }
    return null
  })

  const scopeDomainTitle = $derived.by(() =>
    graph && scopeSel?.domainId ? (graph.nodes.find((n) => n.id === scopeSel!.domainId)?.title ?? null) : null,
  )

  // The constellation renders content nodes only; domain/index scope rows are navigated
  // via the Galaxy and carry no rune colour.
  const contentGraph = $derived.by(() =>
    graph ? { ...graph, nodes: graph.nodes.filter((n) => (n.node_kind ?? 'node') === 'node') } : null,
  )

  // Focus mode shows everything until the user clicks a node - nothing is auto-chosen.
  // If the focused node vanished (deleted elsewhere), zoom back out to the whole graph.
  $effect(() => {
    if (!graph || !focusId) return
    if (!graph.nodes.some((n) => n.id === focusId)) focusId = null
  })

  // Clear a stale selection: if another client deleted the selected node, the refreshed
  // graph no longer contains it, so drop it before the detail panel's delete button gets
  // a chance to 404 against a node that no longer exists.
  $effect(() => {
    if (!graph || !selected) return
    if (!graph.nodes.some((n) => n.id === selected!.id)) selected = null
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

  // Clicking a node always opens its details. In focus mode it ALSO zooms into that
  // node's neighbourhood (the hops, sized by the depth slider); in All mode the camera
  // never moves. Switching to All zooms back out and clears the focus.
  function handleSelect(node: GraphNode) {
    selected = node
    if (mode === 'focus') focusId = node.id
  }

  function setMode(m: 'focus' | 'all') {
    mode = m
    if (m === 'all') focusId = null
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

<main class="relative w-full h-screen bg-bg-page overflow-hidden">
  <!-- Focus slider pill, beside the nav pill on the top row (drops below it when the
       viewport is too narrow to share the row) -->
  {#if graph && graph.nodes.length > 0}
    <div
      title="Focus: click a node to zoom into its neighbourhood (hops set by depth). All: see everything; clicking only shows details."
      class="fixed right-4 top-[4.75rem] xl:top-4 z-40 flex items-center gap-2 rounded-full bg-bg-panel/85 backdrop-blur-md border border-border-default p-1 shadow-[0_4px_20px_rgba(0,0,0,0.4)]"
    >
      <div class="relative flex">
        <div
          aria-hidden="true"
          class="absolute top-0 bottom-0 w-1/2 rounded-full bg-rune-quest/15 border border-rune-quest/40 transition-[left] duration-200"
          style="left:{mode === 'focus' ? '0%' : '50%'}"
        ></div>
        {#each ['focus', 'all'] as const as m (m)}
          <button
            onclick={() => setMode(m)}
            aria-pressed={mode === m}
            class="relative w-16 py-1.5 rounded-full font-label-md text-label-md transition-colors"
            style="color:{mode === m ? '#e3d3a0' : '#9b96b8'}"
          >
            {m === 'focus' ? 'Focus' : 'All'}
          </button>
        {/each}
      </div>
      {#if mode === 'focus'}
        <label class="flex items-center gap-2 pr-3 pl-1 font-label-md text-label-md text-text-muted">
          Depth
          <input type="range" min="1" max="3" step="1" bind:value={depth} class="w-16" style="accent-color:#d4a93f" />
          <span class="text-on-surface w-3 text-center">{depth}</span>
        </label>
      {/if}
    </div>
  {/if}

  <!-- Search lives at the bottom, where the scribe bar used to be -->
  <div class="fixed bottom-6 left-1/2 -translate-x-1/2 w-full max-w-xl px-4 z-30">
    <div class="relative">
      {#if showFilter}
        <div transition:fly={{ y: 8, duration: dur(180) }} class="absolute bottom-full right-0 mb-2 w-56 bg-bg-panel border border-border-default rounded-lg p-3 shadow-[0_8px_30px_rgba(0,0,0,0.6)]">
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
          <p class="font-label-md text-label-md text-text-muted uppercase tracking-widest mt-3 mb-2">Emphasize</p>
          <div class="flex gap-1.5">
            {#each ALL_TYPES as t (t)}
              {@const rune = RUNE[t]}
              {@const on = highlightType === t}
              <a
                href={link(on ? '/' : `/?type=${t}`)}
                title={rune.nav}
                aria-label="Emphasize {rune.nav}"
                class="w-8 h-8 rounded-full border flex items-center justify-center transition-colors"
                style="border-color:{on ? rune.color : '#29263f'};background:{on ? rune.color + '22' : 'transparent'}"
              >
                <span class="material-symbols-outlined text-[16px]" style="color:{rune.color}">{rune.icon}</span>
              </a>
            {/each}
          </div>
        </div>
      {/if}
      <form
        onsubmit={runSearch}
        class="relative bg-bg-panel/80 backdrop-blur-md border border-border-default rounded-full shadow-[0_4px_30px_rgba(0,0,0,0.5)] flex items-center px-4 py-2.5 group focus-within:border-rune-quest focus-within:shadow-[0_0_20px_rgba(212,169,63,0.2)] transition-all duration-300"
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
    </div>
  </div>

  {#if scopeSel}
    <div class="fixed left-4 top-[4.75rem] xl:top-4 z-40 flex items-center gap-1.5 rounded-full bg-bg-panel/85 backdrop-blur-md border border-border-default px-3 py-1.5 shadow-[0_4px_20px_rgba(0,0,0,0.4)] font-label-md text-label-md">
      <a href={link('/galaxy')} class="text-text-muted hover:text-primary uppercase tracking-widest">Galaxy</a>
      {#if scopeSel.kind === 'index' && scopeDomainTitle}
        <span class="text-text-tertiary">/</span>
        <a href={link(`/?domain=${scopeSel.domainId}`)} class="text-text-muted hover:text-primary">{scopeDomainTitle}</a>
      {/if}
      <span class="text-text-tertiary">/</span>
      <span class="text-primary">{scopeSel.title}</span>
      <a href={link('/')} class="ml-1 text-text-muted hover:text-primary flex items-center" title="Clear filter" aria-label="Clear scope filter">
        <span class="material-symbols-outlined text-[16px]">close</span>
      </a>
    </div>
  {/if}

  {#if contentGraph && contentGraph.nodes.length > 0}
    <Constellation
      graph={contentGraph}
      selectedId={selected?.id ?? null}
      {highlightType}
      filterText={query}
      hiddenTypes={hidden}
      focusIds={scopeSel ? scopeSel.members : focusIds}
      focusCenterId={scopeSel ? null : (mode === 'focus' ? focusId : null)}
      colorByCommunity={mode === 'all' && !scopeSel}
      communityLabels={graph?.communities}
      onSelect={handleSelect}
    />
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
</main>
