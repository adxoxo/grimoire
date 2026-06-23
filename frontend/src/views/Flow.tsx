import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { planner, type Anchor, type Block, type FlowData, type PlanResult } from '../api'
import { localDate } from '../theme'
import PlannerChat from '../components/planner/PlannerChat'
import InlineEdit from '../components/planner/InlineEdit'

const PX_PER_MIN = 1.15

function combine(date: string, hhmm: string): Date {
  const [h, m] = hhmm.split(':').map(Number)
  const d = new Date(`${date}T00:00:00`)
  d.setHours(h, m, 0, 0)
  return d
}
function clock(iso: string): string {
  return new Date(iso).toLocaleTimeString(undefined, { hour: '2-digit', minute: '2-digit' })
}
function hhmmFromIso(iso: string | null, fallback: string): string {
  if (!iso) return fallback
  const d = new Date(iso)
  return `${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}`
}

const BLOCK_STYLE: Record<Block['type'], { color: string; label: string }> = {
  anchor: { color: '#5b8dd9', label: 'Anchor' },
  habit: { color: '#d4a93f', label: 'Ritual' },
  task: { color: '#cdc6b7', label: 'Task' },
  goal: { color: '#d98b4a', label: 'Apex goal' },
  break: { color: '#9d6bd9', label: 'Break' },
}

// ---- timeline (draggable / renamable / deletable blocks) ---------------------

