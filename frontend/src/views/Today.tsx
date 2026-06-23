import { useCallback, useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { api, planner, type Habit, type Task, type AreaGroup, type TodayData } from '../api'
import { QUADRANT, type Quadrant, localDate } from '../theme'
import PlannerChat from '../components/planner/PlannerChat'
import AddItemDialog from '../components/planner/AddItemDialog'
import InlineEdit from '../components/planner/InlineEdit'

const QUADRANT_ORDER: Quadrant[] = ['Q1', 'Q2', 'Q3', 'Q4']

// The flag combination each quadrant represents. Dropping a task onto a quadrant writes
// these (urgent as a manual override, so the placement wins over any computed urgency).
const Q_FLAGS: Record<Quadrant, { important: boolean; urgent: boolean }> = {
  Q1: { important: true, urgent: true },
  Q2: { important: true, urgent: false },
  Q3: { important: false, urgent: true },
  Q4: { important: false, urgent: false },
}

function fmtDateline(): string {
  const d = new Date()
  return d.toLocaleDateString(undefined, { weekday: 'long', month: 'short', day: 'numeric' }).toUpperCase()
}

// ---- habits strip ------------------------------------------------------------

function HabitPill({ habit, date, onToggle }: { habit: Habit; date: string; onToggle: () => void }) {
  const daily = habit.cadence_type === 'daily'
  const done = daily ? habit.progress?.done_today : habit.progress?.met
  const count = habit.progress?.count ?? 0
  const target = habit.progress?.target ?? habit.weekly_target ?? 1
  const streak = habit.streak?.current ?? 0

  async function toggle() {
    await planner.toggleHabit(habit.id, date)
    onToggle()
  }
  async function remove(e: React.MouseEvent) {
    e.stopPropagation()
    if (!confirm(`Delete ritual "${habit.name}"? Its streak history goes with it.`)) return
    await planner.deleteHabit(habit.id)
    onToggle()
  }
  async function rename(name: string) {
    await planner.modifyHabit(habit.id, { name })
    onToggle()
  }

  return (
    <div className="flex-shrink-0 flex items-center gap-2 pl-3 pr-2 py-2 rounded-full grimoire-card hover:border-rune-quest/50 transition-colors snap-start group">
      <button onClick={toggle} className="flex items-center gap-2 shrink-0" aria-label={`Toggle ${habit.name}`}>
        {daily ? (
          <span className={`w-5 h-5 rounded-full border flex items-center justify-center ${done ? 'border-rune-quest bg-rune-quest/20 shadow-[0_0_10px_rgba(212,169,63,0.4)]' : 'border-border-default'}`}>
            {done && <span className="w-2.5 h-2.5 rounded-full bg-rune-quest" />}
          </span>
        ) : (
          <span className="relative w-5 h-5 flex items-center justify-center">
            <svg className="w-full h-full -rotate-90" viewBox="0 0 24 24">
              <circle cx="12" cy="12" r="10" fill="none" stroke="#35333e" strokeWidth="2" />
              <circle cx="12" cy="12" r="10" fill="none" stroke={done ? '#d4a93f' : '#5b8dd9'} strokeWidth="2"
                strokeDasharray={62.8} strokeDashoffset={62.8 * (1 - Math.min(count / target, 1))} strokeLinecap="round" />
            </svg>
            <span className="absolute font-label-md text-[8px] text-on-surface-variant">{count}</span>
          </span>
        )}
      </button>
      <InlineEdit value={habit.name} onSave={rename} showPencil={false}
        textClassName={`font-body-md text-body-md cursor-pointer ${done ? 'text-on-surface' : 'text-on-surface-variant'}`} />
      {streak > 0 && (
        <span className="flex items-center text-secondary ml-0.5 shrink-0">
          <span className="material-symbols-outlined text-[14px]" style={{ fontVariationSettings: "'FILL' 1" }}>local_fire_department</span>
          <span className="font-label-md text-[10px]">{streak}</span>
        </span>
      )}
      <button onClick={remove}
        className="material-symbols-outlined text-[15px] text-text-tertiary opacity-0 group-hover:opacity-100 hover:text-status-error transition-all shrink-0"
        aria-label={`Delete ${habit.name}`}>close</button>
    </div>
  )
}

// ---- task chip ---------------------------------------------------------------

function TaskChip({ task, accent, onChange, questLine }: { task: Task; accent: string; onChange: () => void; questLine?: string }) {
  async function complete() {
    await planner.completeTask(task.id, true)
    onChange()
  }
  async function remove() {
    if (!confirm(`Delete "${task.title}"? This cannot be undone.`)) return
    await planner.deleteTask(task.id)
    onChange()
  }
  async function rename(title: string) {
    await planner.modifyTask(task.id, { title })
    onChange()
  }
  const [editing, setEditing] = useState(false)
  const overdueToday = task.due && new Date(task.due) <= new Date()
  return (
    <div
      draggable={!editing}
      onDragStart={(e) => {
        e.dataTransfer.setData('text/plain', task.id)
        e.dataTransfer.effectAllowed = 'move'
      }}
      className="flex items-start gap-3 p-3 rounded bg-surface-container-low/50 border border-border-subtle hover:border-[color:var(--accent)] transition-colors group cursor-grab active:cursor-grabbing"
      style={{ ['--accent' as string]: `${accent}80` }}>
      <button onClick={complete}
        className="mt-0.5 w-4 h-4 rounded-sm border border-border-default flex-shrink-0 hover:bg-[color:var(--accent)] transition-colors"
        aria-label="Complete task" />
      <div className="flex-1 min-w-0">
        <InlineEdit value={task.title} onSave={rename} editing={editing} onEditingChange={setEditing}
          textClassName="font-body-lg text-body-md text-on-surface leading-tight"
          inputClassName="w-full bg-surface-container-low border border-rune-entity/60 rounded px-1.5 py-0.5 text-on-surface font-body-md text-body-md focus:outline-none" />
        <div className="flex items-center gap-3 mt-1 flex-wrap">
          {task.area_name && (
            <span className="font-label-md text-[9px] uppercase px-1.5 py-0.5 rounded border"
              style={{ color: task.area_color ?? accent, borderColor: `${task.area_color ?? accent}4d`, background: `${task.area_color ?? accent}0d` }}>
              {task.area_name}
            </span>
          )}
          {task.goal_title && (
            <span className="font-label-md text-[9px] uppercase text-text-tertiary flex items-center gap-0.5">
              <span className="material-symbols-outlined text-[11px]">flag</span>{task.goal_title}
            </span>
          )}
          {questLine && (
            <Link to={`/project/${encodeURIComponent(questLine)}`} onClick={(e) => e.stopPropagation()}
              className="font-label-md text-[9px] uppercase text-rune-quest hover:underline flex items-center gap-0.5">
              <span className="material-symbols-outlined text-[11px]">account_tree</span>{questLine}
            </Link>
          )}
          {task.estimate_minutes ? (
            <span className="font-label-md text-[10px] text-text-tertiary flex items-center gap-1">
              <span className="material-symbols-outlined text-[12px]">schedule</span>{task.estimate_minutes}m
            </span>
          ) : null}
          {overdueToday && (
            <span className="font-label-md text-[10px] text-status-error flex items-center gap-1">
              <span className="material-symbols-outlined text-[12px]">warning</span>DUE
            </span>
          )}
        </div>
      </div>
      <button onClick={remove}
        className="material-symbols-outlined text-[16px] text-text-tertiary opacity-0 group-hover:opacity-100 hover:text-status-error transition-all self-start"
        aria-label="Delete task">delete</button>
    </div>
  )
}

// ---- quadrant panel ----------------------------------------------------------

function QuadrantPanel({ q, tasks, onChange, onAdd, onMove, projectMap }: { q: Quadrant; tasks: Task[]; onChange: () => void; onAdd: () => void; onMove: (taskId: string, q: Quadrant) => void; projectMap: Record<string, string> }) {
  const meta = QUADRANT[q]
  const [over, setOver] = useState(false)
  return (
    <div
      onDragOver={(e) => { e.preventDefault(); e.dataTransfer.dropEffect = 'move'; if (!over) setOver(true) }}
      onDragLeave={(e) => { if (!e.currentTarget.contains(e.relatedTarget as Node)) setOver(false) }}
      onDrop={(e) => {
        e.preventDefault(); setOver(false)
        const id = e.dataTransfer.getData('text/plain')
        if (id) onMove(id, q)
      }}
      className="grimoire-card border-none rounded-none p-5 flex flex-col gap-3 relative min-h-[260px] transition-shadow"
      style={{ boxShadow: over ? `inset 0 0 0 2px ${meta.color}, 0 0 28px ${meta.glow}` : `0 0 20px ${meta.glow}` }}>
      <div className="absolute top-0 left-0 w-1 h-full" style={{ background: meta.color }} />
      {over && (
        <div className="absolute inset-0 z-0 flex items-center justify-center pointer-events-none" style={{ background: `${meta.color}0f` }}>
          <span className="font-headline-md text-headline-md" style={{ color: meta.color }}>Drop into {meta.label}</span>
        </div>
      )}
      <div className="flex justify-between items-start relative z-10">
        <h3 className="font-headline-md text-headline-md flex items-center gap-2" style={{ color: meta.color }}>
          <span className="material-symbols-outlined text-[20px]">{meta.icon}</span>{meta.label}
        </h3>
        <div className="flex items-center gap-2">
          <button onClick={onAdd} className="material-symbols-outlined text-[18px] text-text-tertiary hover:text-on-surface transition-colors" aria-label="Add task">add</button>
          <span className="font-label-md text-label-md text-text-tertiary bg-surface-container-high px-2 py-1 rounded">{q}</span>
        </div>
      </div>
      <div className="flex flex-col gap-2 overflow-y-auto relative z-10">
        {tasks.length === 0 ? (
          <div className="flex-1 flex flex-col items-center justify-center text-center py-8">
            <span className="material-symbols-outlined text-[28px] text-border-default mb-1">inbox</span>
            <p className="font-body-md text-body-sm text-text-tertiary">{q === 'Q4' ? 'The void is empty. Keep it that way.' : 'Nothing here.'}</p>
          </div>
        ) : tasks.map((t) => <TaskChip key={t.id} task={t} accent={meta.color} onChange={onChange}
            questLine={t.project_id ? projectMap[t.project_id] : undefined} />)}
      </div>
    </div>
  )
}

// ---- goals rail --------------------------------------------------------------

function GoalRow({ group, onChange }: { group: AreaGroup; onChange: () => void }) {
  async function removeGoal(id: string, title: string) {
    if (!confirm(`Delete goal "${title}"? Its tasks stay but are unlinked.`)) return
    await planner.deleteGoal(id)
    onChange()
  }
  async function renameGoal(id: string, title: string) {
    await planner.modifyGoal(id, { title })
    onChange()
  }
  return (
    <>
      {group.goals.map((g) => {
        const total = (g.open_tasks ?? 0) + (g.done_tasks ?? 0)
        const pct = total > 0 ? Math.round(100 * (g.done_tasks ?? 0) / total) : 0
        const color = g.area_color ?? group.color ?? '#d4a93f'
        return (
          <div key={g.id} className="grimoire-card px-5 py-3 rounded-lg flex items-center gap-4 group">
            <span className="w-2 h-2 rounded-full flex-shrink-0" style={{ background: color, boxShadow: `0 0 8px ${color}99` }} />
            <div className="flex-1 min-w-0">
              <div className="flex justify-between items-baseline mb-1.5 gap-3">
                <InlineEdit value={g.title} onSave={(t) => renameGoal(g.id, t)}
                  textClassName="font-body-md text-body-md text-on-surface" />
                <span className="font-label-md text-[10px] text-text-tertiary uppercase shrink-0">
                  {g.target_date ? new Date(g.target_date).toLocaleDateString(undefined, { month: 'short', day: 'numeric' }) : 'no date'}
                </span>
              </div>
              <div className="w-full h-1 bg-surface-container-highest rounded-full overflow-hidden">
                <div className="h-full rounded-full" style={{ width: `${pct}%`, background: color }} />
              </div>
            </div>
            <button onClick={() => removeGoal(g.id, g.title)}
              className="material-symbols-outlined text-[16px] text-text-tertiary opacity-0 group-hover:opacity-100 hover:text-status-error transition-all"
              aria-label="Delete goal">delete</button>
          </div>
        )
      })}
    </>
  )
}

// ---- the tab -----------------------------------------------------------------

export default function Today() {
  const [data, setData] = useState<TodayData | null>(null)
  const [projectMap, setProjectMap] = useState<Record<string, string>>({})
  const [error, setError] = useState<string | null>(null)
  const [dialog, setDialog] = useState<{ kind: 'task' | 'habit' | 'goal'; q?: Quadrant } | null>(null)
  const date = localDate()

  const load = useCallback(() => {
    planner.today(date).then(setData).catch((e) => setError(String(e)))
  }, [date])
  useEffect(load, [load])

  // Map project node ids -> titles so task chips can show a clickable quest-line tag.
  useEffect(() => {
    api.graph().then((g) => {
      const m: Record<string, string> = {}
      for (const n of g.nodes) if (n.type === 'project') m[n.id] = n.title
      setProjectMap(m)
    }).catch(() => {})
  }, [])

  // Drag a task into a quadrant -> write that quadrant's important/urgent flags.
  const moveTask = useCallback((taskId: string, q: Quadrant) => {
    const all = data ? Object.values(data.quadrants).flat() : []
    const t = all.find((x) => x.id === taskId)
    if (t && t.quadrant === q) return // dropped where it already was
    const f = Q_FLAGS[q]
    // optimistic: move it locally so the chip jumps immediately, then persist
    if (data && t) {
      const next: Record<Quadrant, Task[]> = { Q1: [], Q2: [], Q3: [], Q4: [] }
      for (const qq of QUADRANT_ORDER) next[qq] = data.quadrants[qq].filter((x) => x.id !== taskId)
      next[q] = [{ ...t, quadrant: q, important: f.important ? 1 : 0, urgent_manual: f.urgent ? 1 : 0 }, ...next[q]]
      setData({ ...data, quadrants: next })
    }
    planner.modifyTask(taskId, { important: f.important, urgent_manual: f.urgent }).then(load).catch(() => load())
  }, [data, load])

  if (error) return (
    <div className="min-h-screen flex items-center justify-center text-center px-6">
      <div>
        <p className="font-headline-sm text-headline-sm text-status-error">Could not reach the planner</p>
        <p className="font-body-sm text-body-sm text-text-tertiary mt-2">{error}. Is the API running on :8731?</p>
      </div>
    </div>
  )
  if (!data) return <div className="min-h-screen flex items-center justify-center"><p className="font-headline-md text-headline-md text-text-tertiary animate-pulse">Consulting the grimoire...</p></div>

  const goalDefaults: Record<Quadrant, { important: boolean; urgent: boolean }> = {
    Q1: { important: true, urgent: true }, Q2: { important: true, urgent: false },
    Q3: { important: false, urgent: true }, Q4: { important: false, urgent: false },
  }
  const allGoals = data.goals.flatMap((g) => g.goals)

  return (
    <main className="min-h-screen pb-40 flex flex-col items-center overflow-y-auto">
      <div className="w-full max-w-[1200px] px-6 md:px-margin">
        {/* header */}
        <header className="py-lg mt-4 md:mt-8 flex justify-between items-start">
          <div>
            <h1 className="font-display-lg text-display-lg text-rune-quest tracking-widest mb-1">Today</h1>
            <p className="font-label-md text-label-md text-text-muted uppercase tracking-[0.2em]">{fmtDateline()}</p>
          </div>
          <div className="relative w-12 h-12 flex items-center justify-center text-primary opacity-80">
            <span className="material-symbols-outlined text-[32px] sigil-spin">astrophotography_mode</span>
            <div className="absolute inset-0 bg-primary/20 blur-xl rounded-full" />
          </div>
        </header>

        <div className="flex flex-col gap-xl">
          {/* habits strip */}
          <section className="flex flex-col gap-3">
            <div className="flex justify-between items-center px-1">
              <h3 className="font-label-md text-label-md text-text-muted tracking-widest uppercase">Rituals &amp; goals</h3>
              <div className="flex items-center gap-3">
                <span className="font-label-md text-label-md text-rune-quest/80">THIS WEEK · {data.weekly.overall_percent}%</span>
                <button onClick={() => setDialog({ kind: 'habit' })} className="material-symbols-outlined text-[18px] text-text-tertiary hover:text-on-surface" aria-label="Add ritual">add</button>
              </div>
            </div>
            <div className="flex gap-3 overflow-x-auto pb-2 pt-1 snap-x">
              {data.habits.length === 0 && <p className="font-body-md text-body-sm text-text-tertiary py-2">No rituals yet. Add one to begin a streak.</p>}
              {data.habits.map((h) => <HabitPill key={h.id} habit={h} date={date} onToggle={load} />)}
            </div>
          </section>

          {/* eisenhower matrix */}
          <section className="grid grid-cols-1 md:grid-cols-2 gap-px bg-border-subtle rounded-xl overflow-hidden border border-border-subtle">
            {QUADRANT_ORDER.map((q) => (
              <QuadrantPanel key={q} q={q} tasks={data.quadrants[q] ?? []} onChange={load}
                onAdd={() => setDialog({ kind: 'task', q })} onMove={moveTask} projectMap={projectMap} />
            ))}
          </section>

          {/* focus estimate + drag hint */}
          <p className="font-body-md text-body-sm text-text-muted px-1 -mt-2">
            {data.estimate.label}
            <span className="text-text-tertiary"> · drag a task between quadrants to re-prioritize</span>
          </p>

          {/* goals rail */}
          <section className="flex flex-col gap-3">
            <div className="flex justify-between items-center px-1">
              <h3 className="font-label-md text-label-md text-text-muted tracking-widest uppercase">Active vectors</h3>
              <button onClick={() => setDialog({ kind: 'goal' })} className="material-symbols-outlined text-[18px] text-text-tertiary hover:text-on-surface" aria-label="Add goal">add</button>
            </div>
            <div className="flex flex-col gap-2">
              {allGoals.length === 0 && <p className="font-body-md text-body-sm text-text-tertiary">No goals yet. Set a vector to give the day direction.</p>}
              {data.goals.map((group) => <GoalRow key={group.id ?? 'unsorted'} group={group} onChange={load} />)}
            </div>
          </section>
        </div>
      </div>

      <PlannerChat context={{ date }} onActed={load} />

      {dialog && (
        <AddItemDialog kind={dialog.kind} defaultQuadrant={dialog.q ? goalDefaults[dialog.q] : undefined}
          onClose={() => setDialog(null)} onCreated={load} />
      )}
    </main>
  )
}
