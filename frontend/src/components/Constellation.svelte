<script lang="ts">
  import { untrack } from 'svelte'
  import { forceCollide, forceLink, forceManyBody, forceSimulation, forceX, forceY } from 'd3'
  import { api, type Graph, type GraphNode } from '../lib/api'
  import { RUNE, communityColor, edgeColor, type NodeType } from '../lib/theme'

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
    inferred: boolean
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
  const INCREMENTAL_TICKS = 80

  let {
    graph,
    selectedId,
    highlightType,
    filterText = '',
    hiddenTypes,
    focusIds = null,
    focusCenterId = null,
    colorByCommunity = false,
    communityLabels,
    onSelect,
  }: {
    graph: Graph
    selectedId: string | null
    highlightType: NodeType | null
    filterText?: string
    hiddenTypes?: Set<NodeType>
    // Focus mode: when set, only these ids render at full strength; the rest fade to
    // near-invisible (and stop taking clicks) instead of unmounting.
    focusIds?: Set<string> | null
    // The node the camera should glide to when focus changes (null = leave the camera).
    focusCenterId?: string | null
    // Global view: tint nodes by Louvain community instead of rune type, and label
    // each cluster at its centroid. Focus mode keeps the four rune colours.
    colorByCommunity?: boolean
    communityLabels?: Record<string, { label: string }>
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

  // Focus fade state (render path, non-reactive). Out-of-scope nodes ease to 10% alpha
  // over FADE_MS instead of vanishing, so refocusing reads as spatial movement. The
  // canvas tweens live outside CSS, so reduced-motion is honoured here explicitly.
  const reducedMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches
  const FADE_MS = reducedMotion ? 0 : 300
  const GLIDE_MS = reducedMotion ? 0 : 450
  const OUT_ALPHA = 0.1
  let focusSet: Set<string> | null = null
  let fadeFrom = new Map<string, number>() // alpha factor per node when the fade began
  let fadeStart = -Infinity

  function focusFactor(id: string, now: number): number {
    const target = !focusSet || focusSet.has(id) ? 1 : OUT_ALPHA
    if (FADE_MS === 0) return target // reduced motion: no tween, land instantly
    const from = fadeFrom.get(id) ?? target
    const t = Math.min(1, (now - fadeStart) / FADE_MS)
    return from + (target - from) * t
  }

  // Precomputed soft-glow sprites, one per colour, drawn additively and built lazily
  // (rune colours in focus view, community colours in the global view). Building the
  // gradient once (not per node per frame) is what keeps the glow cheap.
  const halos = new Map<string, HTMLCanvasElement>()

  function rgba(hex: string, a: number): string {
    const n = parseInt(hex.slice(1), 16)
    return `rgba(${(n >> 16) & 255},${(n >> 8) & 255},${n & 255},${a})`
  }

  function haloFor(color: string): HTMLCanvasElement {
    let sprite = halos.get(color)
    if (!sprite) {
      sprite = document.createElement('canvas')
      sprite.width = sprite.height = 64
      const g = sprite.getContext('2d')!
      const grad = g.createRadialGradient(32, 32, 4, 32, 32, 32)
      grad.addColorStop(0, rgba(color, 0.55))
      grad.addColorStop(1, rgba(color, 0))
      g.fillStyle = grad
      g.fillRect(0, 0, 64, 64)
      halos.set(color, sprite)
    }
    return sprite
  }

  const nodeColor = (n: SimNode) =>
    colorByCommunity && n.community_id != null ? communityColor(n.community_id) : RUNE[n.type].color

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
      if (focusSet && !focusSet.has(n.id)) continue // faded out = not clickable
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
    const nowT = performance.now()
    const fading = nowT - fadeStart < FADE_MS

    // edges — same-community edges take the community colour in the global view, so
    // clusters read as coherent threads
    ctx.lineWidth = 1.2
    for (const l of links) {
      const s = l.source
      const t = l.target
      if (!s || !t || !vis(s) || !vis(t)) continue
      const focus = Math.min(focusFactor(s.id, nowT), focusFactor(t.id, nowT))
      // Provenance: inferred edges render dashed and lighter than explicit ones.
      ctx.globalAlpha = (matched(s) && matched(t) ? 0.3 : 0.07) * focus * (l.inferred ? 0.6 : 1)
      ctx.setLineDash(l.inferred ? [4, 4] : [])
      const sameCommunity =
        colorByCommunity && s.community_id != null && s.community_id === t.community_id
      ctx.strokeStyle = sameCommunity ? communityColor(s.community_id!) : edgeColor(s.type, t.type)
      ctx.beginPath()
      ctx.moveTo(s.x, s.y)
      ctx.lineTo(t.x, t.y)
      ctx.stroke()
    }
    ctx.setLineDash([])
    ctx.globalAlpha = 1

    // community labels at cluster centroids (global view only), behind the nodes
    if (colorByCommunity && communityLabels) {
      const acc = new Map<number, { x: number; y: number; count: number }>()
      for (const n of nodes) {
        if (!vis(n) || n.community_id == null) continue
        const a = acc.get(n.community_id) ?? { x: 0, y: 0, count: 0 }
        a.x += n.x
        a.y += n.y
        a.count++
        acc.set(n.community_id, a)
      }
      ctx.textAlign = 'center'
      ctx.textBaseline = 'middle'
      ctx.font = '600 15px "Spectral", sans-serif'
      for (const [cid, a] of acc) {
        if (a.count < 3) continue // singleton clusters would just be noise
        const label = communityLabels[String(cid)]?.label
        if (!label) continue
        ctx.globalAlpha = 0.4
        ctx.fillStyle = communityColor(cid)
        ctx.fillText(label, a.x / a.count, a.y / a.count - 46)
      }
      ctx.globalAlpha = 1
    }

    // additive glow pass
    ctx.globalCompositeOperation = 'lighter'
    for (const n of nodes) {
      if (!vis(n) || !matched(n)) continue
      const r = RADIUS[n.type]
      const hot = n.id === selectedId || n.id === hoverId
      const size = r * (hot ? 4.4 : 3.4)
      ctx.globalAlpha = (hot ? 0.9 : 0.5) * focusFactor(n.id, nowT)
      const sprite = haloFor(nodeColor(n))
      ctx.drawImage(sprite, n.x - size / 2, n.y - size / 2, size, size)
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
      const color = nodeColor(n)
      const focus = focusFactor(n.id, nowT)
      ctx.globalAlpha = (dim ? 0.18 : 1) * focus

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
        ctx.globalAlpha = (dim ? 0.18 : 0.7) * focus
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
          ctx.globalAlpha = focus
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
    if (fading) scheduleDraw() // keep the focus tween moving until it lands
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
    const k2 = Math.max(0.1, Math.min(3, cam.k * Math.exp(-e.deltaY * 0.0015)))
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
  // Content signature: rebuild only when nodes/edges/layout actually change. Includes
  // community_id (so a recluster repaints), edge rel/provenance (so styling never goes
  // stale), and a cheap fold of the saved layout (so another client's drag applies here
  // without a full reload).
  const sig = $derived(
    graph.nodes.map((n) => `${n.id}:${n.status}:${n.community_id}`).sort().join(',') +
      '|' +
      graph.edges.map((e) => `${e.src}>${e.dst}:${e.rel}:${e.provenance}`).sort().join(',') +
      '|' +
      Object.entries(graph.layout ?? {})
        .map(([id, p]) => `${id}:${p.x.toFixed(0)}:${p.y.toFixed(0)}:${p.pinned}`)
        .sort()
        .join(','),
  )

  // Mount: context, halos, fonts, sizing.
  $effect(() => {
    if (!canvas) return
    ctx = canvas.getContext('2d')

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

    // Effective saved positions: this session's fresh placements win over the server's,
    // UNLESS the server now has an entry and the cached one was never a drag (pinned) —
    // in that case the save round-tripped, so the server value wins and the now-stale
    // cache entry is dropped instead of permanently shadowing the server.
    const saved = new Map<string, { x: number; y: number; pinned: boolean }>()
    const serverLayout = g.layout ?? {}
    for (const [id, p] of Object.entries(serverLayout)) saved.set(id, p)
    for (const [id, p] of [...posMap]) {
      if (serverLayout[id] && !p.pinned) {
        posMap.delete(id)
        continue
      }
      saved.set(id, p)
    }

    nodes = g.nodes.map((n) => ({ ...n, x: 0, y: 0 })) as SimNode[]
    const byId = new Map(nodes.map((n) => [n.id, n]))
    // Resolve endpoints to node objects HERE, never via forceLink: on a fully-restored
    // load the simulation does not run, and string endpoints would crash the draw loop
    // (RUNE[undefined]) leaving the canvas blank.
    links = g.edges
      .filter((e) => byId.has(e.src) && byId.has(e.dst))
      .map((e) => ({
        source: byId.get(e.src)!,
        target: byId.get(e.dst)!,
        rel: e.rel,
        inferred: e.provenance != null && e.provenance !== 'explicit',
      }))

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
    // Ring radius from circumference (each anchor gets ~140px of arc), not from a
    // per-anchor radius multiplier: 40 quest lines means r~890, not an unusable 2200.
    const ring = Math.max(180, (anchors.length * 140) / TAU)
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
        // Weak pull toward the ring centre so unbounded charge repulsion cannot
        // explode the leaves off-viewport (it only acts during this bounded settle;
        // the layout freezes right after).
        .force('x', forceX<SimNode>(cx).strength(0.05))
        .force('y', forceY<SimNode>(cy).strength(0.05))
        .stop()
      const ticks = saved.size === 0 ? FULL_TICKS : INCREMENTAL_TICKS
      for (let i = 0; i < ticks; i++) sim.tick()
      sim.stop()

      // Persist only nodes without a prior saved position: leaves newly settled this
      // pass, and anchors placed for the first time. Nodes that already had a saved
      // entry are left untouched so we never clobber another client's fresher position
      // (lost-update).
      const batch: { node_id: string; x: number; y: number; pinned: boolean }[] = []
      for (const n of nodes) {
        if (saved.has(n.id)) continue
        const pinned = isAnchor(n)
        posMap.set(n.id, { x: n.x, y: n.y, pinned })
        batch.push({ node_id: n.id, x: n.x, y: n.y, pinned })
      }
      if (batch.length > 0) api.saveLayout(batch).catch(() => {})
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

  // Refocus: capture current alphas as the fade origin, swap the focus set, and fit
  // the camera to the visible neighbourhood (the whole graph in the All view). A
  // single-node glide at fixed zoom cannot frame an arbitrary layout; fitting the
  // bounding box always lands the user on the content. Positions never change on
  // focus (the layout is frozen); only alphas and the viewport move.
  let glideRaf = 0
  let lastFitSig: string | null = null

  function fitTo(ids: Set<string> | null) {
    const targets = ids ? nodes.filter((n) => ids.has(n.id)) : nodes
    if (targets.length === 0) return
    let minX = Infinity, maxX = -Infinity, minY = Infinity, maxY = -Infinity
    for (const n of targets) {
      if (n.x < minX) minX = n.x
      if (n.x > maxX) maxX = n.x
      if (n.y < minY) minY = n.y
      if (n.y > maxY) maxY = n.y
    }
    const pad = 90
    const bw = Math.max(maxX - minX, 200) + pad * 2
    const bh = Math.max(maxY - minY, 200) + pad * 2
    // Zoom floor 0.02, well below the wheel's 0.1: fit must be able to frame ANY
    // layout, including a degenerate persisted one, or the graph reads as blank.
    const tk = Math.min(1.5, Math.max(0.02, Math.min(cssW / bw, cssH / bh)))
    const mx = (minX + maxX) / 2
    const my = (minY + maxY) / 2
    const tx = cssW / 2 - tk * mx
    const ty = cssH / 2 - tk * my
    const sx = cam.x, sy = cam.y, sk = cam.k
    const t0 = performance.now()
    cancelAnimationFrame(glideRaf)
    const step = (t: number) => {
      const p = GLIDE_MS === 0 ? 1 : Math.min(1, (t - t0) / GLIDE_MS)
      const e = 1 - Math.pow(1 - p, 3) // ease-out cubic
      cam.x = sx + (tx - sx) * e
      cam.y = sy + (ty - sy) * e
      cam.k = sk + (tk - sk) * e
      scheduleDraw()
      if (p < 1) glideRaf = requestAnimationFrame(step)
    }
    glideRaf = requestAnimationFrame(step)
  }

  $effect(() => {
    const ids = focusIds ?? null
    const center = focusCenterId
    const now = performance.now()
    const from = new Map<string, number>()
    for (const n of nodes) from.set(n.id, focusFactor(n.id, now))
    fadeFrom = from
    focusSet = ids
    fadeStart = now
    // Refit when the focus target, the neighbourhood size (depth), or the mode
    // changes - but not on every live poll (ids is a fresh Set each time), so manual
    // pan/zoom is never yanked away mid-session.
    const fitSig = `${center ?? '__all__'}:${ids?.size ?? -1}`
    if (fitSig !== lastFitSig) {
      lastFitSig = fitSig
      fitTo(ids)
    }
    scheduleDraw()
  })

  // Restyle (selection / highlight / filter / colour mode) is just a redraw — no relayout.
  $effect(() => {
    selectedId
    highlightType
    filterText
    hiddenTypes
    colorByCommunity
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
