import { useState } from 'react'
import { Link } from 'react-router-dom'
import { api } from '../api'
import { useAppState } from '../state'

interface Job {
  key: string
  title: string
  icon: string
  blurb: string
  run: () => Promise<string>
}

const JOBS: Job[] = [
  {
    key: 'compact',
    title: 'Compaction job',
    icon: 'compress',
    blurb: 'Merge overlapping old memories into consolidated chronicles and refresh each project’s living context. Uses the LLM chain (Groq, falling back to Ollama).',
    run: async () => {
      const r = await api.compact()
      const total = r.compacted.reduce((n, c) => n + c.clusters_merged, 0)
      return `Compacted ${r.compacted.length} project(s), merged ${total} cluster(s).`
    },
  },
  {
    key: 'reembed',
    title: 'Re-embedding routine',
    icon: 'autorenew',
    blurb: 'Walk every chunk and re-embed it through the provider. The maintenance path for changing embedding models.',
    run: async () => {
      const r = await api.reembed()
      return `Re-embedded ${r.reembedded} chunk(s).`
    },
  },
]

export default function Settings() {
  const { refreshGraph } = useAppState()
  const [running, setRunning] = useState<string | null>(null)
  const [results, setResults] = useState<Record<string, string>>({})

  async function trigger(job: Job) {
    setRunning(job.key)
    setResults((r) => ({ ...r, [job.key]: '' }))
    try {
      const msg = await job.run()
      setResults((r) => ({ ...r, [job.key]: msg }))
      refreshGraph()
    } catch (e) {
      setResults((r) => ({ ...r, [job.key]: `failed: ${e}` }))
    } finally {
      setRunning(null)
    }
  }

  return (
    <div className="min-h-screen overflow-y-auto px-margin py-lg max-w-3xl">
      <Link to="/" className="font-label-md text-label-md text-text-muted hover:text-primary uppercase tracking-widest inline-flex items-center gap-1">
        <span className="material-symbols-outlined text-[16px]">arrow_back</span> Constellation
      </Link>

      <header className="mt-6 mb-lg flex items-center gap-3 border-b border-border-subtle pb-6">
        <span className="material-symbols-outlined text-primary-container text-[32px]" style={{ filter: 'drop-shadow(0 0 8px #e3d3a0)' }}>settings</span>
        <div>
          <span className="font-label-md text-label-md text-primary-container uppercase tracking-widest">Settings</span>
          <h1 className="font-headline-lg text-headline-lg text-primary leading-none">Maintenance rites</h1>
        </div>
      </header>

      <div className="space-y-md">
        {JOBS.map((job) => (
          <section key={job.key} className="bg-bg-panel border border-border-default rounded-lg p-5 flex items-start gap-4">
            <span className="material-symbols-outlined text-rune-quest text-[24px] mt-1">{job.icon}</span>
            <div className="flex-1 min-w-0">
              <h2 className="font-headline-sm text-headline-sm text-primary">{job.title}</h2>
              <p className="font-body-sm text-body-sm text-text-muted mt-1">{job.blurb}</p>
              {results[job.key] && (
                <p className="font-body-sm text-body-sm text-rune-quest mt-2">{results[job.key]}</p>
              )}
            </div>
            <button
              onClick={() => trigger(job)}
              disabled={running !== null}
              className="shrink-0 py-2 px-4 bg-surface text-primary-container border border-primary-container rounded hover:bg-bg-surface hover:shadow-[0_0_15px_0px_rgba(227,211,160,0.3)] transition-all duration-300 font-label-md text-label-md uppercase tracking-wider disabled:opacity-40"
            >
              {running === job.key ? 'Running...' : 'Run'}
            </button>
          </section>
        ))}
      </div>
    </div>
  )
}
