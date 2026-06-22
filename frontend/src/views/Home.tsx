import { useEffect, useMemo, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import { api, type Graph, type GraphNode } from '../api'
import type { NodeType } from '../theme'
import Constellation from '../components/Constellation'
import NodeDetailPanel from '../components/NodeDetailPanel'

export default function Home() {
  const [graph, setGraph] = useState<Graph | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [selected, setSelected] = useState<GraphNode | null>(null)
  const [query, setQuery] = useState('')
  const [params] = useSearchParams()
  const highlightType = (params.get('type') as NodeType | null) ?? null

  useEffect(() => {
    api.graph().then(setGraph).catch((e) => setError(String(e)))
  }, [])

  const connections = useMemo(() => {
    if (!graph || !selected) return 0
    return graph.edges.filter((e) => e.src === selected.id || e.dst === selected.id).length
  }, [graph, selected])

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
      // retrieval unavailable (e.g. Ollama down): fall back to a title match
    }
    const q = query.trim().toLowerCase()
    const hit = graph.nodes.find((n) => n.title.toLowerCase().includes(q))
    if (hit) setSelected(hit)
  }

  return (
    <main className="relative w-full h-screen bg-bg-page overflow-hidden">
      {/* Search overlay */}
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
          <span className="material-symbols-outlined text-text-muted ml-3">tune</span>
        </form>
      </div>

      {graph && graph.nodes.length > 0 && (
        <Constellation graph={graph} selectedId={selected?.id ?? null} highlightType={highlightType} onSelect={setSelected} />
      )}

      {selected && <NodeDetailPanel node={selected} connections={connections} onClose={() => setSelected(null)} />}

      {/* States */}
      {!graph && !error && (
        <div className="absolute inset-0 flex items-center justify-center">
          <p className="font-headline-md text-headline-md text-text-tertiary animate-pulse">Inscribing the grimoire...</p>
        </div>
      )}
      {graph && graph.nodes.length === 0 && (
        <div className="absolute inset-0 flex items-center justify-center text-center px-6">
          <div>
            <p className="font-headline-md text-headline-md text-text-muted">The grimoire is empty</p>
            <p className="font-body-md text-body-md text-text-tertiary mt-2">Inscribe your first node to begin the constellation.</p>
          </div>
        </div>
      )}
      {error && (
        <div className="absolute inset-0 flex items-center justify-center text-center px-6">
          <div>
            <p className="font-headline-sm text-headline-sm text-status-error">Could not reach the knowledge service</p>
            <p className="font-body-sm text-body-sm text-text-tertiary mt-2">{error}. Is the API running on :8000?</p>
          </div>
        </div>
      )}
    </main>
  )
}
