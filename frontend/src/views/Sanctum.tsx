import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { api, type ReviewItem } from '../api'
import { RUNE } from '../theme'

export default function Sanctum() {
  const [items, setItems] = useState<ReviewItem[] | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState<string | null>(null)

  useEffect(() => {
    api.review().then((r) => setItems(r.items)).catch((e) => setError(String(e)))
  }, [])

  async function review(id: string) {
    setBusy(id)
    try {
      await api.markReviewed(id)
      setItems((cur) => (cur ? cur.filter((i) => i.id !== id) : cur))
    } finally {
      setBusy(null)
    }
  }

  return (
    <div className="min-h-screen overflow-y-auto px-margin py-lg max-w-3xl">
      <Link to="/" className="font-label-md text-label-md text-text-muted hover:text-primary uppercase tracking-widest inline-flex items-center gap-1">
        <span className="material-symbols-outlined text-[16px]">arrow_back</span> Constellation
      </Link>

      <header className="mt-6 mb-lg flex items-center gap-3 border-b border-border-subtle pb-6">
        <span className="material-symbols-outlined text-primary-container text-[32px]" style={{ filter: 'drop-shadow(0 0 8px #e3d3a0)' }}>fort</span>
        <div>
          <span className="font-label-md text-label-md text-primary-container uppercase tracking-widest">Review sanctum</span>
          <h1 className="font-headline-lg text-headline-lg text-primary leading-none">Unreviewed</h1>
        </div>
      </header>

      {error && <p className="font-body-sm text-body-sm text-status-error">{error}</p>}
      {!items && !error && <p className="font-headline-md text-headline-md text-text-tertiary animate-pulse">Gathering the unsanctioned...</p>}
      {items && items.length === 0 && (
        <p className="font-body-lg text-body-lg text-text-tertiary">The sanctum is clear. All knowledge has been sanctioned.</p>
      )}

      <ul className="space-y-3">
        {items?.map((item) => {
          const rune = RUNE[item.type]
          return (
            <li
              key={item.id}
              className="bg-bg-panel border border-border-default rounded-lg p-4 border-l-4 flex items-start justify-between gap-4"
              style={{ borderLeftColor: rune.color }}
            >
              <div className="min-w-0">
                <div className="flex items-center gap-2 mb-1">
                  <span
                    className="w-2 h-2 rounded-full svg-pulse"
                    style={{ backgroundColor: rune.color, boxShadow: `0 0 8px ${rune.color}` }}
                  />
                  <span className="font-label-md text-label-md uppercase tracking-wider" style={{ color: rune.color }}>{rune.label}</span>
                </div>
                <p className="font-body-md text-body-md text-on-surface truncate">{item.title}</p>
                {item.context_summary && (
                  <p className="font-body-sm text-body-sm text-text-muted mt-1 line-clamp-2">
                    {item.context_summary.slice(0, 160)}
                  </p>
                )}
              </div>
              <button
                onClick={() => review(item.id)}
                disabled={busy === item.id}
                className="shrink-0 py-1.5 px-3 bg-surface text-primary-container border border-primary-container rounded hover:bg-bg-surface hover:shadow-[0_0_15px_0px_rgba(227,211,160,0.3)] transition-all duration-300 font-label-md text-label-md uppercase tracking-wider disabled:opacity-50"
              >
                {busy === item.id ? '...' : 'Sanction'}
              </button>
            </li>
          )
        })}
      </ul>
    </div>
  )
}
