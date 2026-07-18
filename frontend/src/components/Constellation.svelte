<script lang="ts">
  import { untrack } from 'svelte'
  import { forceCollide, forceLink, forceManyBody, forceSimulation } from 'd3'
  import { api, type Graph, type GraphNode } from '../lib/api'
  import { RUNE, edgeColor, type NodeType } from '../lib/theme'

  interface SimNode extends GraphNode {
    x: number
    y: number
    fx?: number | null
    fy?: number | null
  }
  interface SimLink {
    source: SimNode
    target: SimNode
    rel: string
  }

  const RADIUS: Record<NodeType, number> = { project: 30, memory: 20, document: 19, entity: 17 }
  const TAU = Math.PI * 2

  // Anchors are the fixed spine of the constellation; leaves settle around them and
  // freeze. Projects (quest lines) are the only anchor type in this graph.
  const isAnchor = (n: GraphNode) => n.type === 'project'

  // Edge stiffness by relationship: tight and strong for ownership so leaves hug their
  // quest line; loose and weak for cross-references so they do not collapse clusters.
  const EDGE_STIFFNESS: Record<string, { distance: number; strength: number }> = {
    belongs_to: { distance: 46, strength: 0.9 },
    mentions: { distance: 85, strength: 0.5 },
    derived_from: { distance: 85, strength: 0.5 },
    references: { distance: 160, strength: 0.1 },
  }
  const DEFAULT_STIFFNESS = { distance: 95, strength: 0.4 }

  // Tick budgets: a first-ever layout settles long; adding nodes to a saved layout only
  // re-settles the newcomers (everything saved is pinned during the pass).
  const FULL_TICKS = 300
  const INCREMENTAL_TICKS = 120

  let {
    graph,
    selectedId,
    highlightType,
    filterText = '',
    hiddenTypes,
    onSelect,
  }: {
    graph: Graph
    selectedId: string | null
    highlightType: NodeType | null
    filterText?: string
    hiddenTypes?: Set<NodeType>
    onSelect: (node: GraphNode) => void
  } = $props()

  let canvas = $state<HTMLCanvasElement>()

  // Everything below is deliberately NON-reactive. Canvas draws imperatively; Svelte
  // never touches the render path, so hundreds of nodes stay cheap and an idle graph
  // costs zero repaints (the render loop is event-driven, not a permanent rAF).
  let ctx: CanvasRenderingContext2D | null = null
  let nodes: SimNode[] = []
  let links: SimLink[] = []
  // Positions computed this session (id -> {x,y,pinned}). Bridges the gap between a
  // settle/drag and the server round trip, so a live graph refetch never snaps
  // freshly placed nodes back to an un-laid-out state.
  const posMap = new Map<string, { x: number; y: number; pinned: boolean }>()
  let cssW = 800
  let cssH = 600
  const cam = { x: 0, y: 0, k: 1 } // screen = graph * k + (x,y)
  let fontReady = false
  let rafPending = false

  // Precomputed soft-glow sprites, one per rune colour, drawn additively. Building the
  // gradient once (not per node per frame) is what keeps the glow cheap.
  const halo: Partial<Record<NodeType, HTMLCanvasElement>> = {}

  function rgba(hex: string, a: number): string {
    const n = parseInt(hex.slice(1), 16)
    return `rgba(${(n >> 16) & 255},${(n >> 8) & 255},${n & 255},${a})`
  }

  function buildHalos() {
    for (const type of Object.keys(RUNE) as NodeType[]) {
      const c = document.createElement('canvas')
      c.width = c.height = 64
      const g = c.getContext('2d')!
      const grad = g.createRadialGradient(32, 32, 4, 32, 32, 32)
      grad.addColorStop(0, rgba(RUNE[type].color, 0.55))
      grad.addColorStop(1, rgba(RUNE[type].color, 0))
      g.fillStyle = grad
      g.fillRect(0, 0, 64, 64)
      halo[type] = c
    }
  }

  function scheduleDraw() {
    if (rafPending) return
    rafPending = true
    requestAnimationFrame(draw)
  }

  function toGraph(clientX: number, clientY: number) {
    const r = canvas!.getBoundingClientRect()
    return { x: (clientX - r.left - cam.x) / cam.k, y: (clientY - r.top - cam.y) / cam.k }
  }

  function nodeAt(clientX: number, clientY: number): SimNode | null {
    const p = toGraph(clientX, clientY)
    // topmost first
    for (let i = nodes.length - 1; i >= 0; i--) {
      const n = nodes[i]
      if (hiddenTypes?.has(n.type)) continue
      const dx = p.x - n.x
      const dy = p.y - n.y
      if (dx * dx + dy * dy <= RADIUS[n.type] * RADIUS[n.type]) return n
    }
    return null
  }

  function draw() {
    rafPending = false
    if (!ctx) return
    const dpr = window.devicePixelRatio || 1
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0)
    ctx.clearRect(0, 0, cssW, cssH)
    ctx.translate(cam.x, cam.y)
    ctx.scale(cam.k, cam.k)

    const q = (filterText ?? '').trim().toLowerCase()
    const vis = (n: SimNode) => !hiddenTypes?.has(n.type)
    const matched = (n: SimNode) =>
      vis(n) && (!highlightType || n.type === highlightType) && (!q || n.title.toLowerCase().includes(q))

    // edges
    ctx.lineWidth = 1.2
    for (const l of links) {
      const s = l.source
      const t = l.target
      if (!s || !t || !vis(s) || !vis(t)) continue
      ctx.globalAlpha = matched(s) && matched(t) ? 0.3 : 0.07
      ctx.strokeStyle = edgeColor(s.type, t.type)
      ctx.beginPath()
      ctx.moveTo(s.x, s.y)
      ctx.lineTo(t.x, t.y)
      ctx.stroke()
    }
    ctx.globalAlpha = 1

    // additive glow pass
    ctx.globalCompositeOperation = 'lighter'
    for (const n of nodes) {
      if (!vis(n) || !matched(n)) continue
      const r = RADIUS[n.type]
      const hot = n.id === selectedId || n.id === hoverId
      const size = r * (hot ? 4.4 : 3.4)
      ctx.globalAlpha = hot ? 0.9 : 0.5
      const sprite = halo[n.type]
      if (sprite) ctx.drawImage(sprite, n.x - size / 2, n.y - size / 2, size, size)
    }
    ctx.globalCompositeOperation = 'source-over'
    ctx.globalAlpha = 1

    // nodes
    ctx.textAlign = 'center'
    ctx.textBaseline = 'middle'
    for (const n of nodes) {
      if (!vis(n)) continue
      const r = RADIUS[n.type]
      const sel = n.id === selectedId
      const dim = !matched(n)
      const color = RUNE[n.type].color
      ctx.globalAlpha = dim ? 0.18 : 1

      ctx.beginPath()
      ctx.arc(n.x, n.y, r, 0, TAU)
      ctx.fillStyle = '#0e0d16'
      ctx.fill()
      ctx.lineWidth = sel ? 3 : n.id === hoverId ? 2.4 : 1.6
      ctx.strokeStyle = color
      ctx.stroke()

      // unreviewed = dashed outer ring (status as a static mark, no animation, so idle
      // stays repaint-free — the smoothness trade the SVG pulse could not make).
      if (n.status === 'unreviewed') {
        ctx.save()
        ctx.setLineDash([3, 3])
        ctx.lineWidth = 1
        ctx.globalAlpha = dim ? 0.18 : 0.7
        ctx.beginPath()
        ctx.arc(n.x, n.y, r + 4, 0, TAU)
        ctx.stroke()
        ctx.restore()
      }

      if (fontReady) {
        ctx.fillStyle = color
        ctx.font = `${Math.round(r * 0.9)}px "Material Symbols Outlined"`
        ctx.fillText(RUNE[n.type].icon, n.x, n.y + 1)
      }

      // Declutter: only the spine (projects), the selected/hovered node, and a zoomed-in
      // view show labels. The hovered/selected label gets a dark backdrop so it stays
      // legible over edges and neighbours.
      const hot = sel || n.id === hoverId
      if (hot || n.type === 'project' || cam.k >= 1.1) {
        const label = n.title.length > 22 ? n.title.slice(0, 21) + '…' : n.title
        ctx.font = '11px "Spectral", sans-serif'
        const ly = n.y + r + 12
        if (hot) {
          const tw = ctx.measureText(label).width
          ctx.globalAlpha = 1
          ctx.fillStyle = 'rgba(12,11,20,0.82)'
          ctx.beginPath()
          ctx.roundRect(n.x - tw / 2 - 5, ly - 9, tw + 10, 17, 3)
          ctx.fill()
          ctx.fillStyle = '#e5e0ee'
        } else {
          ctx.fillStyle = '#cdc6b7'
        }
        ctx.fillText(label, n.x, ly)
      }
    }
    ctx.globalAlpha = 1
  }

  // ---- interaction --------------------------------------------------------------
  let dragging: SimNode | null = null
  let mode = $state<'pan' | 'drag' | null>(null) // read in the template (cursor)
  let hoverId = $state<string | null>(null) // node under the cursor (cursor + emphasis)
  let last = { x: 0, y: 0 }
  let downAt = { x: 0, y: 0 }
  let moved = false

  function onWheel(e: WheelEvent) {
    e.preventDefault()
    const r = canvas!.getBoundingClientRect()
    const mx = e.clientX - r.left
    const my = e.clientY - r.top
    const k2 = Math.max(0.2, Math.min(3, cam.k * Math.exp(-e.deltaY * 0.0015)))
    cam.x = mx - (mx - cam.x) * (k2 / cam.k)
    cam.y = my - (my - cam.y) * (k2 / cam.k)
    cam.k = k2
    scheduleDraw()
  }

  function onPointerDown(e: PointerEvent) {
    downAt = { x: e.clientX, y: e.clientY }
    moved = false
    const n = nodeAt(e.clientX, e.clientY)
    if (n) {
      mode = 'drag'
      dragging = n
    } else {
      mode = 'pan'
      last = { x: e.clientX, y: e.clientY }
    }
    canvas!.setPointerCapture(e.pointerId)
  }

  function onPointerMove(e: PointerEvent) {
    if (mode) {
      if (Math.hypot(e.clientX - downAt.x, e.clientY - downAt.y) > 4) moved = true
      if (mode === 'drag' && dragging) {
        // The graph is frozen: only the dragged node moves, nothing else reflows.
        const g = toGraph(e.clientX, e.clientY)
        dragging.x = dragging.fx = g.x
        dragging.y = dragging.fy = g.y
        scheduleDraw()
      } else if (mode === 'pan') {
        cam.x += e.clientX - last.x
        cam.y += e.clientY - last.y
        last = { x: e.clientX, y: e.clientY }
        scheduleDraw()
      }
      return
    }
    // Hover (no button held): highlight the node under the cursor + reveal its label.
    const id = nodeAt(e.clientX, e.clientY)?.id ?? null
    if (id !== hoverId) {
      hoverId = id
      scheduleDraw()
    }
  }

  function onPointerLeave() {
    if (hoverId !== null) {
      hoverId = null
      scheduleDraw()
    }
  }

  function onPointerUp() {
    if (mode === 'drag' && dragging) {
      if (moved) {
        // Persist the drop as pinned so a reload restores exactly this position.
        dragging.fx = dragging.x
        dragging.fy = dragging.y
        posMap.set(dragging.id, { x: dragging.x, y: dragging.y, pinned: true })
        api.saveLayout([{ node_id: dragging.id, x: dragging.x, y: dragging.y, pinned: true }]).catch(() => {})
      } else {
        if (!isAnchor(dragging) && !posMap.get(dragging.id)?.pinned) {
          dragging.fx = null
          dragging.fy = null
        }
        onSelect(dragging)
      }
    }
    mode = null
    dragging = null
  }

  // ---- lifecycle ----------------------------------------------------------------
  // Content signature: rebuild only when nodes/edges actually change.
  const sig = $derived(
    graph.nodes.map((n) => `${n.id}:${n.status}`).sort().join(',') +
      '|' +
      graph.edges.map((e) => `${e.src}>${e.dst}`).sort().join(','),
  )

  // Mount: context, halos, fonts, sizing.
  $effect(() => {
    if (!canvas) return
    ctx = canvas.getContext('2d')
    buildHalos()

    // Resize only re-rasterizes and redraws — the layout is frozen, so nothing reflows.
    const ro = new ResizeObserver(() => {
      const r = canvas!.getBoundingClientRect()
      cssW = r.width
      cssH = r.height
      const dpr = window.devicePixelRatio || 1
      canvas!.width = Math.round(cssW * dpr)
      canvas!.height = Math.round(cssH * dpr)
      scheduleDraw()
    })
    ro.observe(canvas)

    document.fonts.ready.then(() => {
      fontReady = true
      scheduleDraw()
    })

    return () => ro.disconnect()
  })

  // Lay the graph out when its content changes: anchors pinned at saved (or
  // deterministic) coordinates, leaves restored from the saved layout, and only nodes
  // WITHOUT a saved position settled by a bounded synchronous tick run. The simulation
  // never runs live: after this effect the graph is frozen until the user drags a node.
  $effect(() => {
    sig
    const g = untrack(() => graph)
    if (!ctx) return
    if (canvas) {
      const r = canvas.getBoundingClientRect()
      if (r.width > 0) {
        cssW = r.width
        cssH = r.height
      }
    }

    // Effective saved positions: this session's fresh placements win over the server's.
    const saved = new Map<string, { x: number; y: number; pinned: boolean }>()
    for (const [id, p] of Object.entries(g.layout ?? {})) saved.set(id, p)
    for (const [id, p] of posMap) saved.set(id, p)

    nodes = g.nodes.map((n) => ({ ...n, x: 0, y: 0 })) as SimNode[]
    const byId = new Map(nodes.map((n) => [n.id, n]))
    links = g.edges
      .filter((e) => byId.has(e.src) && byId.has(e.dst))
      .map((e) => ({ source: e.src as unknown as SimNode, target: e.dst as unknown as SimNode, rel: e.rel }))

    const cx = cssW / 2
    const cy = cssH / 2
    // Parent anchor per leaf, so new leaves spawn where they belong.
    const parentOf = new Map<string, string>()
    for (const e of g.edges) {
      if (e.rel !== 'belongs_to') continue
      const dst = byId.get(e.dst)
      if (dst && isAnchor(dst)) parentOf.set(e.src, e.dst)
    }

    const anchors = nodes.filter(isAnchor).sort((a, b) => (a.id < b.id ? -1 : 1))
    const ring = Math.max(180, anchors.length * 55)
    anchors.forEach((n, i) => {
      const s = saved.get(n.id)
      if (s) {
        n.x = s.x
        n.y = s.y
      } else {
        const angle = (i / Math.max(1, anchors.length)) * TAU
        n.x = cx + Math.cos(angle) * ring
        n.y = cy + Math.sin(angle) * ring
      }
      n.fx = n.x // anchors are always fixed
      n.fy = n.y
    })

    let newCount = 0
    for (const n of nodes) {
      if (isAnchor(n)) continue
      const s = saved.get(n.id)
      if (s) {
        n.x = s.x
        n.y = s.y
        n.fx = s.x // temporary pin while newcomers settle; released below
        n.fy = s.y
      } else {
        newCount++
        const p = parentOf.get(n.id) ? byId.get(parentOf.get(n.id)!) : undefined
        // Deterministic small offset (hash of id) so a re-render is stable pre-settle.
        const seed = n.id.charCodeAt(0) + n.id.charCodeAt(n.id.length - 1)
        n.x = (p?.x ?? cx) + Math.cos(seed) * 40
        n.y = (p?.y ?? cy) + Math.sin(seed) * 40
      }
    }

    if (newCount > 0) {
      const sim = forceSimulation<SimNode>(nodes)
        .force(
          'link',
          forceLink<SimNode, SimLink>(links)
            .id((d: any) => d.id)
            .distance((l) => (EDGE_STIFFNESS[l.rel] ?? DEFAULT_STIFFNESS).distance)
            .strength((l) => (EDGE_STIFFNESS[l.rel] ?? DEFAULT_STIFFNESS).strength),
        )
        .force('charge', forceManyBody<SimNode>().strength(-320))
        .force('collide', forceCollide<SimNode>((d) => RADIUS[d.type] + 14))
        .stop()
      const ticks = saved.size === 0 ? FULL_TICKS : INCREMENTAL_TICKS
      for (let i = 0; i < ticks; i++) sim.tick()
      sim.stop()

      // Record every position (anchors and user-pinned leaves stay pinned) and persist.
      const batch: { node_id: string; x: number; y: number; pinned: boolean }[] = []
      for (const n of nodes) {
        const pinned = isAnchor(n) || (saved.get(n.id)?.pinned ?? false)
        posMap.set(n.id, { x: n.x, y: n.y, pinned })
        batch.push({ node_id: n.id, x: n.x, y: n.y, pinned })
      }
      api.saveLayout(batch).catch(() => {})
    }

    // Release the temporary pins on unpinned leaves so a drag can move them freely.
    for (const n of nodes) {
      if (isAnchor(n)) continue
      if (!(saved.get(n.id)?.pinned ?? false) && !posMap.get(n.id)?.pinned) {
        n.fx = null
        n.fy = null
      }
    }

    scheduleDraw()
  })

  // Restyle (selection / highlight / filter) is just a redraw — no relayout.
  $effect(() => {
    selectedId
    highlightType
    filterText
    hiddenTypes
    scheduleDraw()
  })
</script>

<canvas
  bind:this={canvas}
  class="absolute inset-0 w-full h-full touch-none {mode === 'pan' ? 'cursor-grabbing' : hoverId ? 'cursor-pointer' : 'cursor-grab'}"
  aria-label="Knowledge constellation"
  onwheel={onWheel}
  onpointerdown={onPointerDown}
  onpointermove={onPointerMove}
  onpointerup={onPointerUp}
  onpointercancel={onPointerUp}
  onpointerleave={onPointerLeave}
></canvas>