function Timeline({ blocks, windowStart, windowEnd, overlay, onMove, onRename, onDelete }: {
  blocks: Block[]
  windowStart: Date
  windowEnd: Date
  overlay: FlowData['overlay']
  onMove: (index: number, newStartISO: string) => void
  onRename: (index: number, title: string) => void
  onDelete: (index: number) => void
}) {
  const containerRef = useRef<HTMLDivElement>(null)
  const [drag, setDrag] = useState<{ i: number; grab: number; topPx: number } | null>(null)
  const [editing, setEditing] = useState<number | null>(null)

  // The frame is FIXED to the chosen wake -> sleep window. Generating later in the day
  // fills only from "now" onward, but the calendar stays the same shape: the elapsed
  // morning sits empty above the current-time line.
  const now = new Date()
  const lo = windowStart.getTime()
  const hi = windowEnd.getTime()
  const totalMin = Math.max(60, (hi - lo) / 60000)
  const height = totalMin * PX_PER_MIN
  const topPxOf = (ms: number) => ((ms - lo) / 60000) * PX_PER_MIN
  const durMin = (b: Block) => (new Date(b.end).getTime() - new Date(b.start).getTime()) / 60000

  const hours: Date[] = []
  const first = new Date(lo); first.setMinutes(0, 0, 0); if (first.getTime() < lo) first.setHours(first.getHours() + 1)
  for (let t = new Date(first); t.getTime() <= hi; t.setHours(t.getHours() + 1)) hours.push(new Date(t))

  // pointer drag: move a block to a new time slot (snap to 5 min)
  useEffect(() => {
    if (!drag) return
    function onMoveEvt(e: MouseEvent) {
      const rect = containerRef.current?.getBoundingClientRect()
      if (!rect) return
      const blockPx = durMin(blocks[drag!.i]) * PX_PER_MIN
      let topPx = e.clientY - rect.top - drag!.grab
      topPx = Math.max(0, Math.min(topPx, height - blockPx))
      setDrag((d) => (d ? { ...d, topPx } : d))
    }
    function onUp() {
      setDrag((d) => {
        if (d) {
          const snapped = Math.round((d.topPx / PX_PER_MIN) / 5) * 5
          onMove(d.i, new Date(lo + snapped * 60000).toISOString())
        }
        return null
      })
    }
    window.addEventListener('mousemove', onMoveEvt)
    window.addEventListener('mouseup', onUp)
    return () => { window.removeEventListener('mousemove', onMoveEvt); window.removeEventListener('mouseup', onUp) }
  }, [drag, blocks, height, lo, onMove])

  return (
    <div ref={containerRef} className="relative ml-14 select-none" style={{ height }}>
      {/* hour gridlines */}
      {hours.map((h, i) => (
        <div key={i} className="absolute left-0 right-0 flex items-center" style={{ top: topPxOf(h.getTime()) }}>
          <span className="absolute -left-14 -translate-y-1/2 font-label-md text-[10px] text-text-tertiary tabular-nums">
            {h.toLocaleTimeString(undefined, { hour: '2-digit', minute: '2-digit' })}
          </span>
          <div className="w-full border-t border-border-subtle/60" />
        </div>
      ))}

      {/* IF eating window band */}
      {overlay && (
        <div className="absolute left-0 right-0 rounded bg-rune-chronicle/5 border-y border-rune-chronicle/20 pointer-events-none"
          style={{
            top: topPxOf(new Date(overlay.eating_start).getTime()),
            height: Math.max(0, durMin({ start: overlay.eating_start, end: overlay.eating_end } as Block)) * PX_PER_MIN,
          }}>
          <span className="absolute top-1 right-2 font-label-md text-[9px] uppercase tracking-widest text-rune-chronicle/70 flex items-center gap-1">
            <span className="material-symbols-outlined text-[12px]">restaurant</span>eating window
          </span>
        </div>
      )}

      {/* blocks */}
      {blocks.map((b, i) => {
        const dragging = drag?.i === i
        const top = dragging ? drag!.topPx : topPxOf(new Date(b.start).getTime())
        const h = Math.max(30, durMin(b) * PX_PER_MIN)
        const s = BLOCK_STYLE[b.type]
        const apex = b.goal_block
        const startLabel = clock(new Date(lo + (top / PX_PER_MIN) * 60000).toISOString())
        return (
          <div key={i}
            onMouseDown={(e) => {
              if ((e.target as HTMLElement).closest('button,input')) return
              if (editing === i) return
              const rect = containerRef.current!.getBoundingClientRect()
              const blockTop = topPxOf(new Date(b.start).getTime())
              setDrag({ i, grab: e.clientY - rect.top - blockTop, topPx: blockTop })
            }}
            className={`absolute left-2 right-2 rounded-lg px-4 py-2 overflow-hidden group ${apex ? 'border-2' : 'border'} ${dragging ? 'cursor-grabbing z-30 shadow-2xl' : 'cursor-grab transition-all'} ${b.locked ? 'opacity-80' : ''}`}
            style={{
              top, height: h,
              borderColor: apex ? s.color : `${s.color}55`,
              background: apex ? `${s.color}1f` : 'rgba(22,20,43,0.92)',
              boxShadow: dragging ? `0 8px 30px rgba(0,0,0,0.6), 0 0 0 1px ${s.color}` : apex ? `0 0 24px ${s.color}30` : 'inset 0 1px 0 rgba(255,255,255,0.05)',
            }}>
            <div className="absolute top-0 left-0 w-1 h-full" style={{ background: s.color }} />
            <div className="flex items-center justify-between gap-2">
              <span className="font-label-md text-[9px] uppercase tracking-widest" style={{ color: s.color }}>
                {apex ? '★ apex goal' : b.kind === 'hard' ? 'pinned' : s.label}
              </span>
              <div className="flex items-center gap-1.5">
                <span className="font-label-md text-[10px] text-text-tertiary tabular-nums">{startLabel}</span>
                {b.locked && <span className="material-symbols-outlined text-[12px] text-text-tertiary">lock</span>}
                <button onClick={() => onDelete(i)} onMouseDown={(e) => e.stopPropagation()}
                  className="material-symbols-outlined text-[13px] text-text-tertiary opacity-0 group-hover:opacity-100 hover:text-status-error transition-all"
                  aria-label="Remove block">close</button>
              </div>
            </div>
            <div className="mt-0.5">
              <InlineEdit value={b.title} onSave={(t) => onRename(i, t)} showPencil={false}
                editing={editing === i} onEditingChange={(on) => setEditing(on ? i : null)}
                textClassName={`${apex ? 'font-headline-sm' : 'font-body-md'} text-body-md text-on-surface leading-tight`}
                inputClassName="w-full bg-surface-container-low border border-rune-entity/60 rounded px-1.5 py-0.5 text-on-surface font-body-md text-body-md focus:outline-none" />
            </div>
          </div>
        )
      })}

      {/* current-time marker */}
      {now.getTime() >= lo && now.getTime() <= hi && (
        <div className="absolute left-0 right-0 z-20 pointer-events-none" style={{ top: topPxOf(now.getTime()) }}>
          <div className="flex items-center">
            <span className="absolute -left-14 -translate-y-1/2 font-label-md text-[10px] text-rune-entity font-bold">{clock(now.toISOString())}</span>
            <div className="w-full border-t-2 border-rune-entity/70" />
            <div className="absolute left-0 w-2 h-2 rounded-full bg-rune-entity -translate-y-1/2 shadow-[0_0_8px_rgba(157,107,217,0.8)]" />
          </div>
        </div>
      )}
    </div>
  )
}

