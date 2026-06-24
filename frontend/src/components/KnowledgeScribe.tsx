import { useRef, useState } from 'react'
import { api } from '../api'
import { RUNE, type NodeType } from '../theme'

type Result = { id: string; type: NodeType; title: string; project?: string } | { error: string }

const ACCEPT = '.pdf,.epub,.fb2,.xps,.mobi,.cbz,.html,.htm,.md,.markdown,.txt'

// Quick-capture for the constellation: type a sentence, an LLM scribes it into the
// right node (memory / entity / document / quest line) and files it under a project.
export default function KnowledgeScribe({ onScribed }: { onScribed: () => void }) {
  const [value, setValue] = useState('')
  const [busy, setBusy] = useState(false)
  const [status, setStatus] = useState<string | null>(null)
  const [last, setLast] = useState<Result | null>(null)
  const fileInput = useRef<HTMLInputElement>(null)

  async function send() {
    const message = value.trim()
    if (!message || busy) return
    setBusy(true)
    setValue('')
    setStatus(null)
    try {
      const r = await api.scribe(message)
      setLast(r)
      onScribed()
    } catch (e) {
      setLast({ error: String(e) })
    } finally {
      setBusy(false)
    }
  }

  async function onFiles(fileList: FileList | null) {
    const files = fileList ? Array.from(fileList) : []
    if (!files.length || busy) return
    const project = value.trim() || undefined // the text box doubles as the target quest line
    setBusy(true)
    setStatus(`ingesting ${files.length} file${files.length > 1 ? 's' : ''}... (large books take a moment)`)
    setLast(null)
    try {
      const r = await api.ingest(files, project)
      const ok = r.ingested.filter((x) => !x.error)
      const failed = r.ingested.filter((x) => x.error)
      if (ok.length) {
        setLast({ id: '', type: 'document',
          title: ok.length === 1 ? (ok[0].title || ok[0].filename) : `${ok.length} documents`,
          project: r.project })
      }
      if (failed.length) {
        setLast({ error: `${failed.length} failed: ${failed.map((f) => f.filename).join(', ')}` })
      }
      setValue('')
      onScribed()
    } catch (e) {
      setLast({ error: String(e) })
    } finally {
      setBusy(false)
      setStatus(null)
      if (fileInput.current) fileInput.current.value = ''
    }
  }

  const ok = last && !('error' in last) ? last : null
  const err = last && 'error' in last ? last.error : null
  const accent = ok ? RUNE[ok.type].color : '#d4a93f'

  return (
    <div className="absolute bottom-6 left-1/2 -translate-x-1/2 w-full max-w-xl px-4 z-30">
      {(ok || err || status) && (
        <div className="mb-2 bg-bg-panel/90 backdrop-blur-md border border-border-default rounded-lg px-4 py-2.5 shadow-[0_8px_30px_rgba(0,0,0,0.6)]">
          {status ? (
            <p className="font-body-sm text-body-sm text-text-muted animate-pulse">{status}</p>
          ) : ok ? (
            <p className="font-body-sm text-body-sm text-on-surface flex items-center gap-2">
              <span className="material-symbols-outlined text-[16px]" style={{ color: accent }}>{RUNE[ok.type].icon}</span>
              inscribed {RUNE[ok.type].label.toLowerCase()} <span className="text-on-surface-variant">"{ok.title}"</span>
              {ok.project && <span className="text-text-tertiary">under {ok.project}</span>}
            </p>
          ) : (
            <p className="font-body-sm text-body-sm text-status-error">{err}</p>
          )}
        </div>
      )}
      <div
        className="bg-bg-panel/80 backdrop-blur-md border border-border-default rounded-full shadow-[0_4px_30px_rgba(0,0,0,0.5)] flex items-center px-4 py-3 group focus-within:border-rune-quest focus-within:shadow-[0_0_20px_rgba(212,169,63,0.2)] transition-all duration-300"
      >
        <span className="material-symbols-outlined mr-3 transition-colors" style={{ color: busy ? '#d4a93f' : undefined }}>
          {busy ? 'hourglass_top' : 'edit_note'}
        </span>
        <input
          value={value}
          onChange={(e) => setValue(e.target.value)}
          onKeyDown={(e) => e.key === 'Enter' && send()}
          disabled={busy}
          className="bg-transparent border-none text-on-surface placeholder:text-text-tertiary w-full font-body-md text-body-md outline-none"
          placeholder="Scribe a thought, or attach a PDF / book..."
        />
        <input ref={fileInput} type="file" accept={ACCEPT} multiple className="hidden"
          onChange={(e) => onFiles(e.target.files)} />
        <button
          onClick={() => fileInput.current?.click()}
          disabled={busy}
          title="Attach documents, books, or PDFs (the text box sets the quest line)"
          className="w-9 h-9 rounded-full text-text-muted flex items-center justify-center hover:text-rune-quest hover:bg-rune-quest/10 transition-colors shrink-0 disabled:opacity-40"
          aria-label="Attach files"
        >
          <span className="material-symbols-outlined text-[20px]">attach_file</span>
        </button>
        <button
          onClick={send}
          disabled={busy}
          className="w-9 h-9 rounded-full bg-rune-quest/20 text-rune-quest flex items-center justify-center hover:bg-rune-quest hover:text-bg-page transition-colors ml-1 shrink-0 disabled:opacity-40"
          aria-label="Scribe"
        >
          <span className="material-symbols-outlined text-[20px]">north</span>
        </button>
      </div>
    </div>
  )
}
