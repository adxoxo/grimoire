<script lang="ts">
  import { untrack } from 'svelte'
  import { forceCollide, forceLink, forceManyBody, forceSimulation, forceX, forceY } from 'd3'
  import { api, type Graph, type GraphNode } from '../lib/api'
  import { RUNE, SCOPE, communityColor, edgeColor, nodeKindColor, type NodeType } from '../lib/theme'

  interface SimNode extends GraphNode {
    x: number
    y: number
    fx?: number | null
    fy?: number | null
    z: number // stable depth factor in [0.80, 1.15]; scales drawn radius + stroke/label alpha
    pulsePhase: number // stable per-node phase for the unreviewed stroke oscillation
  }
  interface SimLink {
    source: SimNode
    target: SimNode
    rel: string
    inferred: boolean
    phase: number // stable per-edge pulse phase in [0, 1)
    duration: number // pulse travel time in ms (4-8s)
  }

  const RADIUS: Record<NodeType, number> = { project: 30, memory: 20, document: 19, entity: 17 }
  const TAU = Math.PI * 2
  const PULSE_LEN = 0.035 // traveling highlight covers ~3.5% of the bezier

  // Cheap stable 32-bit hash (FNV-1a). Depth, pulse phase, and pulse duration all
  // derive from ids through this, so they never change across frames or reloads.
  function hash32(s: string): number {
    let h = 2166136261
    for (let i = 0; i < s.length; i++) {
      h ^= s.charCodeAt(i)
      h = Math.imul(h, 16777619)
    }
    return h >>> 0
  }

  // Depth factor: scope rows sit at fixed senior depths (domains nearest), content
  // scatters across [0.80, 1.15] by id hash for a stable 2.5D read.
  const zOf = (n: GraphNode): number =>
    n.node_kind === 'domain' ? 1.08 : n.node_kind === 'index' ? 1.0 : 0.8 + ((hash32(n.id) % 1000) / 1000) * 0.35

  // Cubic bezier coordinate at t (used for the edge pulse segment).
  const cubicAt = (a: number, c1: number, c2: number, b: number, t: number): number => {
    const u = 1 - t
    return u * u * u * a + 3 * u * u * t * c1 + 3 * u * t * t * c2 + t * t * t * b
  }

  // Node radius: scope rows (domain/index spine of the galaxy and domain views) render
  // larger than content stars; content keeps the per-type radius, with RADIUS the fallback.
  const radiusOf = (n: GraphNode) =>
    n.node_kind === 'domain' ? 32 : n.node_kind === 'index' ? 24 : RADIUS[n.type]

  // Icon glyph: scope rows carry the SCOPE hub/category marks; content carries its rune.
  const iconOf = (n: GraphNode) =>
    n.node_kind === 'domain' || n.node_kind === 'index' ? SCOPE[n.node_kind].icon : RUNE[n.type]?.icon ?? ''

  // Edge colour, scope-aware: a membership/hierarchy edge (one endpoint a domain/index)
  // takes the scope's gold family colour; content-to-content edges follow the parent rune.
  const linkColor = (s: GraphNode, t: GraphNode): string => {
    if (t.node_kind === 'domain' || t.node_kind === 'index') return nodeKindColor(t)
    if (s.node_kind === 'domain' || s.node_kind === 'index') return nodeKindColor(s)
    return edgeColor(s.type, t.type)
  }

  // Anchors are the fixed spine of the constellation; leaves settle around them and
  // freeze. By default projects (quest lines) are the anchors, but a caller can override
  // the spine with anchorIds (the galaxy pins domains, a domain view pins its indexes).
  const isAnchor = (n: GraphNode) => (anchorIds ? anchorIds.has(n.id) : n.type === 'project')

  // Edge stiffness by relationship: firm for ownership so leaves fan out around their
  // parent at a calm distance; loose and weak for cross-references so they do not
  // collapse clusters. Membership into a domain rides longer than into an index.
  const EDGE_STIFFNESS: Record<string, { distance: number; strength: number }> = {
    belongs_to: { distance: 70, strength: 0.9 },
    mentions: { distance: 90, strength: 0.5 },
    derived_from: { distance: 90, strength: 0.5 },
    references: { distance: 160, strength: 0.1 },
  }
  const DEFAULT_STIFFNESS = { distance: 95, strength: 0.4 }
  const DOMAIN_LINK_DISTANCE = 110 // index -> domain membership rides the longest leash

  const linkDistance = (l: SimLink): number =>
    l.rel === 'belongs_to' && (l.target.node_kind === 'domain' || l.source.node_kind === 'index')
      ? DOMAIN_LINK_DISTANCE
      : (EDGE_STIFFNESS[l.rel] ?? DEFAULT_STIFFNESS).distance

  // Tick budgets: a first-ever layout settles long; adding nodes to a saved layout only
  // re-settles the newcomers (everything saved is pinned during the pass). 380 because
  // the looser spacing forces need more iterations to stop drifting.
  const FULL_TICKS = 380
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
    anchorIds = null,
    persistLayout = true,
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
    // Override the anchor spine: when set, these ids are the pinned anchors instead of
    // the default type==='project'. null keeps the legacy project-spine behaviour.
    anchorIds?: Set<string> | null
    // Whether drags and settles persist to the server layout. Drill-down views are
    // ephemeral partitions, so they pass false to keep the canonical layout clean.
    persistLayout?: boolean
    communityLabels?: Record<string, { label: string }>
    onSelect: (node: GraphNode) => void
  } = $props()

  let canvas = $state<HTMLCanvasElement>()

  // Everything below is deliberately NON-reactive. Canvas draws imperatively; Svelte
  // never touches the render path, so hundreds of nodes stay cheap. Rendering has one
  // driver: while edge pulses animate (motion allowed, tab visible, edges present) a
  // persistent rAF loop repaints; otherwise redraws stay event-driven exactly as before
  // (and reduced-motion never leaves the event-driven path).
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

  // Starfield atmosphere: ~120 tiny dots behind the graph, seeded deterministically
  // from the canvas size (same size = same sky), split across three parallax bands so
  // panning drifts them slower than the nodes. Rebuilt only when the size changes.
  interface Star {
    x: number
    y: number
    size: number
    alpha: number
    factor: number
  }
  const STAR_COUNT = 120
  const STAR_LAYERS = [0.15, 0.3, 0.45]
  let stars: Star[] = []
  let starW = 0
  let starH = 0

  function mulberry32(seed: number): () => number {
    let a = seed >>> 0
    return () => {
      a = (a + 0x6d2b79f5) | 0
      let t = Math.imul(a ^ (a >>> 15), 1 | a)
      t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t
      return ((t ^ (t >>> 14)) >>> 0) / 4294967296
    }
  }

  function buildStars() {
    if (starW === cssW && starH === cssH) return
    starW = cssW
    starH = cssH
    const rand = mulberry32((Math.round(cssW) * 73856093) ^ (Math.round(cssH) * 19349663))
    stars = []
    for (let i = 0; i < STAR_COUNT; i++) {
      stars.push({
        x: rand() * cssW,
        y: rand() * cssH,
        size: rand() < 0.12 ? 1.3 : 0.7,
        alpha: 0.05 + rand() * 0.2,
        factor: STAR_LAYERS[i % STAR_LAYERS.length],
      })
    }
  }

  // Pulse loop: the single continuous driver. It runs ONLY while pulses can animate
  // (motion allowed, tab visible, something to pulse); otherwise rendering stays
  // event-driven through scheduleDraw. Never started under reduced motion.
  let pulseRunning = false
  let pulseRaf = 0

  function pulseLoop() {
    if (!pulseRunning) return
    draw()
    pulseRaf = requestAnimationFrame(pulseLoop)
  }

  function stopPulseLoop() {
    pulseRunning = false
    cancelAnimationFrame(pulseRaf)
  }

  function syncPulseLoop() {
    const wants =
      !reducedMotion &&
      !document.hidden &&
      (links.length > 0 || nodes.some((n) => n.status === 'unreviewed'))
    if (wants && !pulseRunning) {
      pulseRunning = true
      pulseRaf = requestAnimationFrame(pulseLoop)
    } else if (!wants && pulseRunning) {
      stopPulseLoop()
    }
  }

  const nodeColor = (n: SimNode) =>
    n.node_kind === 'domain' || n.node_kind === 'index'
      ? nodeKindColor(n)
      : colorByCommunity && n.community_id != null
        ? communityColor(n.community_id)
        : RUNE[n.type].color

  let drawRaf = 0
  function scheduleDraw() {
    if (pulseRunning) return // the persistent loop already repaints every frame
    if (rafPending) return
    rafPending = true
    drawRaf = requestAnimationFrame(draw)
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
      const r = radiusOf(n) * n.z // hit area matches the depth-scaled drawn radius
      if (dx * dx + dy * dy <= r * r) return n
    }
    return null
  }

  function draw() {
    rafPending = false
    if (!ctx) return
    const nowT = performance.now()
    const fading = nowT - fadeStart < FADE_MS

    // Camera glide: tweened here inside the single draw driver instead of running a
    // second competing rAF chain.
    if (glide) {
      const p = GLIDE_MS === 0 ? 1 : Math.min(1, (nowT - glide.t0) / GLIDE_MS)
      const e = 1 - Math.pow(1 - p, 3) // ease-out cubic
      cam.x = glide.sx + (glide.tx - glide.sx) * e
      cam.y = glide.sy + (glide.ty - glide.sy) * e
      cam.k = glide.sk + (glide.tk - glide.sk) * e
      if (p >= 1) glide = null
    }

    const dpr = window.devicePixelRatio || 1
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0)
    ctx.clearRect(0, 0, cssW, cssH)

    // Atmosphere, screen space, deepest first: a faint mid-depth grid, then three
    // parallax star bands. Both track a fraction of the camera translation (wrapped)
    // so the graph reads as the nearest layer of a deep scene, not marks on a board.
    const GRID = 66
    const gx = (((cam.x * 0.5) % GRID) + GRID) % GRID
    const gy = (((cam.y * 0.5) % GRID) + GRID) % GRID
    ctx.strokeStyle = 'rgba(41,38,63,0.35)'
    ctx.lineWidth = 1
    ctx.beginPath()
    for (let x = gx; x <= cssW; x += GRID) {
      ctx.moveTo(x, 0)
      ctx.lineTo(x, cssH)
    }
    for (let y = gy; y <= cssH; y += GRID) {
      ctx.moveTo(0, y)
      ctx.lineTo(cssW, y)
    }
    ctx.stroke()

    buildStars()
    ctx.fillStyle = '#cfc8e8'
    for (const s of stars) {
      const sx = (((s.x + cam.x * s.factor) % cssW) + cssW) % cssW
      const sy = (((s.y + cam.y * s.factor) % cssH) + cssH) % cssH
      ctx.globalAlpha = s.alpha
      ctx.fillRect(sx, sy, s.size, s.size)
    }
    ctx.globalAlpha = 1

    ctx.translate(cam.x, cam.y)
    ctx.scale(cam.k, cam.k)

    const q = (filterText ?? '').trim().toLowerCase()
    const vis = (n: SimNode) => !hiddenTypes?.has(n.type)
    const matched = (n: SimNode) =>
      vis(n) && (!highlightType || n.type === highlightType) && (!q || n.title.toLowerCase().includes(q))

    // Edges, pass 1 (static): horizontal-tangent cubic beziers in the schematic border
    // colour, quiet by design. Provenance keeps its read: inferred edges stay dashed
    // and lighter than explicit ones.
    ctx.lineWidth = 1
    ctx.strokeStyle = '#29263f'
    for (const l of links) {
      const s = l.source
      const t = l.target
      if (!s || !t || !vis(s) || !vis(t)) continue
      const focus = Math.min(focusFactor(s.id, nowT), focusFactor(t.id, nowT))
      ctx.globalAlpha = (matched(s) && matched(t) ? 0.7 : 0.18) * focus * (l.inferred ? 0.6 : 1)
      ctx.setLineDash(l.inferred ? [4, 4] : [])
      const mx = (s.x + t.x) / 2
      ctx.beginPath()
      ctx.moveTo(s.x, s.y)
      ctx.bezierCurveTo(mx, s.y, mx, t.y, t.x, t.y)
      ctx.stroke()
    }
    ctx.setLineDash([])

    // Edges, pass 2 (pulse): a short traveling highlight along the bezier, carrying
    // the edge's own colour (community colour for same-community edges in the global
    // view, so clusters still read as coherent threads). Skipped under reduced motion;
    // the loop that would animate it never starts there.
    if (!reducedMotion) {
      ctx.lineCap = 'round'
      ctx.lineWidth = 1.4
      for (const l of links) {
        const s = l.source
        const t = l.target
        if (!s || !t || !vis(s) || !vis(t)) continue
        const focus = Math.min(focusFactor(s.id, nowT), focusFactor(t.id, nowT))
        const a = 0.85 * focus * (matched(s) && matched(t) ? 1 : 0.15) * (l.inferred ? 0.6 : 1)
        if (a < 0.02) continue
        const t0 = ((nowT / l.duration + l.phase) % 1) * (1 - PULSE_LEN)
        const t1 = t0 + PULSE_LEN
        const mx = (s.x + t.x) / 2
        const sameCommunity =
          colorByCommunity && s.community_id != null && s.community_id === t.community_id
        ctx.strokeStyle = sameCommunity ? communityColor(s.community_id!) : linkColor(s, t)
        ctx.globalAlpha = a
        ctx.beginPath()
        ctx.moveTo(cubicAt(s.x, mx, mx, t.x, t0), cubicAt(s.y, s.y, t.y, t.y, t0))
        ctx.lineTo(cubicAt(s.x, mx, mx, t.x, t1), cubicAt(s.y, s.y, t.y, t.y, t1))
        ctx.stroke()
      }
      ctx.lineCap = 'butt'
    }
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
      ctx.font = '600 15px "Spectral", serif'
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

    // Nodes: flat fills with depth-faded strokes, no glow pass. Depth (z) scales the
    // drawn radius and fades the stroke; hover/selection go to full alpha, no scaling.
    ctx.textAlign = 'center'
    ctx.textBaseline = 'middle'
    // Small index views (<= 30 nodes at full focus) label everything; dense views
    // label only scope rows and the hot node.
    const fullCount = focusSet ? focusSet.size : nodes.reduce((c, n) => (vis(n) ? c + 1 : c), 0)
    const smallView = fullCount <= 30
    for (const n of nodes) {
      if (!vis(n)) continue
      const r = radiusOf(n) * n.z
      const sel = n.id === selectedId
      const hot = sel || n.id === hoverId
      const dim = !matched(n)
      const color = nodeColor(n)
      const focus = focusFactor(n.id, nowT)
      const dimF = (dim ? 0.18 : 1) * focus
      const isDomain = n.node_kind === 'domain'
      const isIndex = n.node_kind === 'index'

      ctx.beginPath()
      ctx.arc(n.x, n.y, r, 0, TAU)
      ctx.fillStyle = '#16142b'
      ctx.globalAlpha = dimF
      ctx.fill()
      ctx.lineWidth = isDomain ? 1.6 : 1.1
      ctx.strokeStyle = color
      ctx.globalAlpha = (hot ? 1 : 0.45 + 0.4 * n.z) * dimF
      ctx.stroke()

      // Domain anchor mark: a second concentric ring, quiet until hot.
      if (isDomain) {
        ctx.lineWidth = 1
        ctx.globalAlpha = (hot ? 0.8 : 0.3) * dimF
        ctx.beginPath()
        ctx.arc(n.x, n.y, r + 4, 0, TAU)
        ctx.stroke()
      }

      // Selection: full-alpha stroke above plus one restrained outer ring, no glow.
      if (sel) {
        ctx.lineWidth = 1
        ctx.globalAlpha = 0.5 * dimF
        ctx.beginPath()
        ctx.arc(n.x, n.y, r + 3, 0, TAU)
        ctx.stroke()
      }

      // Unreviewed = dashed outer ring whose stroke alpha oscillates 0.35..0.75 over
      // ~3s (per-node phase). Reduced motion holds it steady at the midpoint; the dash
      // pattern keeps the status legible without any animation.
      if (n.status === 'unreviewed') {
        const pulse = reducedMotion ? 0.55 : 0.55 + 0.2 * Math.sin(TAU * (nowT / 3000 + n.pulsePhase))
        ctx.setLineDash([3, 3])
        ctx.lineWidth = 1
        ctx.globalAlpha = pulse * dimF
        ctx.beginPath()
        ctx.arc(n.x, n.y, r + (isDomain ? 7 : 4), 0, TAU)
        ctx.stroke()
        ctx.setLineDash([])
      }

      if (fontReady) {
        ctx.globalAlpha = dimF
        ctx.fillStyle = color
        ctx.font = `${Math.round(r * 0.9)}px "Material Symbols Outlined"`
        ctx.fillText(iconOf(n), n.x, n.y + 1)
      }

      // Labels: scope rows always speak (domains in the display serif, indexes in
      // Spectral); content speaks when hot or when the view is small enough to stay
      // calm. The hot label keeps its dark backdrop for legibility over edges.
      const inFull = !focusSet || focusSet.has(n.id)
      if (isDomain || isIndex || hot || (smallView && inFull)) {
        const label = n.title.length > 22 ? n.title.slice(0, 21) + '…' : n.title
        let size = 11
        if (isDomain) {
          size = 13
          ctx.font = '600 13px "Cormorant Garamond", Georgia, serif'
          ctx.fillStyle = '#e3d3a0'
          ctx.globalAlpha = 0.95 * dimF
        } else if (isIndex) {
          ctx.font = '11px "Spectral", serif'
          ctx.fillStyle = '#9b96b8'
          ctx.globalAlpha = 0.8 * dimF
        } else {
          ctx.font = '11px "Spectral", serif'
          ctx.fillStyle = hot ? '#e5e0ee' : '#9b96b8'
          ctx.globalAlpha = (hot ? 1 : 0.45 + 0.4 * n.z) * dimF
        }
        const ly = n.y + r + size + 3
        if (hot) {
          const tw = ctx.measureText(label).width
          ctx.globalAlpha = focus
          ctx.fillStyle = 'rgba(12,11,20,0.82)'
          ctx.beginPath()
          ctx.roundRect(n.x - tw / 2 - 5, ly - 9, tw + 10, 17, 3)
          ctx.fill()
          ctx.fillStyle = '#e5e0ee'
        }
        ctx.fillText(label, n.x, ly)
      }
    }
    ctx.globalAlpha = 1
    // Keep tweens moving when the pulse loop is off (reduced motion or no pulses);
    // scheduleDraw no-ops while the loop is the driver.
    if (fading || glide) scheduleDraw()
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
        if (persistLayout)
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

  // Mount: context, fonts, sizing, visibility.
  $effect(() => {
    if (!canvas) return
    ctx = canvas.getContext('2d')

    // Resize only re-rasterizes and redraws; the layout is frozen, so nothing reflows.
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

    // Pause the pulse loop while the tab is hidden; resume (and repaint) on return.
    const onVisibility = () => {
      syncPulseLoop()
      if (!document.hidden) scheduleDraw()
    }
    document.addEventListener('visibilitychange', onVisibility)

    return () => {
      ro.disconnect()
      document.removeEventListener('visibilitychange', onVisibility)
      stopPulseLoop()
      cancelAnimationFrame(drawRaf)
      rafPending = false
      glide = null
    }
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
    // UNLESS the server now has an entry and the cached one was never a drag (pinned):
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

    nodes = g.nodes.map((n) => ({
      ...n,
      x: 0,
      y: 0,
      z: zOf(n),
      pulsePhase: (hash32(n.id) % 997) / 997,
    })) as SimNode[]
    const byId = new Map(nodes.map((n) => [n.id, n]))
    // Resolve endpoints to node objects HERE, never via forceLink: on a fully-restored
    // load the simulation does not run, and string endpoints would crash the draw loop
    // (RUNE[undefined]) leaving the canvas blank.
    links = g.edges
      .filter((e) => byId.has(e.src) && byId.has(e.dst))
      .map((e) => {
        const h = hash32(e.src + '>' + e.dst)
        return {
          source: byId.get(e.src)!,
          target: byId.get(e.dst)!,
          rel: e.rel,
          inferred: e.provenance != null && e.provenance !== 'explicit',
          phase: (h % 1024) / 1024,
          duration: 4000 + ((h >>> 10) % 4000), // 4-8s, stable per edge
        }
      })

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
            .distance(linkDistance)
            .strength((l) => (EDGE_STIFFNESS[l.rel] ?? DEFAULT_STIFFNESS).strength),
        )
        .force('charge', forceManyBody<SimNode>().strength(-320))
        // Collide on the depth-scaled drawn radius plus generous breathing room,
        // the "too tight" fix.
        .force('collide', forceCollide<SimNode>((d) => radiusOf(d) * d.z + 26))
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
      if (persistLayout && batch.length > 0) api.saveLayout(batch).catch(() => {})
    }

    // Release the temporary pins on unpinned leaves so a drag can move them freely.
    for (const n of nodes) {
      if (isAnchor(n)) continue
      if (!(saved.get(n.id)?.pinned ?? false) && !posMap.get(n.id)?.pinned) {
        n.fx = null
        n.fy = null
      }
    }

    // Content changed: start or stop the pulse driver to match the new edge set.
    syncPulseLoop()
    scheduleDraw()
  })

  // Refocus: capture current alphas as the fade origin, swap the focus set, and fit
  // the camera to the visible neighbourhood (the whole graph in the All view). A
  // single-node glide at fixed zoom cannot frame an arbitrary layout; fitting the
  // bounding box always lands the user on the content. Positions never change on
  // focus (the layout is frozen); only alphas and the viewport move.
  // Glide state consumed by draw(): the camera tween runs inside the one draw driver
  // (pulse loop when active, self-chained scheduleDraw otherwise), no separate rAF.
  let glide: { sx: number; sy: number; sk: number; tx: number; ty: number; tk: number; t0: number } | null = null
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
    if (GLIDE_MS === 0) {
      // Reduced motion: land instantly, no tween.
      glide = null
      cam.x = tx
      cam.y = ty
      cam.k = tk
      scheduleDraw()
      return
    }
    glide = { sx: cam.x, sy: cam.y, sk: cam.k, tx, ty, tk, t0: performance.now() }
    scheduleDraw()
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

  // Restyle (selection / highlight / filter / colour mode) is just a redraw, no relayout.
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