// ---- anchors panel -----------------------------------------------------------

function AnchorsPanel({ date, anchors, onChange }: { date: string; anchors: Anchor[]; onChange: () => void }) {
  const [open, setOpen] = useState(false)
  const [title, setTitle] = useState('')
  const [kind, setKind] = useState<'hard' | 'soft'>('hard')
  const [time, setTime] = useState('14:00')
  const [winStart, setWinStart] = useState('12:00')
  const [winEnd, setWinEnd] = useState('14:00')
  const [dur, setDur] = useState('60')

  async function add() {
    if (!title.trim()) return
    await planner.createAnchor({
      title: title.trim(), date, kind, duration_minutes: Number(dur) || 30,
      start: kind === 'hard' ? combine(date, time).toISOString() : undefined,
      window_start: kind === 'soft' ? winStart : undefined,
      window_end: kind === 'soft' ? winEnd : undefined,
    })
    setTitle(''); setOpen(false); onChange()
  }

  const field = 'bg-surface-container-low border border-border-default rounded px-2 py-1.5 text-on-surface font-body-sm text-body-sm focus:outline-none focus:border-rune-tome/60'

  return (
    <div>
      <div className="flex justify-between items-center mb-2">
        <h4 className="font-label-md text-label-md text-text-muted uppercase tracking-widest">Anchors</h4>
        <button onClick={() => setOpen((o) => !o)} className="material-symbols-outlined text-[18px] text-text-tertiary hover:text-on-surface">{open ? 'close' : 'add'}</button>
      </div>
      <div className="space-y-1.5">
        {anchors.length === 0 && !open && <p className="font-body-sm text-body-sm text-text-tertiary">No anchors. Pin a call or window the day.</p>}
        {anchors.map((a) => (
          <div key={a.id} className="flex items-center gap-2 bg-surface-container-low/50 border border-border-subtle rounded px-2 py-1.5">
            <span className="w-1.5 h-1.5 rounded-full shrink-0" style={{ background: a.kind === 'hard' ? '#5b8dd9' : '#9d6bd9' }} />
            <span className="font-body-sm text-body-sm text-on-surface flex-1 truncate">{a.title}</span>
            <span className="font-label-md text-[9px] text-text-tertiary">{a.kind === 'hard' && a.start ? clock(a.start) : `${a.window_start ?? ''}–${a.window_end ?? ''}`}</span>
            <button onClick={async () => { await planner.deleteAnchor(a.id); onChange() }} className="material-symbols-outlined text-[14px] text-text-tertiary hover:text-status-error">close</button>
          </div>
        ))}
      </div>
      {open && (
        <div className="mt-2 space-y-2 bg-surface-container-low/40 border border-border-subtle rounded p-2">
          <input value={title} onChange={(e) => setTitle(e.target.value)} placeholder="anchor title" className={`${field} w-full`} />
          <div className="flex gap-2">
            <select value={kind} onChange={(e) => setKind(e.target.value as 'hard' | 'soft')} className={`${field} flex-1`}>
              <option value="hard">Hard (pinned)</option>
              <option value="soft">Soft (window)</option>
            </select>
            <input value={dur} onChange={(e) => setDur(e.target.value)} type="number" className={`${field} w-20`} placeholder="min" />
          </div>
          {kind === 'hard' ? (
            <input value={time} onChange={(e) => setTime(e.target.value)} type="time" className={`${field} w-full`} />
          ) : (
            <div className="flex gap-2 items-center">
              <input value={winStart} onChange={(e) => setWinStart(e.target.value)} type="time" className={`${field} flex-1`} />
              <span className="text-text-tertiary">–</span>
              <input value={winEnd} onChange={(e) => setWinEnd(e.target.value)} type="time" className={`${field} flex-1`} />
            </div>
          )}
          <button onClick={add} className="w-full py-1.5 bg-surface text-rune-tome border border-rune-tome/50 rounded hover:bg-rune-tome/10 font-label-md text-label-md uppercase tracking-wider">Add anchor</button>
        </div>
      )}
    </div>
  )
}

