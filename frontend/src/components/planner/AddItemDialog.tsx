import { useEffect, useState } from 'react'
import { api, planner, type LifeArea, type Goal } from '../../api'

type Kind = 'task' | 'habit' | 'goal'

interface Props {
  kind: Kind
  defaultQuadrant?: { important: boolean; urgent: boolean }
  onClose: () => void
  onCreated: () => void
}

// Structured capture for when the user wants precise control (the + buttons). The chat
// bar handles the fast, sentence-driven path; this handles the deliberate one.
export default function AddItemDialog({ kind, defaultQuadrant, onClose, onCreated }: Props) {
  const [title, setTitle] = useState('')
  const [busy, setBusy] = useState(false)
  // task
  const [important, setImportant] = useState(defaultQuadrant?.important ?? false)
  const [urgent, setUrgent] = useState(defaultQuadrant?.urgent ?? false)
  const [estimate, setEstimate] = useState('')
  const [goalId, setGoalId] = useState('')
  const [goals, setGoals] = useState<Goal[]>([])
  // habit
  const [cadence, setCadence] = useState<'daily' | 'weekly'>('daily')
  const [weeklyTarget, setWeeklyTarget] = useState('3')
  const [duration, setDuration] = useState('')
  const [windowPref, setWindowPref] = useState('anytime')
  // goal
  const [why, setWhy] = useState('')
  const [area, setArea] = useState('')
  const [target, setTarget] = useState('')
  const [areas, setAreas] = useState<LifeArea[]>([])
  // quest line (project node) link, available for tasks and goals
  const [questLine, setQuestLine] = useState('')
  const [questLines, setQuestLines] = useState<{ id: string; title: string }[]>([])

  useEffect(() => {
    if (kind === 'task') planner.goals().then((r) => setGoals(r.goals)).catch(() => {})
    if (kind === 'goal') planner.areas().then((r) => { setAreas(r.areas); setArea(r.areas[0]?.name ?? '') }).catch(() => {})
    if (kind !== 'habit') {
      api.graph().then((g) => setQuestLines(g.nodes.filter((n) => n.type === 'project').map((n) => ({ id: n.id, title: n.title })))).catch(() => {})
    }
  }, [kind])

  async function submit() {
    if (!title.trim() || busy) return
    setBusy(true)
    try {
      if (kind === 'task') {
        await planner.createTask({
          title: title.trim(), important, urgent_manual: urgent ? true : undefined,
          estimate_minutes: estimate ? Number(estimate) : undefined, goal_id: goalId || undefined,
          project_id: questLine || undefined,
        })
      } else if (kind === 'habit') {
        await planner.createHabit({
          name: title.trim(), cadence_type: cadence,
          weekly_target: cadence === 'weekly' ? Number(weeklyTarget) : undefined,
          duration_minutes: duration ? Number(duration) : 0, window_preference: windowPref,
        })
      } else {
        await planner.createGoal({
          title: title.trim(), why: why.trim() || undefined, area: area || undefined,
          target_date: target ? new Date(target).toISOString() : undefined,
          project_id: questLine || undefined,
        })
      }
      onCreated()
      onClose()
    } catch (e) {
      alert(`could not create ${kind}: ${e}`)
    } finally {
      setBusy(false)
    }
  }

  const heads: Record<Kind, string> = { task: 'Scribe a task', habit: 'Inscribe a ritual', goal: 'Set a vector' }
  const field = 'w-full bg-surface-container-low border border-border-default rounded px-3 py-2 text-on-surface font-body-md text-body-md focus:outline-none focus:border-rune-entity/60'
  const lbl = 'font-label-md text-label-md text-text-muted uppercase tracking-widest mb-1 block'

  return (
    <div className="fixed inset-0 z-[60] flex items-center justify-center bg-bg-page/70 backdrop-blur-sm px-4" onClick={onClose}>
      <div className="w-full max-w-md bg-bg-panel border border-border-default rounded-xl p-6 shadow-[0_20px_60px_rgba(0,0,0,0.7)]" onClick={(e) => e.stopPropagation()}>
        <h3 className="font-headline-md text-headline-md text-primary mb-4">{heads[kind]}</h3>

        <div className="space-y-3">
          <div>
            <label className={lbl}>{kind === 'habit' ? 'Name' : 'Title'}</label>
            <input autoFocus value={title} onChange={(e) => setTitle(e.target.value)}
              onKeyDown={(e) => e.key === 'Enter' && kind === 'task' && submit()}
              className={field} placeholder={kind === 'habit' ? 'meditation' : kind === 'goal' ? 'Ship the beta' : 'Finish the i2c driver'} />
          </div>

          {kind === 'task' && (
            <>
              <div className="flex gap-3">
                <button onClick={() => setImportant((v) => !v)}
                  className={`flex-1 py-2 rounded border text-body-sm font-body-sm transition-colors ${important ? 'border-rune-quest text-rune-quest bg-rune-quest/10' : 'border-border-default text-text-muted'}`}>
                  Important
                </button>
                <button onClick={() => setUrgent((v) => !v)}
                  className={`flex-1 py-2 rounded border text-body-sm font-body-sm transition-colors ${urgent ? 'border-rune-chronicle text-rune-chronicle bg-rune-chronicle/10' : 'border-border-default text-text-muted'}`}>
                  Urgent (override)
                </button>
              </div>
              <div className="flex gap-3">
                <div className="flex-1">
                  <label className={lbl}>Estimate (min)</label>
                  <input value={estimate} onChange={(e) => setEstimate(e.target.value)} type="number" className={field} placeholder="60" />
                </div>
                <div className="flex-1">
                  <label className={lbl}>Goal</label>
                  <select value={goalId} onChange={(e) => setGoalId(e.target.value)} className={field}>
                    <option value="">— none —</option>
                    {goals.map((g) => <option key={g.id} value={g.id}>{g.title}</option>)}
                  </select>
                </div>
              </div>
            </>
          )}

          {kind === 'habit' && (
            <>
              <div className="flex gap-3">
                <select value={cadence} onChange={(e) => setCadence(e.target.value as 'daily' | 'weekly')} className={field}>
                  <option value="daily">Daily</option>
                  <option value="weekly">Weekly</option>
                </select>
                {cadence === 'weekly' && (
                  <input value={weeklyTarget} onChange={(e) => setWeeklyTarget(e.target.value)} type="number" className={field} placeholder="times / week" />
                )}
              </div>
              <div className="flex gap-3">
                <div className="flex-1">
                  <label className={lbl}>Duration (min)</label>
                  <input value={duration} onChange={(e) => setDuration(e.target.value)} type="number" className={field} placeholder="20" />
                </div>
                <div className="flex-1">
                  <label className={lbl}>Window</label>
                  <select value={windowPref} onChange={(e) => setWindowPref(e.target.value)} className={field}>
                    {['anytime', 'morning', 'midday', 'evening'].map((w) => <option key={w} value={w}>{w}</option>)}
                  </select>
                </div>
              </div>
            </>
          )}

          {kind === 'goal' && (
            <>
              <div>
                <label className={lbl}>Why (the spark filter)</label>
                <input value={why} onChange={(e) => setWhy(e.target.value)} className={field} placeholder="why this earns your time" />
              </div>
              <div className="flex gap-3">
                <div className="flex-1">
                  <label className={lbl}>Life area</label>
                  <select value={area} onChange={(e) => setArea(e.target.value)} className={field}>
                    {areas.map((a) => <option key={a.id} value={a.name}>{a.name}</option>)}
                  </select>
                </div>
                <div className="flex-1">
                  <label className={lbl}>Target date</label>
                  <input value={target} onChange={(e) => setTarget(e.target.value)} type="date" className={field} />
                </div>
              </div>
            </>
          )}

          {kind !== 'habit' && questLines.length > 0 && (
            <div>
              <label className={lbl}>Quest line</label>
              <select value={questLine} onChange={(e) => setQuestLine(e.target.value)} className={field}>
                <option value="">— none —</option>
                {questLines.map((p) => <option key={p.id} value={p.id}>{p.title}</option>)}
              </select>
            </div>
          )}
        </div>

        <div className="flex justify-end gap-3 mt-6">
          <button onClick={onClose} className="px-4 py-2 text-text-muted hover:text-on-surface font-label-md text-label-md uppercase tracking-wider">Cancel</button>
          <button onClick={submit} disabled={busy || !title.trim()}
            className="px-5 py-2 bg-surface text-primary-container border border-primary-container rounded hover:shadow-[0_0_15px_rgba(227,211,160,0.3)] transition-all font-label-md text-label-md uppercase tracking-wider disabled:opacity-40">
            {busy ? 'Scribing...' : 'Scribe'}
          </button>
        </div>
      </div>
    </div>
  )
}
