<script lang="ts">
  import { api } from '../lib/api'
  import { RUNE, type NodeType } from '../lib/theme'

  type Result = { id: string; type: NodeType; title: string; project?: string } | { error: string }

  const ACCEPT = '.pdf,.epub,.fb2,.xps,.mobi,.cbz,.html,.htm,.md,.markdown,.txt'

  // Quick-capture for the constellation: type a sentence, an LLM scribes it into the
  // right node (memory / entity / document / quest line) and files it under a project.
  let { onScribed }: { onScribed: () => void } = $props()

  let value = $state('')
  let busy = $state(false)
  let status = $state<string | null>(null)
  let last = $state<Result | null>(null)
  let fileInput = $state<HTMLInputElement>()

  async function send() {
    const message = value.trim()
    if (!message || busy) return
    busy = true
    value = ''
    status = null
    try {
      last = await api.scribe(message)
      onScribed()
    } catch (e) {
      last = { error: String(e) }
    } finally {
      busy = false
    }
  }

  async function onFiles(fileList: FileList | null) {
    const files = fileList ? Array.from(fileList) : []
    if (!files.length || busy) return
    const project = value.trim() || undefined // the text box doubles as the target quest line
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
      onScribed()
    } catch (e) {
      last = { error: String(e) }
    } finally {
      busy = false
      status = null
      if (fileInput) fileInput.value = ''
    }
  }

  const ok = $derived(last && !('error' in last) ? (last as { id: string; type: NodeType; title: string; project?: string }) : null)
  const err = $derived(last && 'error' in last ? last.error : null)
  const accent = $derived(ok ? RUNE[ok.type].color : '#d4a93f')
</script>

<div class="fixed bottom-6 left-1/2 -translate-x-1/2 w-full max-w-xl px-4 z-30">
  {#if ok || err || status}
    <div class="mb-2 bg-bg-panel/90 backdrop-blur-md border border-border-default rounded-lg px-4 py-2.5 shadow-[0_8px_30px_rgba(0,0,0,0.6)]">
      {#if status}
        <p class="font-body-sm text-body-sm text-text-muted animate-pulse">{status}</p>
      {:else if ok}
        <p class="font-body-sm text-body-sm text-on-surface flex items-center gap-2">
          <span class="material-symbols-outlined text-[16px]" style="color:{accent}">{RUNE[ok.type].icon}</span>
          inscribed {RUNE[ok.type].label.toLowerCase()} <span class="text-on-surface-variant">"{ok.title}"</span>
          {#if ok.project}<span class="text-text-tertiary">under {ok.project}</span>{/if}
        </p>
      {:else}
        <p class="font-body-sm text-body-sm text-status-error">{err}</p>
      {/if}
    </div>
  {/if}
  <div
    class="bg-bg-panel/80 backdrop-blur-md border border-border-default rounded-full shadow-[0_4px_30px_rgba(0,0,0,0.5)] flex items-center px-4 py-3 group focus-within:border-rune-quest focus-within:shadow-[0_0_20px_rgba(212,169,63,0.2)] transition-all duration-300"
  >
    <span class="material-symbols-outlined mr-3 transition-colors" style="color:{busy ? '#d4a93f' : ''}">
      {busy ? 'hourglass_top' : 'edit_note'}
    </span>
    <input
      bind:value
      onkeydown={(e) => e.key === 'Enter' && send()}
      disabled={busy}
      class="bg-transparent border-none text-on-surface placeholder:text-text-tertiary w-full font-body-md text-body-md outline-none"
      placeholder="Scribe a thought, or attach a PDF / book..."
    />
    <input bind:this={fileInput} type="file" accept={ACCEPT} multiple class="hidden" onchange={(e) => onFiles((e.currentTarget as HTMLInputElement).files)} />
    <button
      onclick={() => fileInput?.click()}
      disabled={busy}
      title="Attach documents, books, or PDFs (the text box sets the quest line)"
      class="w-9 h-9 rounded-full text-text-muted flex items-center justify-center hover:text-rune-quest hover:bg-rune-quest/10 transition-colors shrink-0 disabled:opacity-40"
      aria-label="Attach files"
    >
      <span class="material-symbols-outlined text-[20px]">attach_file</span>
    </button>
    <button
      onclick={send}
      disabled={busy}
      class="w-9 h-9 rounded-full bg-rune-quest/20 text-rune-quest flex items-center justify-center hover:bg-rune-quest hover:text-bg-page transition-colors ml-1 shrink-0 disabled:opacity-40"
      aria-label="Scribe"
    >
      <span class="material-symbols-outlined text-[20px]">north</span>
    </button>
  </div>
</div>