// ---- the tab -----------------------------------------------------------------

export default function Flow() {
  const date = localDate()
  const [flow, setFlow] = useState<FlowData | null>(null)
  const [result, setResult] = useState<PlanResult | null>(null)
  const [blocks, setBlocks] = useState<Block[]>([])
  const [wake, setWake] = useState('08:00')
  const [sleep, setSleep] = useState('23:00')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const load = useCallback(() => {
    planner.flow(date).then((f) => {
      setFlow(f)
      setBlocks(f.plan?.blocks ?? [])
      if (f.plan) {
        setWake(hhmmFromIso(f.plan.wake_time, '08:00'))
        setSleep(hhmmFromIso(f.plan.sleep_target, '23:00'))
      }
    }).catch((e) => setError(String(e)))
  }, [date])
  useEffect(load, [load])

  // Persist a block edit (drag / rename / delete) and keep the view in sync.
  const saveBlocks = useCallback((next: Block[]) => {
    setBlocks(next)
    planner.saveBlocks(date, next).catch((e) => setError(String(e)))
  }, [date])

  const moveBlock = useCallback((i: number, newStartISO: string) => {
    setBlocks((prev) => {
      const b = prev[i]
      const dur = new Date(b.end).getTime() - new Date(b.start).getTime()
      const next = prev.map((x, j) => j === i
        ? { ...x, start: newStartISO, end: new Date(new Date(newStartISO).getTime() + dur).toISOString(), locked: true }
        : x)
      planner.saveBlocks(date, next).catch((e) => setError(String(e)))
      return next
    })
  }, [date])

  const renameBlock = useCallback((i: number, title: string) => {
    setBlocks((prev) => { const next = prev.map((x, j) => j === i ? { ...x, title } : x); saveBlocks(next); return next })
  }, [saveBlocks])

  const deleteBlock = useCallback((i: number) => {
    setBlocks((prev) => { const next = prev.filter((_, j) => j !== i); saveBlocks(next); return next })
  }, [saveBlocks])

  // The fixed calendar frame: wake -> sleep (sleep rolls to next day if it's "earlier").
  const windowDates = useMemo(() => {
    const start = combine(date, wake)
    let end = combine(date, sleep)
    if (end <= start) end = new Date(end.getTime() + 86400000)
    return { start, end }
  }, [date, wake, sleep])

  const windowLabel = useMemo(() => {
    const min = Math.round((windowDates.end.getTime() - windowDates.start.getTime()) / 60000)
    return `${Math.floor(min / 60)}h ${min % 60}m`
  }, [windowDates])

  async function generate() {
    setBusy(true); setError(null)
    try {
      const w = combine(date, wake)
      let s = combine(date, sleep)
      if (s <= w) s = new Date(s.getTime() + 86400000)
      const r = await planner.generateDay({
        date, wake_time: w.toISOString(), sleep_target: s.toISOString(),
        now: new Date().toISOString(), // start from the present, not the elapsed morning
        if_enabled: flow?.plan?.if_enabled, first_meal: flow?.plan?.first_meal ?? undefined,
        eating_hours: flow?.plan?.eating_hours,
      })
      setResult(r); setBlocks(r.blocks)
    } catch (e) { setError(String(e)) } finally { setBusy(false) }
  }

  async function reflow() {
    setBusy(true); setError(null)
    try {
      const r = await planner.reflow({ date, now: new Date().toISOString() })
      setResult(r); setBlocks(r.blocks)
    } catch (e) { setError(`reflow needs a day plan first — generate one. (${e})`) } finally { setBusy(false) }
  }

  async function toggleIF() {
    if (!flow?.plan) return
    const next = !flow.plan.if_enabled
    const first = flow.plan.first_meal ?? new Date().toISOString()
    await planner.flowMeta(date, { if_enabled: next, first_meal: next ? first : undefined })
    load()
  }

  async function saveTemplate() {
    const name = prompt('Name this day-shape (e.g. "deep work day")')
    if (!name) return
    await planner.saveTemplate(name, date); load()
  }

  const overlay = flow?.overlay ?? null // overlay is recomputed server-side and refetched on load
  const notice = result?.notice ?? null
  const deferred = result?.deferred ?? []

  return (
    <main className="min-h-screen pb-48 overflow-y-auto">
      <div className="max-w-[1200px] mx-auto px-6 md:px-margin py-lg mt-4 md:mt-8">
        {/* day setup bar */}
        <div className="grimoire-card rounded-xl p-4 flex flex-wrap items-center gap-4 md:gap-6 mb-lg">
          <div>
            <label className="font-label-md text-label-md text-text-muted uppercase tracking-widest block mb-1">Woke at</label>
            <div className="flex items-center gap-2">
              <span className="material-symbols-outlined text-rune-quest text-[18px]">wb_twilight</span>
              <input type="time" value={wake} onChange={(e) => setWake(e.target.value)} className="bg-surface-container-low border border-border-default rounded px-2 py-1.5 text-on-surface font-body-md text-body-md focus:outline-none focus:border-rune-quest/60" />
            </div>
          </div>
          <div className="font-label-md text-label-md text-text-tertiary self-end pb-2">window {windowLabel}</div>
          <div>
            <label className="font-label-md text-label-md text-text-muted uppercase tracking-widest block mb-1">Sleeping around</label>
            <div className="flex items-center gap-2">
              <span className="material-symbols-outlined text-rune-entity text-[18px]">bedtime</span>
              <input type="time" value={sleep} onChange={(e) => setSleep(e.target.value)} className="bg-surface-container-low border border-border-default rounded px-2 py-1.5 text-on-surface font-body-md text-body-md focus:outline-none focus:border-rune-entity/60" />
            </div>
          </div>
          <div className="flex-1" />
          <button onClick={reflow} disabled={busy} className="flex items-center gap-2 py-2 px-4 border border-border-default rounded text-on-surface hover:border-rune-entity/60 transition-colors font-label-md text-label-md uppercase tracking-wider disabled:opacity-40">
            <span className="material-symbols-outlined text-[18px]">refresh</span>Reflow from now
          </button>
          <button onClick={generate} disabled={busy} className="flex items-center gap-2 py-2 px-5 bg-rune-entity/20 text-rune-entity border border-rune-entity/50 rounded hover:bg-rune-entity hover:text-bg-page transition-all font-label-md text-label-md uppercase tracking-wider disabled:opacity-40">
            <span className="material-symbols-outlined text-[18px]">auto_awesome</span>{busy ? 'Weaving...' : 'Generate my day'}
          </button>
        </div>

        {error && <p className="font-body-sm text-body-sm text-status-error mb-4">{error}</p>}

        <div className="flex flex-col lg:flex-row gap-lg">
          {/* timeline */}
          <div className="flex-1 min-w-0">
            <h2 className="font-headline-md text-headline-md text-primary mb-4 flex items-center gap-2">
              <span className="material-symbols-outlined">view_timeline</span>The flow
            </h2>
            {blocks.length > 0 ? (
              <>
                <Timeline blocks={blocks} windowStart={windowDates.start} windowEnd={windowDates.end}
                  overlay={overlay} onMove={moveBlock} onRename={renameBlock} onDelete={deleteBlock} />
                <p className="font-body-sm text-body-sm text-text-tertiary mt-3 ml-14">drag a block to reschedule it · double-click to rename · hover for delete</p>
              </>
            ) : (
              <div className="border border-dashed border-border-default rounded-xl py-20 text-center">
                <span className="material-symbols-outlined text-[40px] text-border-default mb-2">bedtime</span>
                <p className="font-body-md text-body-md text-text-muted">Set your window and weave the day.</p>
                <p className="font-body-sm text-body-sm text-text-tertiary mt-1">The schedule is a proposal. The goals are the constant.</p>
              </div>
            )}
          </div>

          {/* intentions panel */}
          <aside className="lg:w-80 shrink-0 space-y-md">
            <h2 className="font-headline-md text-headline-md text-primary flex items-center gap-2">
              Intentions
            </h2>

            {notice && (
              <div className="bg-rune-chronicle/5 border border-rune-chronicle/30 rounded-lg p-3">
                <p className="font-label-md text-label-md text-rune-chronicle uppercase tracking-wider flex items-center gap-1 mb-1">
                  <span className="material-symbols-outlined text-[16px]">warning</span>Gentle notice
                </p>
                <p className="font-body-sm text-body-sm text-on-surface-variant">{notice}</p>
              </div>
            )}

            {deferred.length > 0 && (
              <div>
                <h4 className="font-label-md text-label-md text-text-muted uppercase tracking-widest mb-2">Unscheduled pool</h4>
                <div className="flex flex-wrap gap-2">
                  {deferred.map((d, i) => (
                    <span key={i} title={d.reason} className="font-body-sm text-body-sm text-on-surface-variant bg-surface-container-low/60 border border-border-subtle rounded px-2 py-1">
                      {d.title}
                    </span>
                  ))}
                </div>
              </div>
            )}

            {/* IF overlay toggle */}
            <div className="grimoire-card rounded-lg p-3 flex items-center justify-between">
              <div>
                <p className="font-body-md text-body-md text-on-surface">Fasting overlay</p>
                <p className="font-body-sm text-body-sm text-text-tertiary">{flow?.plan?.if_enabled ? 'on · anchored to first meal' : 'off · pressure-free'}</p>
              </div>
              <button onClick={toggleIF} disabled={!flow?.plan}
                className={`w-11 h-6 rounded-full transition-colors relative ${flow?.plan?.if_enabled ? 'bg-rune-chronicle/60' : 'bg-surface-container-high'} disabled:opacity-40`}>
                <span className={`absolute top-0.5 w-5 h-5 rounded-full bg-on-surface transition-all ${flow?.plan?.if_enabled ? 'left-[22px]' : 'left-0.5'}`} />
              </button>
            </div>

            <div className="grimoire-card rounded-lg p-3">
              <AnchorsPanel date={date} anchors={flow?.anchors ?? []} onChange={load} />
            </div>

            {/* templates */}
            <div className="grimoire-card rounded-lg p-3">
              <div className="flex justify-between items-center mb-2">
                <h4 className="font-label-md text-label-md text-text-muted uppercase tracking-widest">Day-shapes</h4>
                <button onClick={saveTemplate} className="font-label-md text-label-md text-rune-quest hover:text-primary uppercase tracking-wider">Save</button>
              </div>
              <div className="flex flex-wrap gap-2">
                {(flow?.templates ?? []).length === 0 && <p className="font-body-sm text-body-sm text-text-tertiary">No saved shapes yet.</p>}
                {(flow?.templates ?? []).map((t) => (
                  <button key={t.template_id} onClick={async () => { await planner.loadTemplate(t.template_id, date); load() }}
                    className="font-body-sm text-body-sm text-on-surface-variant bg-surface-container-low/60 border border-border-subtle rounded px-2 py-1 hover:border-rune-quest/50">
                    {t.template_name} ({t.n})
                  </button>
                ))}
              </div>
            </div>
          </aside>
        </div>
      </div>

      <PlannerChat
        placeholder="Transmute thought to schedule..."
        context={{ date, now: new Date().toISOString() }}
        quickPrompts={['regenerate my day', 'add a 30m break', 'how long is my day']}
        onActed={load}
      />
    </main>
  )
}
