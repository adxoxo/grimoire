<script lang="ts">
  import { api } from '../lib/api'
  import { RUNE, type NodeType } from '../lib/theme'
  import { appState, closeCapture, openScribe, refreshGraph } from '../lib/appstate.svelte'
  import { fly, fade } from 'svelte/transition'
  import { dur } from '../lib/motion.svelte'

  type Result = { id: string; type: NodeType; title: string; project?: string } | { error: string }

  const ACCEPT = '.pdf,.epub,.fb2,.xps,.mobi,.cbz,.html,.htm,.md,.markdown,.txt'

  // Quick capture, dialog form: describe a thought and the LLM scribes it into the
  // right node (memory / entity / document / quest line), or attach PDFs and books.
  let value = $state('')
  let busy = $state(false)
  let status = $state<string | null>(null)
  let last = $state<Result | null>(null)
  let fileInput = $state<HTMLInputElement>()
  let textarea = $state<HTMLTextAreaElement>()

  $effect(() => {
    if (appState.captureOpen) textarea?.focus()
  })

  async function send() {
    const message = value.trim()
    if (!message || busy) return
    busy = true
    value = ''
    status = null
    try {
      last = await api.scribe(message)
      refreshGraph()
    } catch (e) {
      last = { error: String(e) }
    } finally {
      busy = false
    }
  }

  async function onFiles(fileList: FileList | null) {
    const files = fileList ? Array.from(fileList) : []
    if (!files.length || busy) return
    const project = value.trim() || undefined // the text doubles as the target quest line
    busy = true
    status = `ingesting ${files.length} file${files.length > 1 ? 's' : ''}... (large books take a moment)`
    last = null
    try {
      const r = await api.ingest(files, project)
      const ok = r.ingested.filter((x) => !x.error)
      const failed = r.ingested.filter((x) => x.error)
      if (ok.length) {
        const projects = [...new Set(ok.map((x) => x.project).filter(Boolean))]
        last = {
          id: '',
          type: 'document',
          title: ok.length === 1 ? ok[0].title || ok[0].filename : `${ok.length} documents`,
          project: ok.length === 1 ? ok[0].project : projects.join(', '),
        }
      }
      if (failed.length) {
        last = { error: `${failed.length} failed: ${failed.map((f) => f.filename).join(', ')}` }
      }
      value = ''
      refreshGraph()
    } catch (e) {
      last = { error: String(e) }
    } finally {
      busy = false
      status = null
      if (fileInput) fileInput.value = ''
    }
  }

  function onKeydown(e: KeyboardEvent) {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      send()
    }
  }

  function manualScribe() {
    closeCapture()
    openScribe()
  }

  const ok = $derived(last && !('error' in last) ? (last as { id: string; type: NodeType; title: string; project?: string }) : null)
  const err = $derived(last && 'error' in last ? last.error : null)
</script>

<svelte:window onkeydown={(e) => e.key === 'Escape' && appState.captureOpen && closeCapture()} />

{#if appState.captureOpen}
  <div
    transition:fade={{ duration: dur(150) }}
    class="fixed inset-0 z-[60] bg-black/60 backdrop-blur-sm flex items-start justify-center pt-[12vh] px-4"
    onclick={(e) => e.target === e.currentTarget && closeCapture()}
    role="presentation"
  >
    <div
      transition:fly={{ y: 14, duration: dur(200) }}
      role="dialog"
      aria-modal="true"
      aria-label="Scribe"
      class="w-full max-w-lg bg-bg-panel border border-border-default rounded-xl shadow-[0_20px_60px_rgba(0,0,0,0.7)]"
    >
      <div class="flex items-center justify-between px-5 pt-4 pb-3 border-b border-border-subtle">
        <h2 class="font-headline-sm text-headline-sm text-primary flex items-center gap-2">
          <span class="material-symbols-outlined text-rune-quest text-[20px]">edit_note</span>
          Scribe
        </h2>
        <button
          onclick={closeCapture}
          aria-label="Close"
          class="w-8 h-8 rounded-full flex items-center justify-center text-text-muted hover:text-on-surface hover:bg-bg-surface transition-colors"
        >
          <span class="material-symbols-outlined text-[20px]">close</span>
        </button>
      </div>

      <div class="p-5">
        <textarea
          bind:this={textarea}
          bind:value
          onkeydown={onKeydown}
          disabled={busy}
          rows="3"
          placeholder="Describe a thought... the scribe files it under the right quest line"
          class="w-full resize-none bg-bg-page border border-border-default rounded-lg px-3 py-2.5 font-body-md text-body-md text-on-surface placeholder:text-text-tertiary outline-none focus:border-rune-quest transition-colors"
        ></textarea>

        <div class="flex items-center justify-between mt-3">
          <input bind:this={fileInput} type="file" accept={ACCEPT} multiple class="hidden" onchange={(e) => onFiles((e.currentTarget as HTMLInputElement).files)} />
          <button
            onclick={() => fileInput?.click()}
            disabled={busy}
            class="flex items-center gap-2 px-3 py-2 rounded-full border border-border-default text-text-muted hover:text-rune-quest hover:border-rune-quest/50 transition-colors font-label-md text-label-md disabled:opacity-40"
          >
            <span class="material-symbols-outlined text-[18px]">attach_file</span>
            Attach a PDF or book
          </button>
          <button
            onclick={send}
            disabled={busy || !value.trim()}
            class="flex items-center gap-2 px-4 py-2 rounded-full bg-rune-quest/20 text-rune-quest hover:bg-rune-quest hover:text-bg-page transition-colors font-label-md text-label-md disabled:opacity-40"
          >
            <span class="material-symbols-outlined text-[18px]">{busy ? 'hourglass_top' : 'north'}</span>
            Scribe it
          </button>
        </div>
        <p class="font-body-sm text-body-sm text-text-tertiary mt-2">
          Attachments file under the quest line named in the text, or the closest match.
        </p>

        {#if ok || err || status}
          <div class="mt-3 bg-bg-page border border-border-subtle rounded-lg px-4 py-2.5">
            {#if status}
              <p class="font-body-sm text-body-sm text-text-muted animate-pulse">{status}</p>
            {:else if ok}
              <p class="font-body-sm text-body-sm text-on-surface flex items-center gap-2">
                <span class="material-symbols-outlined text-[16px]" style="color:{RUNE[ok.type].color}">{RUNE[ok.type].icon}</span>
                inscribed {RUNE[ok.type].label.toLowerCase()} <span class="text-on-surface-variant">"{ok.title}"</span>
                {#if ok.project}<span class="text-text-tertiary">under {ok.project}</span>{/if}
              </p>
            {:else}
              <p class="font-body-sm text-body-sm text-status-error">{err}</p>
            {/if}
          </div>
        {/if}
      </div>

      <div class="px-5 py-3 border-t border-border-subtle">
        <button
          onclick={manualScribe}
          class="w-full flex items-center justify-center gap-2 py-2 rounded-lg text-text-muted hover:text-primary hover:bg-bg-surface transition-colors font-label-md text-label-md"
        >
          <span class="material-symbols-outlined text-[18px]">tune</span>
          Scribe a node manually instead
        </button>
      </div>
    </div>
  </div>
{/if}
