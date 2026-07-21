<script lang="ts">
  import {
    API_TOKEN_KEY, api,
    type CompactResult, type JobStart, type ReclusterResult, type ReembedResult,
  } from '../lib/api'
  import { link } from '../lib/router.svelte'
  import { refreshGraph } from '../lib/appstate.svelte'
  import {
    anyRunning, jobFor, jobsState, refreshJobs, startPollingWhileRunning,
  } from '../lib/jobs.svelte'

  interface JobDef {
    key: string
    title: string
    icon: string
    blurb: string
    start: () => Promise<JobStart>
    format: (result: unknown) => string
  }

  const JOBS: JobDef[] = [
    {
      key: 'compact',
      title: 'Compaction job',
      icon: 'compress',
      blurb:
        'Merge overlapping old memories into consolidated chronicles and refresh each project’s living context. Uses the LLM chain (Groq, falling back to Ollama).',
      start: () => api.compact(),
      format: (result) => {
        const r = result as CompactResult
        const total = r.compacted.reduce((n, c) => n + c.clusters_merged, 0)
        return `Compacted ${r.compacted.length} project(s), merged ${total} cluster(s).`
      },
    },
    {
      key: 'reembed',
      title: 'Re-embedding routine',
      icon: 'autorenew',
      blurb: 'Walk every chunk and re-embed it through the provider. The maintenance path for changing embedding models.',
      start: () => api.reembed(),
      format: (result) => {
        const r = result as ReembedResult
        return `Re-embedded ${r.reembedded.chunks} chunk(s), ${r.reembedded.scopes} scope summary(ies).`
      },
    },
    {
      key: 'recluster',
      title: 'Community detection',
      icon: 'hub',
      blurb: 'Recompute Louvain communities over the constellation. The global graph view colours its clusters from this.',
      start: () => api.recluster(),
      format: (result) => {
        const r = result as ReclusterResult
        return `Assigned ${r.nodes} node(s) to ${r.communities} communit(ies).`
      },
    },
  ]

  // These jobs now run server-side on a background thread; this view mirrors their status
  // from the shared store, so a run keeps showing "Running..." across navigation and tab
  // switches instead of silently resetting. Errors surface on the job itself.
  let actionError = $state<Record<string, string>>({})

  // On mount, sync job state and resume polling if something is already running (a job
  // started here or in another tab). Runs once (no reactive reads).
  $effect(() => {
    refreshJobs()
    startPollingWhileRunning()
  })

  // Refresh the constellation once per job completion (compaction and reclustering both
  // change what the graph draws). Plain bookkeeping map, deliberately not reactive.
  const seenFinished: Record<string, string> = {}
  $effect(() => {
    for (const [key, j] of Object.entries(jobsState.byKind)) {
      if (j.status === 'done' && j.finished_at && seenFinished[key] !== j.finished_at) {
        seenFinished[key] = j.finished_at
        refreshGraph()
      }
    }
  })

  function buttonLabel(key: string): string {
    const j = jobFor(key)
    if (j?.status !== 'running') return 'Run'
    const p = j.progress
    return p && p.total > 0 ? `Running ${p.done}/${p.total}` : 'Running...'
  }

  // Bearer token for write routes (matches the server's GRIMOIRE_API_TOKEN). Stored
  // locally; empty when the server runs unguarded.
  let apiToken = $state(localStorage.getItem(API_TOKEN_KEY) ?? '')

  function saveToken() {
    if (apiToken.trim()) localStorage.setItem(API_TOKEN_KEY, apiToken.trim())
    else localStorage.removeItem(API_TOKEN_KEY)
  }

  async function trigger(job: JobDef) {
    actionError = { ...actionError, [job.key]: '' }
    try {
      await job.start()
      await refreshJobs()
      startPollingWhileRunning()
    } catch (e) {
      actionError = { ...actionError, [job.key]: `failed to start: ${e}` }
    }
  }
</script>

<div class="min-h-screen overflow-y-auto px-margin py-lg max-w-3xl mx-auto">
  <a href={link('/')} class="font-label-md text-label-md text-text-muted hover:text-primary inline-flex items-center gap-1">
    <span class="material-symbols-outlined text-[16px]">arrow_back</span> Constellation
  </a>

  <header class="mt-6 mb-lg flex items-center gap-3 border-b border-border-subtle pb-6">
    <span class="material-symbols-outlined text-primary-container text-[32px]" style="filter:drop-shadow(0 0 8px #d4a93f)">settings</span>
    <div>
      <span class="font-label-md text-label-md text-primary-container">Settings</span>
      <h1 class="font-headline-lg text-headline-lg text-primary leading-none">Maintenance rites</h1>
    </div>
  </header>

  <div class="space-y-md">
    {#each JOBS as job (job.key)}
      <section class="grimoire-card rounded-lg p-5 flex items-start gap-4">
        <span class="material-symbols-outlined text-rune-quest text-[24px] mt-1">{job.icon}</span>
        <div class="flex-1 min-w-0">
          <h2 class="font-headline-sm text-headline-sm text-primary">{job.title}</h2>
          <p class="font-body-sm text-body-sm text-text-muted mt-1">{job.blurb}</p>
          {#if jobFor(job.key)}
            {@const j = jobFor(job.key)}
            {#if j?.status === 'running' && j.progress?.detail}
              <p class="font-body-sm text-body-sm text-text-muted mt-2">
                {j.progress.detail}{j.progress.total > 0 ? ` (${j.progress.done}/${j.progress.total})` : ''}
              </p>
            {:else if j?.status === 'done'}
              <p class="font-body-sm text-body-sm text-rune-quest mt-2">{job.format(j.result)}</p>
            {:else if j?.status === 'failed'}
              <p class="font-body-sm text-body-sm text-status-error mt-2">failed: {j.error}</p>
            {/if}
          {/if}
          {#if actionError[job.key]}
            <p class="font-body-sm text-body-sm text-status-error mt-2">{actionError[job.key]}</p>
          {/if}
        </div>
        <button
          onclick={() => trigger(job)}
          disabled={anyRunning()}
          class="shrink-0 py-2 px-4 bg-surface text-primary-container border border-primary-container rounded hover:bg-bg-surface hover:shadow-[0_0_15px_0px_rgba(212,169,63,0.3)] transition-all duration-300 font-label-md text-label-md disabled:opacity-40"
        >
          {buttonLabel(job.key)}
        </button>
      </section>
    {/each}

    <section class="grimoire-card rounded-lg p-5 flex items-start gap-4">
      <span class="material-symbols-outlined text-rune-quest text-[24px] mt-1">key</span>
      <div class="flex-1 min-w-0">
        <h2 class="font-headline-sm text-headline-sm text-primary">API token</h2>
        <p class="font-body-sm text-body-sm text-text-muted mt-1">
          Sent as a bearer token on writes. Required once the server sets GRIMOIRE_API_TOKEN; leave empty for an unguarded local server.
        </p>
        <input
          type="password"
          bind:value={apiToken}
          onblur={saveToken}
          placeholder="Paste the token"
          aria-label="API token"
          autocomplete="off"
          class="mt-3 w-full max-w-sm bg-bg-page border border-border-default rounded px-3 py-2 font-body-sm text-body-sm text-on-surface outline-none focus:border-rune-quest"
        />
      </div>
    </section>
  </div>
</div>
