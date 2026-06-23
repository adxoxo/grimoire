import { useEffect, useRef, useState } from 'react'

interface Props {
  value: string
  onSave: (next: string) => void
  textClassName?: string
  inputClassName?: string
  showPencil?: boolean
  // Controlled editing flag (lets a draggable parent turn off drag while typing).
  editing?: boolean
  onEditingChange?: (editing: boolean) => void
}

// Double-click the text (or click the pencil) to rename in place. Enter/blur saves,
// Esc cancels. Used for task/goal/habit names in Today and block titles in Flow.
export default function InlineEdit({
  value, onSave, textClassName = '', inputClassName = '', showPencil = true,
  editing: editingProp, onEditingChange,
}: Props) {
  const [editingState, setEditingState] = useState(false)
  const editing = editingProp ?? editingState
  const setEditing = (v: boolean) => { setEditingState(v); onEditingChange?.(v) }
  const [draft, setDraft] = useState(value)
  const ref = useRef<HTMLInputElement>(null)

  useEffect(() => setDraft(value), [value])
  useEffect(() => { if (editing) ref.current?.select() }, [editing])

  function commit() {
    const next = draft.trim()
    if (next && next !== value) onSave(next)
    setEditing(false)
  }

  if (editing) {
    return (
      <input
        ref={ref}
        value={draft}
        onChange={(e) => setDraft(e.target.value)}
        onBlur={commit}
        onKeyDown={(e) => {
          if (e.key === 'Enter') commit()
          if (e.key === 'Escape') { setDraft(value); setEditing(false) }
        }}
        onMouseDown={(e) => e.stopPropagation()}
        onClick={(e) => e.stopPropagation()}
        draggable={false}
        className={inputClassName || 'bg-surface-container-low border border-rune-entity/60 rounded px-1.5 py-0.5 text-on-surface font-body-md text-body-md focus:outline-none'}
      />
    )
  }

  return (
    <span className="inline-flex items-center gap-1 group/edit min-w-0">
      <span className={`${textClassName} truncate`} onDoubleClick={(e) => { e.stopPropagation(); setEditing(true) }} title="double-click to rename">
        {value}
      </span>
      {showPencil && (
        <button
          onClick={(e) => { e.stopPropagation(); setEditing(true) }}
          onMouseDown={(e) => e.stopPropagation()}
          className="material-symbols-outlined text-[13px] text-text-tertiary opacity-0 group-hover/edit:opacity-100 hover:text-rune-entity transition-all shrink-0"
          aria-label="Rename"
        >edit</button>
      )}
    </span>
  )
}
