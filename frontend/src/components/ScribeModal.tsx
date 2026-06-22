import { useState } from 'react'
import { api, type NewNode } from '../api'
import { RUNE } from '../theme'
import { useAppState } from '../state'

type Creatable = NewNode['type'] // 'project' | 'document' | 'entity'

const TYPES: { value: Creatable; label: string }[] = [
  { value: 'project', label: RUNE.project.label }, // Quest line
  { value: 'document', label: RUNE.document.label }, // Tome
  { value: 'entity', label: RUNE.entity.label }, // Rune
]

export default function ScribeModal() {
  const { scribeOpen, setScribeOpen, refreshGraph } = useAppState()
  const [type, setType] = useState<Creatable>('project')
  const [title, setTitle] = useState('')
  const [context, setContext] = useState('')
  const [project, setProject] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  if (!scribeOpen) return null

  function close() {
    setTitle('')
    setContext('')
    setProject('')
    setType('project')
    setError(null)
    setScribeOpen(false)
  }

  async function submit(e: React.FormEvent) {
    e.preventDefault()
    if (!title.trim()) return
    setBusy(true)
    setError(null)
    try {
      const payload: NewNode = { type, title: title.trim() }
      if (context.trim()) payload.context = context.trim()
      if (type !== 'project' && project.trim()) payload.project = project.trim()
      await api.createNode(payload)
      refreshGraph()
      close()
    } catch (err) {
      setError(String(err))
    } finally {
      setBusy(false)
    }
  }

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 backdrop-blur-sm"
      onClick={close}
    >
      <form
        onClick={(e) => e.stopPropagation()}
        onSubmit={submit}
        className="w-full max-w-md mx-4 bg-bg-panel border border-border-default rounded-xl border-t-2 border-t-primary-container shadow-[0_0_40px_rgba(0,0,0,0.8)]"
      >
        <div className="px-6 py-4 border-b border-border-subtle flex items-center justify-between">
          <h2 className="font-headline-sm text-headline-sm text-primary flex items-center gap-2">
            <span className="material-symbols-outlined">add</span> Scribe a new node
          </h2>
          <button type="button" onClick={close} className="text-text-muted hover:text-on-surface">
            <span className="material-symbols-outlined text-[20px]">close</span>
          </button>
        </div>

        <div className="px-6 py-5 space-y-5">
          {/* type selector */}
          <div>
            <label className="font-label-md text-label-md text-text-muted uppercase tracking-widest">Node type</label>
            <div className="mt-2 grid grid-cols-3 gap-2">
              {TYPES.map((t) => {
                const rune = RUNE[t.value]
                const active = type === t.value
                return (
                  <button
                    type="button"
                    key={t.value}
                    onClick={() => setType(t.value)}
                    className="flex flex-col items-center gap-1 py-3 rounded-lg border transition-all duration-200"
                    style={{
                      borderColor: active ? rune.color : '#29263f',
                      backgroundColor: active ? `${rune.color}1a` : 'transparent',
                      boxShadow: active ? `0 0 12px ${rune.color}55` : 'none',
                    }}
                  >
                    <span className="material-symbols-outlined" style={{ color: rune.color }}>{rune.icon}</span>
                    <span className="font-label-md text-label-md" style={{ color: active ? rune.color : '#9b96b8' }}>{t.label}</span>
                  </button>
                )
              })}
            </div>
          </div>

          {/* title */}
          <div>
            <label className="font-label-md text-label-md text-text-muted uppercase tracking-widest">Title</label>
            <input
              autoFocus
              value={title}
              onChange={(e) => setTitle(e.target.value)}
              placeholder="A name for this node"
              className="mt-1 w-full bg-transparent border-0 border-b border-border-default focus:border-rune-quest outline-none py-2 font-body-md text-body-md text-on-surface placeholder:text-text-tertiary transition-colors"
            />
          </div>

          {/* context */}
          <div>
            <label className="font-label-md text-label-md text-text-muted uppercase tracking-widest">
              {type === 'project' ? 'Context summary' : 'Notes (optional)'}
            </label>
            <textarea
              value={context}
              onChange={(e) => setContext(e.target.value)}
              rows={3}
              placeholder={type === 'project' ? 'What is this quest line about?' : 'Optional body or notes'}
              className="mt-1 w-full bg-surface-container-low border border-border-default rounded focus:border-rune-quest outline-none p-3 font-body-sm text-body-sm text-on-surface placeholder:text-text-tertiary transition-colors resize-none"
            />
          </div>

          {/* link to quest line (rune/tome only) */}
          {type !== 'project' && (
            <div>
              <label className="font-label-md text-label-md text-text-muted uppercase tracking-widest">Link to quest line (optional)</label>
              <input
                value={project}
                onChange={(e) => setProject(e.target.value)}
                placeholder="Existing project name"
                className="mt-1 w-full bg-transparent border-0 border-b border-border-default focus:border-rune-quest outline-none py-2 font-body-md text-body-md text-on-surface placeholder:text-text-tertiary transition-colors"
              />
            </div>
          )}

          {error && <p className="font-body-sm text-body-sm text-status-error">{error}</p>}
        </div>

        <div className="px-6 py-4 border-t border-border-subtle flex justify-end gap-3">
          <button type="button" onClick={close} className="py-2 px-4 font-label-md text-label-md text-text-muted hover:text-on-surface uppercase tracking-wider">
            Cancel
          </button>
          <button
            type="submit"
            disabled={busy || !title.trim()}
            className="py-2 px-4 bg-surface text-primary-container border border-primary-container rounded hover:bg-bg-surface hover:shadow-[0_0_15px_0px_rgba(227,211,160,0.3)] transition-all duration-300 font-label-md text-label-md uppercase tracking-wider disabled:opacity-40"
          >
            {busy ? 'Inscribing...' : 'Inscribe'}
          </button>
        </div>
      </form>
    </div>
  )
}
