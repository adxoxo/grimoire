<script lang="ts">
  import { api, planner, type LinkedNode, type Project, type Task } from '../lib/api'
  import { RUNE, QUADRANT, type NodeType } from '../lib/theme'
  import { link } from '../lib/router.svelte'
  import { liveRefresh } from '../lib/useLive.svelte'

  let { name }: { name: string } = $props()

  let project = $state<Project | null>(null)
  let tasks = $state<Task[]>([])
  let error = $state<string | null>(null)

  function humanize(key: string): string {
    return key.replace(/_/g, ' ').replace(/^\w/, (c) => c.toUpperCase())
  }

  function pull() {
    api
      .project(name)
      .then((p) => {
        project = p
        planner.projectTasks(p.id).then((r) => (tasks = r.tasks)).catch(() => {})
      })
      .catch((e) => (error = String(e)))
  }

  // Fresh fetch when the route's :name changes.
  $effect(() => {
    name
    project = null
    error = null
    tasks = []
    pull()
  })
  liveRefresh(pull)

  function refreshTasks() {
    if (project) planner.projectTasks(project.id).then((r) => (tasks = r.tasks)).catch(() => {})
  }
  async function completeTask(id: string) {
    await planner.completeTask(id, true)
    refreshTasks()
  }
  async function deleteTask(id: string, title: string) {
    if (!confirm(`Delete "${title}"? This cannot be undone.`)) return
    await planner.deleteTask(id)
    refreshTasks()
  }

  const linked = $derived(project?.linked ?? [])
  const chronicles = $derived(linked.filter((n) => n.type === 'memory'))
  const tomes = $derived(linked.filter((n) => n.type === 'document'))
  const runes = $derived(linked.filter((n) => n.type === 'entity'))
</script>

