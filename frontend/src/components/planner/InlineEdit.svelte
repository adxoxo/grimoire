<script lang="ts">
  // Double-click the text (or click the pencil) to rename in place. Enter/blur saves,
  // Esc cancels. Used for task/goal/habit names in Today and block titles in Flow.
  let {
    value,
    onSave,
    textClassName = '',
    inputClassName = '',
    showPencil = true,
    editing: editingProp = undefined,
    onEditingChange,
  }: {
    value: string
    onSave: (next: string) => void
    textClassName?: string
    inputClassName?: string
    showPencil?: boolean
    editing?: boolean
    onEditingChange?: (editing: boolean) => void
  } = $props()

  let editingState = $state(false)
  const editing = $derived(editingProp ?? editingState)
  function setEditing(v: boolean) {
    editingState = v
    onEditingChange?.(v)
  }

  let draft = $state('')
  let inputEl = $state<HTMLInputElement>()

  // Keep the working copy synced to the incoming value (only changes after a save).
  $effect(() => {
    draft = value
  })
  $effect(() => {
    if (editing) inputEl?.select()
  })

  function commit() {
    const next = draft.trim()
    if (next && next !== value) onSave(next)
    setEditing(false)
  }
</script>

{#if editing}
  <input
    bind:this={inputEl}
    bind:value={draft}
    onblur={commit}
    onkeydown={(e) => {
      if (e.key === 'Enter') commit()
      if (e.key === 'Escape') {
        draft = value
        setEditing(false)
      }
    }}
    onmousedown={(e) => e.stopPropagation()}
    onclick={(e) => e.stopPropagation()}
    draggable="false"
    class={inputClassName || 'bg-surface-container-low border border-rune-entity/60 rounded px-1.5 py-0.5 text-on-surface font-body-md text-body-md focus:outline-none'}
  />
{:else}
  <span class="flex items-center gap-1 group/edit min-w-0">
    <span class="{textClassName} truncate" ondblclick={(e) => { e.stopPropagation(); setEditing(true) }} title="double-click to rename" role="textbox" tabindex="-1">
      {value}
    </span>
    {#if showPencil}
      <button
        onclick={(e) => { e.stopPropagation(); setEditing(true) }}
        onmousedown={(e) => e.stopPropagation()}
        class="material-symbols-outlined text-[13px] text-text-tertiary opacity-0 group-hover/edit:opacity-100 hover:text-rune-entity transition-all shrink-0"
        aria-label="Rename"
      >edit</button>
    {/if}
  </span>
{/if}
