import { useState } from 'react'
import { planner, type ChatResponse } from '../../api'

interface Props {
  placeholder?: string
  context?: Record<string, unknown>
  quickPrompts?: string[]
  onActed?: () => void
}

// The in-tab capture bar (Groq + Llama, capped tool surface). Fixed to the bottom of
// the Today and Flow tabs. Captures/edits items by sentence; analytical asks are
// redirected to Claude Desktop by the agent itself.
export default function PlannerChat({ placeholder = 'Transmute thought to task...', context, quickPrompts, onActed }: Props) {
  const [value, setValue] = useState('')
  const [busy, setBusy] = useState(false)
  const [last, setLast] = useState<ChatResponse | null>(null)

  async function send(override?: string) {
    const message = (override ?? value).trim()
    if (!message || busy) return
    setBusy(true)
    setValue('')
    try {
      const res = await planner.chat(message, context)
      setLast(res)
      if (res.actions.some((a) => (a.result as { ok?: boolean }).ok)) onActed?.()
    } catch (e) {
      setLast({ reply: `the agent could not be reached (${e}).`, actions: [], error: true })
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="fixed bottom-0 md:bottom-md left-0 right-0 md:left-64 flex justify-center px-4 pointer-events-none z-50 pb-4">
      <div className="w-full max-w-2xl pointer-events-auto">
        {quickPrompts && quickPrompts.length > 0 && (
          <div className="flex gap-2 justify-center mb-2 flex-wrap">
            {quickPrompts.map((p) => (
              <button key={p} onClick={() => send(p)} disabled={busy}
                className="font-label-md text-label-md text-text-muted bg-bg-panel/80 backdrop-blur border border-border-default rounded-full px-3 py-1.5 hover:border-rune-entity/50 hover:text-on-surface transition-colors disabled:opacity-40">
                {p}
              </button>
            ))}
          </div>
        )}
        {last && (
          <div className="mb-2 bg-bg-panel/90 backdrop-blur-xl border border-border-default rounded-lg px-4 py-3 shadow-[0_8px_30px_rgba(0,0,0,0.6)]">
            <p className={`font-body-sm text-body-sm ${last.error ? 'text-status-error' : 'text-on-surface'}`}>{last.reply}</p>
            {last.actions.filter((a) => (a.result as { ok?: boolean }).ok).map((a, i) => (
              <p key={i} className="font-label-md text-label-md text-rune-quest uppercase tracking-wider mt-1.5 flex items-center gap-1">
                <span className="material-symbols-outlined text-[14px]">check_small</span>
                {a.tool.replace(/_/g, ' ')}
              </p>
            ))}
          </div>
        )}
        <div className="grimoire-card rounded-full p-1 pl-4 flex items-center shadow-[0_-10px_40px_rgba(12,11,20,0.9)] backdrop-blur-xl bg-bg-surface/90 border border-border-default focus-within:border-rune-entity/50 focus-within:shadow-[0_0_20px_rgba(157,107,217,0.2)] transition-all">
          <span className="material-symbols-outlined text-text-tertiary mr-2">{busy ? 'hourglass_top' : 'add_circle'}</span>
          <input
            value={value}
            onChange={(e) => setValue(e.target.value)}
            onKeyDown={(e) => e.key === 'Enter' && send()}
            disabled={busy}
            className="flex-1 bg-transparent border-none text-on-surface font-body-md text-body-md focus:outline-none placeholder:text-text-tertiary py-3"
            placeholder={placeholder}
          />
          <button
            onClick={() => send()}
            disabled={busy}
            className="w-10 h-10 rounded-full bg-rune-entity/20 text-rune-entity flex items-center justify-center hover:bg-rune-entity hover:text-bg-page transition-colors ml-2 shrink-0 disabled:opacity-40"
            aria-label="Send to capture agent"
          >
            <span className="material-symbols-outlined">north</span>
          </button>
        </div>
      </div>
    </div>
  )
}
