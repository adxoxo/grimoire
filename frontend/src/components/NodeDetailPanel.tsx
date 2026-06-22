import { useNavigate } from 'react-router-dom'
import type { GraphNode } from '../api'
import { RUNE } from '../theme'

interface Props {
  node: GraphNode
  connections: number
  onClose: () => void
}

export default function NodeDetailPanel({ node, connections, onClose }: Props) {
  const navigate = useNavigate()
  const rune = RUNE[node.type]
  const unreviewed = node.status === 'unreviewed'

  return (
    <aside
      className="absolute top-24 right-8 w-80 bg-bg-panel border border-border-default rounded-xl shadow-[0_0_20px_0px_rgba(0,0,0,0.8)] flex flex-col z-30 border-t-2"
      style={{ borderTopColor: rune.color }}
    >
      <div className="p-4 border-b border-border-subtle flex justify-between items-start">
        <div>
          <span
            className="inline-block px-2 py-1 font-label-md text-label-md rounded uppercase tracking-wider mb-2"
            style={{ color: rune.color, backgroundColor: `${rune.color}1a` }}
          >
            {rune.label}
          </span>
          <h3 className="font-headline-sm text-headline-sm text-primary leading-snug">{node.title}</h3>
        </div>
        <button className="text-text-muted hover:text-on-surface transition-colors" onClick={onClose} aria-label="Close">
          <span className="material-symbols-outlined text-[20px]">close</span>
        </button>
      </div>

      <div className="p-4 flex-1 space-y-3">
        <div className="flex items-center justify-between">
          <span className="font-label-md text-label-md text-text-muted uppercase tracking-wider">Status</span>
          <span className="font-label-md text-label-md flex items-center gap-2" style={{ color: rune.color }}>
            <span
              className={`w-2 h-2 rounded-full ${unreviewed ? 'svg-pulse' : ''}`}
              style={{ backgroundColor: rune.color, boxShadow: `0 0 8px ${rune.color}` }}
            />
            {node.status ?? 'unknown'}
          </span>
        </div>
        <div className="flex items-center justify-between">
          <span className="font-label-md text-label-md text-text-muted uppercase tracking-wider">Connections</span>
          <span className="font-label-md text-label-md text-on-surface">{connections} nodes</span>
        </div>
      </div>

      <div className="p-4 border-t border-border-subtle bg-surface-container-low rounded-b-xl">
        {node.type === 'project' && (
          <button
            className="w-full py-2 bg-surface text-primary-container border border-primary-container rounded hover:bg-bg-surface hover:shadow-[0_0_15px_0px_rgba(227,211,160,0.3)] transition-all duration-300 font-label-md text-label-md uppercase tracking-wider"
            onClick={() => navigate(`/project/${encodeURIComponent(node.title)}`)}
          >
            Open quest line
          </button>
        )}
        {node.type === 'document' && (
          <button
            className="w-full py-2 bg-surface text-rune-tome border border-rune-tome rounded hover:bg-bg-surface hover:shadow-[0_0_15px_0px_rgba(91,141,217,0.3)] transition-all duration-300 font-label-md text-label-md uppercase tracking-wider"
            onClick={() => navigate(`/tome/${encodeURIComponent(node.id)}`)}
          >
            Open tome
          </button>
        )}
        {(node.type === 'memory' || node.type === 'entity') && (
          <p className="font-body-sm text-body-sm text-text-tertiary text-center italic">
            Detailed {rune.label.toLowerCase()} view not yet inscribed
          </p>
        )}
      </div>
    </aside>
  )
}
