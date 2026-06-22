import { useEffect, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import ReactMarkdown from 'react-markdown'
import { api, type Document } from '../api'

export default function TomeReader() {
  const { id = '' } = useParams()
  const [doc, setDoc] = useState<Document | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    setDoc(null)
    setError(null)
    api.document(id).then(setDoc).catch((e) => setError(String(e)))
  }, [id])

  return (
    <div className="min-h-screen overflow-y-auto px-margin py-lg">
      <Link to="/" className="font-label-md text-label-md text-text-muted hover:text-primary uppercase tracking-widest inline-flex items-center gap-1">
        <span className="material-symbols-outlined text-[16px]">arrow_back</span> Constellation
      </Link>

      {error && <p className="font-body-sm text-body-sm text-status-error mt-8">{error}</p>}
      {!doc && !error && <p className="font-headline-md text-headline-md text-text-tertiary animate-pulse mt-8">Unsealing the tome...</p>}

      {doc && (
        <article className="mt-6 mx-auto max-w-[800px]">
          <header className="mb-lg flex items-center gap-3 border-b border-border-subtle pb-6">
            <span className="material-symbols-outlined text-rune-tome text-[32px]" style={{ filter: 'drop-shadow(0 0 8px #5b8dd9)' }}>menu_book</span>
            <div>
              <span className="font-label-md text-label-md text-rune-tome uppercase tracking-widest">Tome</span>
              <h1 className="font-headline-lg text-headline-lg text-primary leading-none">{doc.title}</h1>
            </div>
          </header>
          {/* Content stays clean and plainly readable: Spectral, not stylised into illegibility */}
          <div className="tome-content bg-bg-panel border border-border-default rounded-lg border-t-2 border-t-rune-tome p-8">
            <ReactMarkdown>{doc.content}</ReactMarkdown>
          </div>
        </article>
      )}
    </div>
  )
}
