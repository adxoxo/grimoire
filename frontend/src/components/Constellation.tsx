import { useEffect, useMemo, useRef, useState } from 'react'
import {
  forceCenter,
  forceCollide,
  forceLink,
  forceManyBody,
  forceSimulation,
  forceX,
  forceY,
  select,
  zoom,
  zoomIdentity,
  type Simulation,
  type ZoomTransform,
} from 'd3'
import type { Graph, GraphNode } from '../api'
import { RUNE, edgeColor, type NodeType } from '../theme'

interface SimNode extends GraphNode {
  x?: number
  y?: number
  fx?: number | null
  fy?: number | null
}
interface SimLink {
  source: SimNode | string
  target: SimNode | string
}

const RADIUS: Record<NodeType, number> = { project: 30, memory: 20, document: 19, entity: 17 }

interface Props {
  graph: Graph
  selectedId: string | null
  highlightType: NodeType | null
  onSelect: (node: GraphNode | null) => void
}

export default function Constellation({ graph, selectedId, highlightType, onSelect }: Props) {
  const svgRef = useRef<SVGSVGElement>(null)
  const gRef = useRef<SVGGElement>(null)
  const transformRef = useRef<ZoomTransform>(zoomIdentity)
  const simRef = useRef<Simulation<SimNode, undefined> | null>(null)
  const dragRef = useRef<SimNode | null>(null)
  const [, setTick] = useState(0)
  const [size, setSize] = useState({ w: 800, h: 600 })

  // Build the simulation once per graph payload.
  const { nodes, links } = useMemo(() => {
    const nodes: SimNode[] = graph.nodes.map((n) => ({ ...n }))
    const byId = new Set(nodes.map((n) => n.id))
    const links: SimLink[] = graph.edges
      .filter((e) => byId.has(e.src) && byId.has(e.dst))
      .map((e) => ({ source: e.src, target: e.dst }))
    return { nodes, links }
  }, [graph])

  const nodeById = useMemo(() => {
    const m = new Map<string, SimNode>()
    nodes.forEach((n) => m.set(n.id, n))
    return m
  }, [nodes])

  // Measure the canvas.
  useEffect(() => {
    const el = svgRef.current
    if (!el) return
    const ro = new ResizeObserver(() => {
      const r = el.getBoundingClientRect()
      setSize({ w: r.width, h: r.height })
    })
    ro.observe(el)
    return () => ro.disconnect()
  }, [])

  // Run the force layout. Quest lines pull toward centre; everything radiates out.
  useEffect(() => {
    const sim = forceSimulation<SimNode>(nodes)
      .force('charge', forceManyBody().strength(-380))
      .force('link', forceLink<SimNode, SimLink>(links).id((d) => (d as SimNode).id).distance(95).strength(0.45))
      .force('center', forceCenter(size.w / 2, size.h / 2))
      .force('collide', forceCollide<SimNode>((d) => RADIUS[d.type] + 14))
      .force('x', forceX<SimNode>(size.w / 2).strength((d) => (d.type === 'project' ? 0.08 : 0.02)))
      .force('y', forceY<SimNode>(size.h / 2).strength((d) => (d.type === 'project' ? 0.08 : 0.03)))
      .on('tick', () => setTick((t) => t + 1))
    simRef.current = sim
    return () => {
      sim.stop()
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [nodes, links])

  // Keep centre forces in sync with the measured size.
  useEffect(() => {
    const sim = simRef.current
    if (!sim) return
    sim.force('center', forceCenter(size.w / 2, size.h / 2))
    sim.force('x', forceX<SimNode>(size.w / 2).strength((d) => (d.type === 'project' ? 0.08 : 0.02)))
    sim.force('y', forceY<SimNode>(size.h / 2).strength((d) => (d.type === 'project' ? 0.08 : 0.03)))
    sim.alpha(0.4).restart()
  }, [size])

  // Pan + zoom on the canvas; ignore gestures that start on a node so drag wins.
  useEffect(() => {
    const svg = select(svgRef.current as SVGSVGElement)
    const behavior = zoom<SVGSVGElement, unknown>()
      .scaleExtent([0.35, 3])
      .filter((e: Event) => !(e.target as Element).closest('.gnode'))
      .on('zoom', (e) => {
        transformRef.current = e.transform
        select(gRef.current as SVGGElement).attr('transform', e.transform.toString())
      })
    svg.call(behavior)
    return () => {
      svg.on('.zoom', null)
    }
  }, [])

  // Node dragging via pointer events, converted through the current zoom transform.
  useEffect(() => {
    function move(e: PointerEvent) {
      const dragged = dragRef.current
      if (!dragged || !svgRef.current) return
      const r = svgRef.current.getBoundingClientRect()
      const [gx, gy] = transformRef.current.invert([e.clientX - r.left, e.clientY - r.top])
      dragged.fx = gx
      dragged.fy = gy
    }
    function up() {
      if (dragRef.current) {
        dragRef.current.fx = null
        dragRef.current.fy = null
        dragRef.current = null
        simRef.current?.alphaTarget(0)
      }
    }
    window.addEventListener('pointermove', move)
    window.addEventListener('pointerup', up)
    return () => {
      window.removeEventListener('pointermove', move)
      window.removeEventListener('pointerup', up)
    }
  }, [])

  function startDrag(node: SimNode) {
    dragRef.current = node
    node.fx = node.x
    node.fy = node.y
    simRef.current?.alphaTarget(0.3).restart()
  }

  return (
    <svg ref={svgRef} className="absolute inset-0 w-full h-full" style={{ cursor: 'grab' }}>
      <g ref={gRef}>
        {/* Edges — coloured by their higher-rank (parent) endpoint */}
        <g>
          {links.map((l, i) => {
            const s = typeof l.source === 'string' ? nodeById.get(l.source) : l.source
            const t = typeof l.target === 'string' ? nodeById.get(l.target) : l.target
            if (!s || !t) return null
            const dim = highlightType && s.type !== highlightType && t.type !== highlightType
            return (
              <line
                key={i}
                x1={s.x}
                y1={s.y}
                x2={t.x}
                y2={t.y}
                stroke={edgeColor(s.type, t.type)}
                strokeWidth={1.2}
                opacity={dim ? 0.08 : 0.4}
              />
            )
          })}
        </g>

        {/* Nodes */}
        <g>
          {nodes.map((n) => {
            const rune = RUNE[n.type]
            const r = RADIUS[n.type]
            const selected = n.id === selectedId
            const dim = highlightType ? n.type !== highlightType : false
            const unreviewed = n.status === 'unreviewed'
            const glow = `${selected ? r * 0.7 : r * 0.45}px`
            return (
              <g
                key={n.id}
                className="gnode"
                transform={`translate(${n.x ?? 0},${n.y ?? 0})`}
                style={{ cursor: 'pointer', opacity: dim ? 0.22 : 1, transition: 'opacity 300ms' }}
                onPointerDown={(e) => {
                  e.preventDefault()
                  startDrag(n)
                }}
                onClick={() => onSelect(n)}
              >
                <circle
                  r={r}
                  fill="#0e0d16"
                  stroke={rune.color}
                  strokeWidth={selected ? 3 : 1.6}
                  className={unreviewed ? 'svg-pulse' : undefined}
                  style={{ filter: `drop-shadow(0 0 ${glow} ${rune.color})` }}
                />
                <text
                  className="material-symbols-outlined"
                  dominantBaseline="central"
                  textAnchor="middle"
                  fill={rune.color}
                  style={{ fontSize: `${Math.round(r * 0.85)}px` }}
                >
                  {rune.icon}
                </text>
                <text
                  textAnchor="middle"
                  y={r + 16}
                  fill="#cdc6b7"
                  className="font-label-md"
                  style={{ fontSize: '11px', letterSpacing: '0.04em', pointerEvents: 'none' }}
                >
                  {n.title.length > 22 ? n.title.slice(0, 21) + '…' : n.title}
                </text>
              </g>
            )
          })}
        </g>
      </g>
    </svg>
  )
}
