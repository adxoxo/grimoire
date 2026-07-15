<script lang="ts">
  import { untrack } from 'svelte'
  import {
    forceCenter,
    forceCollide,
    forceLink,
    forceManyBody,
    forceSimulation,
    forceX,
    forceY,
    type Simulation,
  } from 'd3'
  import type { Graph, GraphNode } from '../lib/api'
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
  }

  const RADIUS: Record<NodeType, number> = { project: 30, memory: 20, document: 19, entity: 17 }
  const TAU = Math.PI * 2

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
  let sim: Simulation<SimNode, undefined> | null = null
  let nodes: SimNode[] = []
  let links: SimLink[] = []
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
      ctx.fillStyle = '#0c1710'
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
        ctx.font = '11px "Work Sans", sans-serif'
        const ly = n.y + r + 12
        if (hot) {
          const tw = ctx.measureText(label).width
          ctx.globalAlpha = 1
          ctx.fillStyle = 'rgba(7,16,11,0.82)'
          ctx.beginPath()
          ctx.roundRect(n.x - tw / 2 - 5, ly - 9, tw + 10, 17, 3)
          ctx.fill()
          ctx.fillStyle = '#e4efe7'
        } else {
          ctx.fillStyle = '#c4d3c7'
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
      n.fx = n.x
      n.fy = n.y
      sim?.alphaTarget(0.3).restart()
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
        const g = toGraph(e.clientX, e.clientY)
        dragging.fx = g.x
        dragging.fy = g.y
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
      dragging.fx = null
      dragging.fy = null
      sim?.alphaTarget(0)
      if (!moved) onSelect(dragging)
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

    const ro = new ResizeObserver(() => {
      const r = canvas!.getBoundingClientRect()
      cssW = r.width
      cssH = r.height
      const dpr = window.devicePixelRatio || 1
      canvas!.width = Math.round(cssW * dpr)
      canvas!.height = Math.round(cssH * dpr)
      sim?.force('center', forceCenter(cssW / 2, cssH / 2))
      sim?.force('x', forceX<SimNode>(cssW / 2).strength((d) => (d.type === 'project' ? 0.08 : 0.02)))
      sim?.force('y', forceY<SimNode>(cssH / 2).strength((d) => (d.type === 'project' ? 0.08 : 0.03)))
      sim?.alpha(0.3).restart()
      scheduleDraw()
    })
    ro.observe(canvas)

    document.fonts.ready.then(() => {
      fontReady = true
      scheduleDraw()
    })

    return () => ro.disconnect()
  })

  // Rebuild the simulation when the graph content changes.
  $effect(() => {
    sig
    const g = untrack(() => graph)
    if (!ctx) return

    nodes = g.nodes.map((n) => ({ ...n, x: cssW / 2 + (Math.random() - 0.5) * 40, y: cssH / 2 + (Math.random() - 0.5) * 40 })) as SimNode[]
    const byId = new Set(nodes.map((n) => n.id))
    links = g.edges
      .filter((e) => byId.has(e.src) && byId.has(e.dst))
      .map((e) => ({ source: e.src as unknown as SimNode, target: e.dst as unknown as SimNode }))

    sim?.stop()
    sim = forceSimulation<SimNode>(nodes)
      .force('charge', forceManyBody().strength(-380))
      .force('link', forceLink<SimNode, SimLink>(links).id((d: any) => d.id).distance(95).strength(0.45))
      .force('center', forceCenter(cssW / 2, cssH / 2))
      .force('collide', forceCollide<SimNode>((d) => RADIUS[d.type] + 14))
      .force('x', forceX<SimNode>(cssW / 2).strength((d) => (d.type === 'project' ? 0.08 : 0.02)))
      .force('y', forceY<SimNode>(cssH / 2).strength((d) => (d.type === 'project' ? 0.08 : 0.03)))
      .on('tick', scheduleDraw)

    return () => {
      sim?.stop()
      sim = null
    }
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
