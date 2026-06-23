import { useEffect, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { api, planner, type LinkedNode, type Project, type Task } from '../api'
import { RUNE, QUADRANT, type NodeType } from '../theme'

function humanize(key: string): string {
  return key.replace(/_/g, ' ').replace(/^\w/, (c) => c.toUpperCase())
}

function LinkedCard({ node }: { node: LinkedNode }) {
  const rune = RUNE[node.type]
  const unreviewed = node.status === 'unreviewed'
  return (
    <div className="bg-bg-panel border border-border-default rounded-lg p-4 hover:border-border-default hover:-translate-y-0.5 transition-all duration-200 border-t-2" style={{ borderTopColor: rune.color }}>
      <div className="flex items-center gap-2 mb-2">
        <span className="material-symbols-outlined text-[18px]" style={{ color: rune.color }}>{rune.icon}</span>
        <span
          className={`w-1.5 h-1.5 rounded-full ${unreviewed ? 'svg-pulse' : ''}`}
          style={{ backgroundColor: rune.color, boxShadow: `0 0 6px ${rune.color}` }}
        />
      </div>
      <p className="font-body-md text-body-md text-on-surface leading-snug">{node.title}</p>
    </div>
  )
}

export default function ProjectHub() {
  const { name = '' } = useParams()
  const [project, setProject] = useState<Project | null>(null)
  const [tasks, setTasks] = useState<Task[]>([])
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    setProject(null)
    setError(null)
    setTasks([])
    api.project(name).then((p) => {
      setProject(p)
      planner.projectTasks(p.id).then((r) => setTasks(r.tasks)).catch(() => {})
    }).catch((e) => setError(String(e)))
  }, [name])

  function refreshTasks() {
    if (project) planner.projectTasks(project.id).then((r) => setTasks(r.tasks)).catch(() => {})
  }
  async function completeTask(id: string) {
    await planner.completeTask(id, true)
    refreshTasks()
  }
  async function deleteTask(id: string, title: string) {
    if (!confirm(`Delete "${title}"? This cannot be undone.`)) return
    await planner.deleteTask(id)
    refreshTasks()
  }

  if (error) {
    return (
      <div className="p-margin">
        <Link to="/" className="font-label-md text-label-md text-text-muted hover:text-primary uppercase tracking-widest">← Constellation</Link>
        <p className="font-headline-sm text-headline-sm text-status-error mt-8">Quest line not found</p>
        <p className="font-body-sm text-body-sm text-text-tertiary mt-2">{error}</p>
      </div>
    )
  }

  if (!project) {
    return <div className="p-margin font-headline-md text-headline-md text-text-tertiary animate-pulse">Unsealing the quest line...</div>
  }

  const linked = project.linked
  const groups: { type: NodeType; items: LinkedNode[] }[] = [
    { type: 'memory', items: linked.filter((n) => n.type === 'memory') },
    { type: 'document', items: linked.filter((n) => n.type === 'document') },
    { type: 'entity', items: linked.filter((n) => n.type === 'entity') },
  ]

  return (
    <div className="min-h-screen overflow-y-auto px-margin py-lg">
      <Link to="/" className="font-label-md text-label-md text-text-muted hover:text-primary uppercase tracking-widest inline-flex items-center gap-1">
        <span className="material-symbols-outlined text-[16px]">arrow_back</span> Constellation
      </Link>

      {/* Title */}
      <header className="mt-6 mb-lg flex items-center gap-3 border-b border-border-subtle pb-6">
        <span className="material-symbols-outlined text-rune-quest text-[32px]" style={{ filter: 'drop-shadow(0 0 8px #d4a93f)' }}>account_tree</span>
        <div>
          <span className="font-label-md text-label-md text-rune-quest uppercase tracking-widest">Active quest line</span>
          <h1 className="font-display-lg text-display-lg text-primary leading-none">{project.title}</h1>
        </div>
      </header>

      <div className="flex flex-col lg:flex-row gap-lg">
        {/* Main column */}
        <div className="flex-1 min-w-0 space-y-lg">
          {/* Living context summary — clean, plainly readable */}
          <section className="bg-bg-panel border border-border-default rounded-lg border-t-2 border-t-rune-quest overflow-hidden">
            <div className="px-6 py-4 border-b border-border-subtle flex items-center gap-2">
              <span className="material-symbols-outlined text-rune-quest text-[20px]">menu_book</span>
              <h2 className="font-headline-sm text-headline-sm text-primary">Living context summary</h2>
            </div>
            <div className="px-6 py-6 max-w-[800px]">
              <p className="font-body-lg text-body-lg text-on-surface-variant whitespace-pre-line">
                {project.context_summary || 'No context recorded yet.'}
              </p>
            </div>
          </section>

          {/* Open tasks (the graph payoff: tasks linked to this project node) */}
          <section>
            <h3 className="font-headline-sm text-headline-sm text-on-surface mb-3 flex items-center gap-2">
              <span className="material-symbols-outlined text-[18px] text-rune-quest">checklist</span>
              Open tasks
              {tasks.length > 0 && <span className="font-label-md text-label-md text-text-tertiary">({tasks.length})</span>}
            </h3>
            {tasks.length > 0 ? (
              <div className="space-y-2">
                {tasks.map((t) => {
                  const meta = t.quadrant ? QUADRANT[t.quadrant] : QUADRANT.Q4
                  return (
                    <div key={t.id} className="flex items-start gap-3 p-3 rounded bg-bg-panel border border-border-default group">
                      <button onClick={() => completeTask(t.id)} className="mt-0.5 w-4 h-4 rounded-sm border border-border-default flex-shrink-0 hover:bg-rune-quest/40 transition-colors" aria-label="Complete" />
                      <div className="flex-1 min-w-0">
                        <p className="font-body-md text-body-md text-on-surface leading-tight">{t.title}</p>
                        <div className="flex items-center gap-3 mt-1">
                          <span className="font-label-md text-[9px] uppercase px-1.5 py-0.5 rounded border" style={{ color: meta.color, borderColor: `${meta.color}4d` }}>{meta.label}</span>
                          {t.goal_title && <span className="font-label-md text-[9px] uppercase text-text-tertiary">→ {t.goal_title}</span>}
                          {t.estimate_minutes ? <span className="font-label-md text-[10px] text-text-tertiary">{t.estimate_minutes}m</span> : null}
                        </div>
                      </div>
                      <button onClick={() => deleteTask(t.id, t.title)} className="material-symbols-outlined text-[16px] text-text-tertiary opacity-0 group-hover:opacity-100 hover:text-status-error transition-all" aria-label="Delete task">delete</button>
                    </div>
                  )
                })}
              </div>
            ) : (
              <p className="font-body-sm text-body-sm text-text-tertiary italic">No open tasks linked. Capture one in Today and link it here.</p>
            )}
          </section>

          {/* Linked chronicles + tomes */}
          <div className="grid md:grid-cols-2 gap-md">
            {(['memory', 'document'] as NodeType[]).map((type) => {
              const items = groups.find((g) => g.type === type)!.items
              return (
                <section key={type}>
                  <h3 className="font-headline-sm text-headline-sm text-on-surface mb-3 flex items-center gap-2">
                    <span className="material-symbols-outlined text-[18px]" style={{ color: RUNE[type].color }}>{RUNE[type].icon}</span>
                    {type === 'memory' ? 'Recent chronicles' : 'Linked tomes'}
                  </h3>
                  <div className="space-y-3">
                    {items.length > 0 ? (
                      items.map((n) => <LinkedCard key={n.id} node={n} />)
                    ) : (
                      <p className="font-body-sm text-body-sm text-text-tertiary italic">None linked yet.</p>
                    )}
                  </div>
                </section>
              )
            })}
          </div>
        </div>

        {/* Metadata sidebar */}
        <aside className="lg:w-72 shrink-0 space-y-lg">
          <section className="bg-bg-panel border border-border-default rounded-lg p-5">
            <h3 className="font-label-md text-label-md text-text-muted uppercase tracking-widest mb-4">Quest metadata</h3>
            <dl className="space-y-3">
              <div className="flex items-center justify-between">
                <dt className="font-label-md text-label-md text-text-muted uppercase tracking-wider">Status</dt>
                <dd className="font-label-md text-label-md text-rune-quest flex items-center gap-2">
                  <span className="w-2 h-2 rounded-full bg-rune-quest" style={{ boxShadow: '0 0 8px #d4a93f' }} />
                  {project.status}
                </dd>
              </div>
              {Object.entries(project.meta).map(([k, v]) => (
                <div key={k} className="flex items-center justify-between gap-4">
                  <dt className="font-label-md text-label-md text-text-muted uppercase tracking-wider">{humanize(k)}</dt>
                  <dd className="font-body-sm text-body-sm text-on-surface text-right">{String(v)}</dd>
                </div>
              ))}
            </dl>
          </section>

          {/* Recent runes */}
          <section className="bg-bg-panel border border-border-default rounded-lg p-5">
            <h3 className="font-label-md text-label-md text-text-muted uppercase tracking-widest mb-4">Recent runes</h3>
            {groups.find((g) => g.type === 'entity')!.items.length > 0 ? (
              <ul className="space-y-2">
                {groups.find((g) => g.type === 'entity')!.items.map((n) => (
                  <li key={n.id} className="flex items-center gap-2 font-body-sm text-body-sm text-on-surface">
                    <span className="material-symbols-outlined text-[16px] text-rune-entity">token</span>
                    {n.title}
                  </li>
                ))}
              </ul>
            ) : (
              <p className="font-body-sm text-body-sm text-text-tertiary italic">Runes surface through linked chronicles.</p>
            )}
          </section>
        </aside>
      </div>
    </div>
  )
}
