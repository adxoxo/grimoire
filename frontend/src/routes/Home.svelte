<script lang="ts">
  import { api, type Graph, type GraphNode } from '../lib/api'
  import { RUNE, type NodeType } from '../lib/theme'
  import { router, link, navigate } from '../lib/router.svelte'
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
  // The legacy full-graph escape hatch, reached from any level via "All nodes" and left
  // via the "Galaxy" crumb. It is a local toggle, never a URL, so drilling stays orthogonal.
  let showAll = $state(false)
  // Per-index focus inside the domain view: highlights one index's stars and fits the camera.
  let focusIndexId = $state<string | null>(null)
  // The all-view BFS focus (legacy click-to-zoom), only meaningful while showAll is true.
  let focusId = $state<string | null>(null)

  const highlightType = $derived((router.query.type as NodeType | undefined) ?? null)

  // The drill-down level machine, derived from the URL scope params (+ the local escape
  // hatch). No routes are added: /?domain= and /?index= are query drill-downs of '/'.
  const level = $derived.by(() => {
    if (showAll) return 'all'
    if (router.query.index) return 'index'
    if (router.query.domain) return 'domain'
    return 'galaxy'
  })

  // Client-side partitions of the single graph fetch, by node_kind.
  const domains = $derived(graph ? graph.nodes.filter((n) => n.node_kind === 'domain') : [])
  const indexes = $derived(graph ? graph.nodes.filter((n) => n.node_kind === 'index') : [])
  const content = $derived(graph ? graph.nodes.filter((n) => (n.node_kind ?? 'node') === 'node') : [])

  // Breadcrumb title resolution.
  const currentDomain = $derived.by(() =>
    level === 'domain' ? (domains.find((d) => d.id === router.query.domain) ?? null) : null,
  )
  const currentIndex = $derived.by(() =>
    level === 'index' ? (indexes.find((i) => i.id === router.query.index) ?? null) : null,
  )
  const indexDomain = $derived.by(() =>
    currentIndex?.domain_id ? (domains.find((d) => d.id === currentIndex!.domain_id) ?? null) : null,
  )

  // The all-view focus neighbourhood: BFS out one hop, undirected, with the same entity
  // supernode cap as retrieval so a shared rune never bridges unrelated clusters.
  const allFocusIds = $derived.by(() => {
    if (level !== 'all' || !focusId || !graph) return null
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
    for (let d = 0; d < 1; d++) {
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

  // The Constellation feed for the current level: its own graph partition, anchor spine,
  // focus set, colour mode, and layout-persistence policy.
  const view = $derived.by(() => {
    if (!graph) return null

    if (level === 'galaxy') {
      const nodes = [...domains, ...indexes]
      const edges = indexes
        .filter((i) => i.domain_id)
        .map((i) => ({ src: i.id, dst: i.domain_id!, rel: 'belongs_to', provenance: 'explicit' as const }))
      return {
        graph: { nodes, edges },
        anchorIds: new Set(domains.map((d) => d.id)),
        focusIds: null as Set<string> | null,
        focusCenterId: null as string | null,
        colorByCommunity: false,
        persistLayout: false,
      }
    }

    if (level === 'domain') {
      const id = router.query.domain
      const dIndexes = indexes.filter((i) => i.domain_id === id)
      const dContent = content.filter((c) => c.domain_id === id)
      const nodes = [...dIndexes, ...dContent]
      const setIds = new Set(nodes.map((n) => n.id))
      const realEdges = graph.edges.filter((e) => setIds.has(e.src) && setIds.has(e.dst))
      const membershipEdges = dContent
        .filter((c) => c.index_id && setIds.has(c.index_id))
        .map((c) => ({ src: c.id, dst: c.index_id!, rel: 'belongs_to', provenance: 'explicit' as const }))
      const focusIds = focusIndexId
        ? new Set([focusIndexId, ...dContent.filter((c) => c.index_id === focusIndexId).map((c) => c.id)])
        : null
      return {
        graph: { nodes, edges: [...realEdges, ...membershipEdges] },
        anchorIds: new Set(dIndexes.map((i) => i.id)),
        focusIds: focusIds as Set<string> | null,
        focusCenterId: focusIndexId as string | null,
        colorByCommunity: false,
        persistLayout: false,
      }
    }

    if (level === 'index') {
      const id = router.query.index
      const iContent = content.filter((c) => c.index_id === id)
      const setIds = new Set(iContent.map((n) => n.id))
      const realEdges = graph.edges.filter((e) => setIds.has(e.src) && setIds.has(e.dst))
      return {
        graph: { nodes: iContent, edges: realEdges },
        anchorIds: null as Set<string> | null,
        focusIds: null as Set<string> | null,
        focusCenterId: null as string | null,
        colorByCommunity: false,
        persistLayout: false,
      }
    }

    // all: the legacy canonical view, content only, saved layout, community tint at rest.
    return {
      graph: { ...graph, nodes: content },
      anchorIds: null as Set<string> | null,
      focusIds: allFocusIds,
      focusCenterId: focusId as string | null,
      colorByCommunity: !focusId,
      persistLayout: true,
    }
  })

  // Reset the per-index focus whenever the domain scope changes or we leave the domain level.
  $effect(() => {
    router.query.domain
    level
    focusIndexId = null
  })

  // The all-view BFS focus only lives inside the all view; drop it on the way out so a
  // later re-entry opens on the community tint, not a stale focus.
  $effect(() => {
    if (level !== 'all') focusId = null
  })

  // If the focused/selected node vanished (deleted elsewhere), drop the stale reference.
  $effect(() => {
    if (!graph || !focusId) return
    if (!graph.nodes.some((n) => n.id === focusId)) focusId = null
  })
  $effect(() => {
    if (!graph || !selected) return
    if (!graph.nodes.some((n) => n.id === selected!.id)) selected = null
  })

  // Click behaviour is per level: galaxy/domain navigate or focus; index/all open details.
  function handleSelect(node: GraphNode) {
    if (level === 'galaxy') {
      if (node.node_kind === 'domain') navigate(`/?domain=${node.id}`)
      else if (node.node_kind === 'index') navigate(`/?index=${node.id}`)
      return
    }
    if (level === 'domain') {
      if (node.node_kind === 'index') {
        if (focusIndexId === node.id) navigate(`/?index=${node.id}`)
        else focusIndexId = node.id
      } else {
        selected = node
      }
      return
    }
    if (level === 'index') {
      selected = node
      return
    }
    // all
    selected = node
    focusId = node.id
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
  <!-- Breadcrumb / level pill (top-left), shared floating-pill styling -->
  {#if graph && graph.nodes.length > 0}
    <div class="fixed left-4 top-[4.75rem] xl:top-4 z-40 flex items-center gap-1.5 rounded-full bg-bg-panel/85 backdrop-blur-md border border-border-default px-3 py-1.5 shadow-[0_4px_20px_rgba(0,0,0,0.4)] font-label-md text-label-md">
      {#if level === 'galaxy'}
        <span class="text-primary">Galaxy</span>
        <span class="text-text-tertiary">/</span>
        <a href={link('/galaxy')} class="text-text-muted hover:text-primary">Manage</a>
        <span class="w-px h-3 bg-border-default mx-0.5"></span>
        <button onclick={() => (showAll = true)} class="text-text-muted hover:text-primary">All nodes</button>
      {:else if level === 'domain'}
        <a href={link('/')} class="text-text-muted hover:text-primary">Galaxy</a>
        <span class="text-text-tertiary">/</span>
        <span class="text-primary">{currentDomain?.title ?? 'Domain'}</span>
        <span class="w-px h-3 bg-border-default mx-0.5"></span>
        <button onclick={() => (showAll = true)} class="text-text-muted hover:text-primary">All nodes</button>
      {:else if level === 'index'}
        <a href={link('/')} class="text-text-muted hover:text-primary">Galaxy</a>
        {#if indexDomain}
          <span class="text-text-tertiary">/</span>
          <a href={link(`/?domain=${indexDomain.id}`)} class="text-text-muted hover:text-primary">{indexDomain.title}</a>
        {/if}
        <span class="text-text-tertiary">/</span>
        <span class="text-primary">{currentIndex?.title ?? 'Index'}</span>
      {:else}
        <button onclick={() => (showAll = false)} class="text-text-muted hover:text-primary">Galaxy</button>
        <span class="text-text-tertiary">/</span>
        <span class="text-primary">All nodes</span>
      {/if}
    </div>
  {/if}

  <!-- Search lives at the bottom, where the scribe bar used to be -->
  <div class="fixed bottom-6 left-1/2 -translate-x-1/2 w-full max-w-xl px-4 z-30">
    <div class="relative">
      {#if showFilter}
        <div transition:fly={{ y: 8, duration: dur(180) }} class="absolute bottom-full right-0 mb-2 w-56 bg-bg-panel border border-border-default rounded-lg p-3 shadow-[0_8px_30px_rgba(0,0,0,0.6)]">
          <p class="font-label-md text-label-md text-text-muted mb-2">Show node types</p>
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
          <p class="font-label-md text-label-md text-text-muted mt-3 mb-2">Emphasize</p>
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

  {#if view && view.graph.nodes.length > 0}
    {#key `${level}:${router.query.domain ?? ''}:${router.query.index ?? ''}`}
      <Constellation
        graph={view.graph}
        selectedId={selected?.id ?? null}
        {highlightType}
        filterText={query}
        hiddenTypes={hidden}
        focusIds={view.focusIds}
        focusCenterId={view.focusCenterId}
        colorByCommunity={view.colorByCommunity}
        anchorIds={view.anchorIds}
        persistLayout={view.persistLayout}
        communityLabels={graph?.communities}
        onSelect={handleSelect}
      />
    {/key}
  {/if}

  <!-- Galaxy with content but no taxonomy yet: point the user at Manage to bootstrap it. -->
  {#if level === 'galaxy' && graph && graph.nodes.length > 0 && domains.length === 0}
    <div class="absolute inset-0 flex items-center justify-center text-center px-6">
      <div>
        <p class="font-headline-md text-headline-md text-text-muted">No domains yet.</p>
        <p class="font-body-md text-body-md text-text-tertiary mt-2">
          Create your first domain in <a href={link('/galaxy')} class="text-primary hover:underline">Manage</a>, or bootstrap the taxonomy from your clusters via chat.
        </p>
      </div>
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
</main>
