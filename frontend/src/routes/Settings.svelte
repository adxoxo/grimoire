<script lang="ts">
  import { api } from '../lib/api'
  import { link } from '../lib/router.svelte'
  import { refreshGraph } from '../lib/appstate.svelte'

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
      blurb:
        'Merge overlapping old memories into consolidated chronicles and refresh each project’s living context. Uses the LLM chain (Groq, falling back to Ollama).',
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
    {
      key: 'recluster',
      title: 'Community detection',
      icon: 'hub',
      blurb: 'Recompute Louvain communities over the constellation. The global graph view colours its clusters from this.',
      run: async () => {
        const r = await api.recluster()
        refreshGraph()
        return `Assigned ${r.nodes} node(s) to ${r.communities} communit(ies).`
      },
    },
  ]

  let running = $state<string | null>(null)
  let results = $state<Record<string, string>>({})

  async function trigger(job: Job) {
    running = job.key
    results = { ...results, [job.key]: '' }
    try {
      const msg = await job.run()
      results = { ...results, [job.key]: msg }
      refreshGraph()
    } catch (e) {
      results = { ...results, [job.key]: `failed: ${e}` }
    } finally {
      running = null
    }
  }
</script>

<div class="min-h-screen overflow-y-auto px-margin py-lg max-w-3xl">
  <a href={link('/')} class="font-label-md text-label-md text-text-muted hover:text-primary uppercase tracking-widest inline-flex items-center gap-1">
    <span class="material-symbols-outlined text-[16px]">arrow_back</span> Constellation
  </a>

  <header class="mt-6 mb-lg flex items-center gap-3 border-b border-border-subtle pb-6">
    <span class="material-symbols-outlined text-primary-container text-[32px]" style="filter:drop-shadow(0 0 8px #d4a93f)">settings</span>
    <div>
      <span class="font-label-md text-label-md text-primary-container uppercase tracking-widest">Settings</span>
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
          {#if results[job.key]}
            <p class="font-body-sm text-body-sm text-rune-quest mt-2">{results[job.key]}</p>
          {/if}
        </div>
        <button
          onclick={() => trigger(job)}
          disabled={running !== null}
          class="shrink-0 py-2 px-4 bg-surface text-primary-container border border-primary-container rounded hover:bg-bg-surface hover:shadow-[0_0_15px_0px_rgba(212,169,63,0.3)] transition-all duration-300 font-label-md text-label-md uppercase tracking-wider disabled:opacity-40"
        >
          {running === job.key ? 'Running...' : 'Run'}
        </button>
      </section>
    {/each}
  </div>
</div>
