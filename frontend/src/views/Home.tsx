import { useEffect, useMemo, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import { api, type Graph, type GraphNode } from '../api'
import { RUNE, type NodeType } from '../theme'
import Constellation from '../components/Constellation'
import NodeDetailPanel from '../components/NodeDetailPanel'
import { useAppState } from '../state'

const ALL_TYPES: NodeType[] = ['project', 'document', 'memory', 'entity']

export default function Home() {
  const { graphVersion, refreshGraph } = useAppState()
  const [graph, setGraph] = useState<Graph | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [selected, setSelected] = useState<GraphNode | null>(null)
  const [query, setQuery] = useState('')
  const [hidden, setHidden] = useState<Set<NodeType>>(new Set())
  const [showFilter, setShowFilter] = useState(false)
  const [params] = useSearchParams()
  const highlightType = (params.get('type') as NodeType | null) ?? null

  useEffect(() => {
    api.graph().then(setGraph).catch((e) => setError(String(e)))
  }, [graphVersion])

  const connections = useMemo(() => {
    if (!graph || !selected) return 0
    return graph.edges.filter((e) => e.src === selected.id || e.dst === selected.id).length
  }, [graph, selected])

  const selectedEdges = useMemo(() => {
    if (!graph || !selected) return []
    return graph.edges
      .filter((e) => e.src === selected.id || e.dst === selected.id)
      .map((e) => {
        const otherId = e.src === selected.id ? e.dst : e.src
        const other = graph.nodes.find((n) => n.id === otherId)
        return { ...e, otherTitle: other?.title ?? otherId }
      })
  }, [graph, selected])

  function toggleType(t: NodeType) {
    setHidden((h) => {
      const next = new Set(h)
      next.has(t) ? next.delete(t) : next.add(t)
      return next
    })
  }

  async function runSearch(e: React.FormEvent) {
    e.preventDefault()
    if (!graph || !query.trim()) return
    try {
      const { results } = await api.search(query.trim())
      for (const r of results) {
        const node = graph.nodes.find((n) => n.id === r.node_id)
        if (node) {
          setSelected(node)
          return
        }
      }
    } catch {
      /* retrieval unavailable: the live type-filter above already narrowed the graph */
    }
  }

  async function prune(edge: { src: string; dst: string; rel: string }) {
    await api.deleteEdge(edge.src, edge.dst, edge.rel)
    refreshGraph()
  }

  return (
    <main className="relative w-full h-screen bg-bg-page overflow-hidden">
      {/* Search overlay + filter */}
      <div className="absolute top-8 left-1/2 -translate-x-1/2 w-full max-w-2xl px-4 z-30">
        <form
          onSubmit={runSearch}
          className="relative bg-bg-panel/80 backdrop-blur-md border border-border-default rounded-full shadow-[0_4px_30px_rgba(0,0,0,0.5)] flex items-center px-4 py-3 group focus-within:border-rune-quest focus-within:shadow-[0_0_20px_rgba(212,169,63,0.2)] transition-all duration-300"
        >
          <span className="material-symbols-outlined text-text-muted group-focus-within:text-rune-quest transition-colors mr-3">search</span>
          <input
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            className="bg-transparent border-none text-on-surface placeholder:text-text-tertiary w-full font-body-md text-body-md outline-none"
            placeholder="Search the grimoire..."
            type="text"
          />
          <button
            type="button"
            onClick={() => setShowFilter((s) => !s)}
            className="material-symbols-outlined text-text-muted hover:text-primary ml-3 transition-colors"
            style={{ color: hidden.size ? '#d4a93f' : undefined }}
            aria-label="Filter node types"
          >
            tune
          </button>
        </form>

        {showFilter && (
          <div className="mt-2 ml-auto w-56 bg-bg-panel border border-border-default rounded-lg p-3 shadow-[0_8px_30px_rgba(0,0,0,0.6)] float-right">
            <p className="font-label-md text-label-md text-text-muted uppercase tracking-widest mb-2">Show node types</p>
            {ALL_TYPES.map((t) => {
              const rune = RUNE[t]
              const visible = !hidden.has(t)
              return (
                <button
                  key={t}
                  onClick={() => toggleType(t)}
                  className="w-full flex items-center gap-2 py-1.5 text-left"
                  style={{ opacity: visible ? 1 : 0.4 }}
                >
                  <span className="material-symbols-outlined text-[18px]" style={{ color: rune.color }}>
                    {visible ? 'check_box' : 'check_box_outline_blank'}
                  </span>
                  <span className="font-body-sm text-body-sm text-on-surface">{rune.nav}</span>
                </button>
              )
            })}
          </div>
        )}
      </div>

      {graph && graph.nodes.length > 0 && (
        <Constellation
          graph={graph}
          selectedId={selected?.id ?? null}
          highlightType={highlightType}
          filterText={query}
          hiddenTypes={hidden}
          onSelect={setSelected}
        />
      )}

      {selected && (
        <NodeDetailPanel
          node={selected}
          connections={connections}
          edges={selectedEdges}
          onPrune={prune}
          onClose={() => setSelected(null)}
        />
      )}

      {!graph && !error && (
        <div className="absolute inset-0 flex items-center justify-center">
          <p className="font-headline-md text-headline-md text-text-tertiary animate-pulse">Inscribing the grimoire...</p>
        </div>
      )}
      {graph && graph.nodes.length === 0 && (
        <div className="absolute inset-0 flex items-center justify-center text-center px-6">
          <div>
            <p className="font-headline-md text-headline-md text-text-muted">The grimoire is empty</p>
            <p className="font-body-md text-body-md text-text-tertiary mt-2">Scribe your first node to begin the constellation.</p>
          </div>
        </div>
      )}
      {error && (
        <div className="absolute inset-0 flex items-center justify-center text-center px-6">
          <div>
            <p className="font-headline-sm text-headline-sm text-status-error">Could not reach the knowledge service</p>
            <p className="font-body-sm text-body-sm text-text-tertiary mt-2">{error}. Is the API running on :8731?</p>
          </div>
        </div>
      )}
    </main>
  )
}