{#snippet linkedCard(node: LinkedNode)}
  {@const rune = RUNE[node.type]}
  <div class="bg-bg-panel border border-border-default rounded-lg p-4 hover:-translate-y-0.5 transition-all duration-200 border-t-2" style="border-top-color:{rune.color}">
    <div class="flex items-center gap-2 mb-2">
      <span class="material-symbols-outlined text-[18px]" style="color:{rune.color}">{rune.icon}</span>
      <span class="w-1.5 h-1.5 rounded-full {node.status === 'unreviewed' ? 'svg-pulse' : ''}" style="background-color:{rune.color}; box-shadow:0 0 6px {rune.color}"></span>
    </div>
    <p class="font-body-md text-body-md text-on-surface leading-snug">{node.title}</p>
  </div>
{/snippet}

{#if error}
  <div class="p-margin">
    <a href={link('/')} class="font-label-md text-label-md text-text-muted hover:text-primary uppercase tracking-widest">← Constellation</a>
    <p class="font-headline-sm text-headline-sm text-status-error mt-8">Quest line not found</p>
    <p class="font-body-sm text-body-sm text-text-tertiary mt-2">{error}</p>
  </div>
{:else if !project}
  <div class="p-margin font-headline-md text-headline-md text-text-tertiary animate-pulse">Unsealing the quest line...</div>
{:else}
  <div class="min-h-screen overflow-y-auto px-margin py-lg">
    <a href={link('/')} class="font-label-md text-label-md text-text-muted hover:text-primary uppercase tracking-widest inline-flex items-center gap-1">
      <span class="material-symbols-outlined text-[16px]">arrow_back</span> Constellation
    </a>

    <header class="mt-6 mb-lg flex items-center gap-3 border-b border-border-subtle pb-6">
      <span class="material-symbols-outlined text-rune-quest text-[32px]" style="filter:drop-shadow(0 0 8px #6fbf73)">account_tree</span>
      <div>
        <span class="font-label-md text-label-md text-rune-quest uppercase tracking-widest">Active quest line</span>
        <h1 class="font-display-lg text-display-lg text-primary leading-none">{project.title}</h1>
      </div>
    </header>

    <div class="flex flex-col lg:flex-row gap-lg">
      <!-- Main column -->
      <div class="flex-1 min-w-0 space-y-lg">
        <!-- Living context summary — clean, plainly readable -->
        <section class="bg-bg-panel border border-border-default rounded-lg border-t-2 border-t-rune-quest overflow-hidden">
          <div class="px-6 py-4 border-b border-border-subtle flex items-center gap-2">
            <span class="material-symbols-outlined text-rune-quest text-[20px]">menu_book</span>
            <h2 class="font-headline-sm text-headline-sm text-primary">Living context summary</h2>
          </div>
          <div class="px-6 py-6 max-w-[800px]">
            <p class="font-body-lg text-body-lg text-on-surface-variant whitespace-pre-line">
              {project.context_summary || 'No context recorded yet.'}
            </p>
          </div>
        </section>

        <!-- Open tasks -->
        <section>
          <h3 class="font-headline-sm text-headline-sm text-on-surface mb-3 flex items-center gap-2">
            <span class="material-symbols-outlined text-[18px] text-rune-quest">checklist</span>
            Open tasks
            {#if tasks.length > 0}<span class="font-label-md text-label-md text-text-tertiary">({tasks.length})</span>{/if}
          </h3>
          {#if tasks.length > 0}
            <div class="space-y-2">
              {#each tasks as t (t.id)}
                {@const meta = t.quadrant ? QUADRANT[t.quadrant] : QUADRANT.Q4}
                <div class="flex items-start gap-3 p-3 rounded bg-bg-panel border border-border-default group">
                  <button onclick={() => completeTask(t.id)} class="mt-0.5 w-4 h-4 rounded-sm border border-border-default flex-shrink-0 hover:bg-rune-quest/40 transition-colors" aria-label="Complete"></button>
                  <div class="flex-1 min-w-0">
                    <p class="font-body-md text-body-md text-on-surface leading-tight">{t.title}</p>
                    <div class="flex items-center gap-3 mt-1">
                      <span class="font-label-md text-[9px] uppercase px-1.5 py-0.5 rounded border" style="color:{meta.color}; border-color:{`${meta.color}4d`}">{meta.label}</span>
                      {#if t.goal_title}<span class="font-label-md text-[9px] uppercase text-text-tertiary">→ {t.goal_title}</span>{/if}
                      {#if t.estimate_minutes}<span class="font-label-md text-[10px] text-text-tertiary">{t.estimate_minutes}m</span>{/if}
                    </div>
                  </div>
                  <button onclick={() => deleteTask(t.id, t.title)} class="material-symbols-outlined text-[16px] text-text-tertiary opacity-0 group-hover:opacity-100 hover:text-status-error transition-all" aria-label="Delete task">delete</button>
                </div>
              {/each}
            </div>
          {:else}
            <p class="font-body-sm text-body-sm text-text-tertiary italic">No open tasks linked. Capture one in Today and link it here.</p>
          {/if}
        </section>

        <!-- Linked chronicles + tomes -->
        <div class="grid md:grid-cols-2 gap-md">
          <section>
            <h3 class="font-headline-sm text-headline-sm text-on-surface mb-3 flex items-center gap-2">
              <span class="material-symbols-outlined text-[18px]" style="color:{RUNE.memory.color}">{RUNE.memory.icon}</span>
              Recent chronicles
            </h3>
            <div class="space-y-3">
              {#if chronicles.length > 0}
                {#each chronicles as n (n.id)}{@render linkedCard(n)}{/each}
              {:else}
                <p class="font-body-sm text-body-sm text-text-tertiary italic">None linked yet.</p>
              {/if}
            </div>
          </section>
          <section>
            <h3 class="font-headline-sm text-headline-sm text-on-surface mb-3 flex items-center gap-2">
              <span class="material-symbols-outlined text-[18px]" style="color:{RUNE.document.color}">{RUNE.document.icon}</span>
              Linked tomes
            </h3>
            <div class="space-y-3">
              {#if tomes.length > 0}
                {#each tomes as n (n.id)}{@render linkedCard(n)}{/each}
              {:else}
                <p class="font-body-sm text-body-sm text-text-tertiary italic">None linked yet.</p>
              {/if}
            </div>
          </section>
        </div>
      </div>

      <!-- Metadata sidebar -->
      <aside class="lg:w-72 shrink-0 space-y-lg">
        <section class="bg-bg-panel border border-border-default rounded-lg p-5">
          <h3 class="font-label-md text-label-md text-text-muted uppercase tracking-widest mb-4">Quest metadata</h3>
          <dl class="space-y-3">
            <div class="flex items-center justify-between">
              <dt class="font-label-md text-label-md text-text-muted uppercase tracking-wider">Status</dt>
              <dd class="font-label-md text-label-md text-rune-quest flex items-center gap-2">
                <span class="w-2 h-2 rounded-full bg-rune-quest" style="box-shadow:0 0 8px #6fbf73"></span>
                {project.status}
              </dd>
            </div>
            {#each Object.entries(project.meta) as [k, v] (k)}
              <div class="flex items-center justify-between gap-4">
                <dt class="font-label-md text-label-md text-text-muted uppercase tracking-wider">{humanize(k)}</dt>
                <dd class="font-body-sm text-body-sm text-on-surface text-right">{String(v)}</dd>
              </div>
            {/each}
          </dl>
        </section>

        <section class="bg-bg-panel border border-border-default rounded-lg p-5">
          <h3 class="font-label-md text-label-md text-text-muted uppercase tracking-widest mb-4">Recent runes</h3>
          {#if runes.length > 0}
            <ul class="space-y-2">
              {#each runes as n (n.id)}
                <li class="flex items-center gap-2 font-body-sm text-body-sm text-on-surface">
                  <span class="material-symbols-outlined text-[16px] text-rune-entity">token</span>
                  {n.title}
                </li>
              {/each}
            </ul>
          {:else}
            <p class="font-body-sm text-body-sm text-text-tertiary italic">Runes surface through linked chronicles.</p>
          {/if}
        </section>
      </aside>
    </div>
  </div>
{/if}
