<script lang="ts">
  import { fade, fly } from 'svelte/transition'
  import { quintOut } from 'svelte/easing'
  import { api, type NewNode } from '../lib/api'
  import { RUNE } from '../lib/theme'
  import { appState, closeScribe, refreshGraph } from '../lib/appstate.svelte'
  import { dur } from '../lib/motion.svelte'

  type Creatable = NewNode['type'] // 'project' | 'document' | 'entity'

  const TYPES: { value: Creatable; label: string }[] = [
    { value: 'project', label: RUNE.project.label }, // Quest line
    { value: 'document', label: RUNE.document.label }, // Tome
    { value: 'entity', label: RUNE.entity.label }, // Rune
  ]

  let type = $state<Creatable>('project')
  let title = $state('')
  let context = $state('')
  let project = $state('')
  let busy = $state(false)
  let error = $state<string | null>(null)

  function reset() {
    title = ''
    context = ''
    project = ''
    type = 'project'
    error = null
  }
  function close() {
    reset()
    closeScribe()
  }

  async function submit(e: Event) {
    e.preventDefault()
    if (!title.trim()) return
    busy = true
    error = null
    try {
      const payload: NewNode = { type, title: title.trim() }
      if (context.trim()) payload.context = context.trim()
      if (type !== 'project' && project.trim()) payload.project = project.trim()
      await api.createNode(payload)
      refreshGraph()
      close()
    } catch (err) {
      error = String(err)
    } finally {
      busy = false
    }
  }
</script>

{#if appState.scribeOpen}
  <!-- svelte-ignore a11y_no_static_element_interactions -->
  <div
    class="fixed inset-0 z-[60] flex items-center justify-center bg-black/70 backdrop-blur-sm px-4"
    role="presentation"
    transition:fade={{ duration: dur(160) }}
    onclick={(e) => e.target === e.currentTarget && close()}
    onkeydown={(e) => e.key === 'Escape' && close()}
  >
    <form
      transition:fly={{ y: 16, duration: dur(240), easing: quintOut }}
      onsubmit={submit}
      class="w-full max-w-md bg-bg-panel border border-border-default rounded-xl border-t-2 border-t-primary-container shadow-[0_0_40px_rgba(0,0,0,0.8)]"
    >
      <div class="px-6 py-4 border-b border-border-subtle flex items-center justify-between">
        <h2 class="font-headline-sm text-headline-sm text-primary flex items-center gap-2">
          <span class="material-symbols-outlined">add</span> Scribe a new node
        </h2>
        <button type="button" onclick={close} class="text-text-muted hover:text-on-surface" aria-label="Close">
          <span class="material-symbols-outlined text-[20px]">close</span>
        </button>
      </div>

      <div class="px-6 py-5 space-y-5">
        <!-- type selector -->
        <div>
          <span class="font-label-md text-label-md text-text-muted uppercase tracking-widest">Node type</span>
          <div class="mt-2 grid grid-cols-3 gap-2">
            {#each TYPES as t (t.value)}
              {@const rune = RUNE[t.value]}
              {@const active = type === t.value}
              <button
                type="button"
                onclick={() => (type = t.value)}
                class="flex flex-col items-center gap-1 py-3 rounded-lg border transition-all duration-200"
                style="border-color:{active ? rune.color : '#29263f'}; background-color:{active ? `${rune.color}1a` : 'transparent'}; box-shadow:{active ? `0 0 12px ${rune.color}55` : 'none'}"
              >
                <span class="material-symbols-outlined" style="color:{rune.color}">{rune.icon}</span>
                <span class="font-label-md text-label-md" style="color:{active ? rune.color : '#9b96b8'}">{t.label}</span>
              </button>
            {/each}
          </div>
        </div>

        <!-- title -->
        <div>
          <label class="font-label-md text-label-md text-text-muted uppercase tracking-widest" for="scribe-title">Title</label>
          <!-- svelte-ignore a11y_autofocus -->
          <input
            id="scribe-title"
            autofocus
            bind:value={title}
            placeholder="A name for this node"
            class="mt-1 w-full bg-transparent border-0 border-b border-border-default focus:border-rune-quest outline-none py-2 font-body-md text-body-md text-on-surface placeholder:text-text-tertiary transition-colors"
          />
        </div>

        <!-- context -->
        <div>
          <label class="font-label-md text-label-md text-text-muted uppercase tracking-widest" for="scribe-context">
            {type === 'project' ? 'Context summary' : 'Notes (optional)'}
          </label>
          <textarea
            id="scribe-context"
            bind:value={context}
            rows="3"
            placeholder={type === 'project' ? 'What is this quest line about?' : 'Optional body or notes'}
            class="mt-1 w-full bg-surface-container-low border border-border-default rounded focus:border-rune-quest outline-none p-3 font-body-sm text-body-sm text-on-surface placeholder:text-text-tertiary transition-colors resize-none"
          ></textarea>
        </div>

        <!-- link to quest line (rune/tome only) -->
        {#if type !== 'project'}
          <div>
            <label class="font-label-md text-label-md text-text-muted uppercase tracking-widest" for="scribe-project">Link to quest line (optional)</label>
            <input
              id="scribe-project"
              bind:value={project}
              placeholder="Existing project name"
              class="mt-1 w-full bg-transparent border-0 border-b border-border-default focus:border-rune-quest outline-none py-2 font-body-md text-body-md text-on-surface placeholder:text-text-tertiary transition-colors"
            />
          </div>
        {/if}

        {#if error}
          <p class="font-body-sm text-body-sm text-status-error">{error}</p>
        {/if}
      </div>

      <div class="px-6 py-4 border-t border-border-subtle flex justify-end gap-3">
        <button type="button" onclick={close} class="py-2 px-4 font-label-md text-label-md text-text-muted hover:text-on-surface uppercase tracking-wider">
          Cancel
        </button>
        <button
          type="submit"
          disabled={busy || !title.trim()}
          class="py-2 px-4 bg-surface text-primary-container border border-primary-container rounded hover:bg-bg-surface hover:shadow-[0_0_15px_0px_rgba(212,169,63,0.3)] transition-all duration-300 font-label-md text-label-md uppercase tracking-wider disabled:opacity-40"
        >
          {busy ? 'Inscribing...' : 'Inscribe'}
        </button>
      </div>
    </form>
  </div>
{/if}
