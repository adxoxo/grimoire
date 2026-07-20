<script lang="ts">
  import { api, type ScopeTree, type DomainScope } from '../lib/api'
  import { SCOPE } from '../lib/theme'
  import { link } from '../lib/router.svelte'
  import { refreshGraph } from '../lib/appstate.svelte'
  import { liveRefresh } from '../lib/useLive.svelte'

  // The taxonomy navigator: domains, then their indexes. An index drills into the
  // constellation focused on its member stars (/?index=id). Doubles as scope management
  // (create, refresh routing summary, delete-with-detach).
  let scopes = $state<ScopeTree | null>(null)
  let error = $state<string | null>(null)
  let openDomainId = $state<string | null>(null)
  let busy = $state<string | null>(null)

  let newDomain = $state('')
  let newIndexTitle = $state('')

  function load() {
    api.scopes().then((s) => (scopes = s)).catch((e) => (error = String(e)))
  }
  $effect(load)
  liveRefresh(load, { enabled: () => busy === null })

  const openDomain = $derived<DomainScope | null>(
    (scopes?.domains ?? []).find((d) => d.id === openDomainId) ?? null,
  )

  function fmtDate(iso: string | null): string {
    if (!iso) return 'never'
    return new Date(iso).toLocaleDateString(undefined, { month: 'short', day: 'numeric' })
  }

  async function act<T>(key: string, fn: () => Promise<T>) {
    busy = key
    try {
      await fn()
      load()
      refreshGraph()
    } catch (e) {
      error = String(e)
    } finally {
      busy = null
    }
  }

  const createDomain = () =>
    newDomain.trim() && act('new-domain', async () => { await api.createDomain(newDomain.trim()); newDomain = '' })
  const createIndex = () =>
    openDomainId && newIndexTitle.trim() &&
    act('new-index', async () => { await api.createIndex(openDomainId!, newIndexTitle.trim()); newIndexTitle = '' })
  const refresh = (id: string) => act(`refresh-${id}`, () => api.refreshSummary(id))
  const remove = (id: string, kind: string, count: number) => {
    if (!confirm(`Delete this ${kind}? Its ${count} node(s) return to the inbox; nothing is deleted.`)) return
    act(`del-${id}`, async () => { await api.deleteScope(id); if (id === openDomainId) openDomainId = null })
  }
</script>

<div class="min-h-screen overflow-y-auto px-margin py-lg max-w-5xl mx-auto">
  <!-- Breadcrumb -->
  <nav class="flex items-center gap-1.5 font-label-md text-label-md uppercase tracking-widest text-text-muted">
    <a href={link('/')} class="hover:text-primary">Constellation</a>
    <span class="text-text-tertiary">/</span>
    <button class="hover:text-primary {openDomain ? '' : 'text-primary'}" onclick={() => (openDomainId = null)}>Galaxy</button>
    {#if openDomain}
      <span class="text-text-tertiary">/</span>
      <span class="text-primary normal-case tracking-normal">{openDomain.title}</span>
    {/if}
  </nav>

  <header class="mt-6 mb-lg flex items-center gap-3 border-b border-border-subtle pb-6">
    <span class="material-symbols-outlined text-[32px]" style="color:{SCOPE.domain.color};filter:drop-shadow(0 0 8px {SCOPE.domain.color})">{SCOPE.domain.icon}</span>
    <div>
      <span class="font-label-md text-label-md uppercase tracking-widest" style="color:{SCOPE.domain.color}">
        {openDomain ? 'Domain' : 'The galaxy'}
      </span>
      <h1 class="font-headline-lg text-headline-lg text-primary leading-none">{openDomain ? openDomain.title : 'Domains & indexes'}</h1>
    </div>
    {#if scopes}
      <a href={link('/inbox')} class="ml-auto flex items-center gap-1.5 px-3 py-1.5 rounded-full border border-border-default text-text-muted hover:text-rune-quest hover:border-rune-quest/50 transition-colors font-label-md text-label-md">
        <span class="material-symbols-outlined text-[16px]">move_to_inbox</span> Inbox ({scopes.unclassified})
      </a>
    {/if}
  </header>

  {#if error}<p class="font-body-sm text-body-sm text-status-error mb-3">{error}</p>{/if}
  {#if !scopes && !error}<p class="font-headline-md text-headline-md text-text-tertiary animate-pulse">Charting the galaxy...</p>{/if}

  {#if scopes && !openDomain}
    <!-- Galaxy level: domain super-nodes -->
    <div class="mb-lg flex gap-2 max-w-md">
      <input bind:value={newDomain} placeholder="New domain, e.g. Content automation"
        class="flex-1 min-w-0 bg-bg-surface border border-border-default rounded px-3 py-2 font-body-sm text-body-sm text-on-surface" />
      <button onclick={createDomain} disabled={busy !== null || !newDomain.trim()}
        class="px-4 py-2 border border-primary-container text-primary-container rounded font-label-md text-label-md uppercase tracking-wider disabled:opacity-40">Create</button>
    </div>

    {#if scopes.domains.length === 0}
      <p class="font-body-lg text-body-lg text-text-tertiary">No domains yet. Create one above, or bootstrap the taxonomy from your clusters via chat.</p>
    {/if}

    <div class="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
      {#each scopes.domains as d (d.id)}
        <div class="bg-bg-panel border border-border-default rounded-xl p-5 flex flex-col gap-3">
          <div class="flex items-start justify-between gap-2">
            <button class="text-left min-w-0 flex items-center gap-2" onclick={() => (openDomainId = d.id)}>
              <span class="material-symbols-outlined text-[22px]" style="color:{SCOPE.domain.color}">{SCOPE.domain.icon}</span>
              <span class="font-headline-sm text-headline-sm text-primary truncate">{d.title}</span>
            </button>
            {#if d.stale}<span class="shrink-0 w-2 h-2 rounded-full bg-status-error" title="Summary stale or missing"></span>{/if}
          </div>
          <div class="flex items-center gap-3 font-body-sm text-body-sm text-text-muted">
            <span>{d.indexes.length} indexes</span>
            <span>{d.node_count} nodes</span>
          </div>
          {#if d.summary}
            <p class="font-body-sm text-body-sm text-text-tertiary line-clamp-2">{d.summary}</p>
          {:else}
            <p class="font-body-sm text-body-sm text-text-tertiary italic">No routing summary yet.</p>
          {/if}
          <div class="mt-auto flex items-center gap-2 pt-2">
            <button onclick={() => (openDomainId = d.id)} class="px-3 py-1.5 border border-border-default rounded font-label-md text-label-md uppercase tracking-wider text-text-muted hover:text-primary hover:border-primary/50">Open</button>
            <button onclick={() => refresh(d.id)} disabled={busy !== null} title="Regenerate routing summary" class="w-8 h-8 flex items-center justify-center rounded border border-border-default text-text-muted hover:text-primary disabled:opacity-40">
              <span class="material-symbols-outlined text-[16px]">{busy === `refresh-${d.id}` ? 'hourglass_empty' : 'refresh'}</span>
            </button>
            <button onclick={() => remove(d.id, 'domain', d.node_count)} disabled={busy !== null} title="Delete domain" class="w-8 h-8 flex items-center justify-center rounded border border-border-default text-text-muted hover:text-status-error hover:border-status-error disabled:opacity-40">
              <span class="material-symbols-outlined text-[16px]">delete</span>
            </button>
          </div>
        </div>
      {/each}
    </div>
  {/if}

  {#if openDomain}
    <!-- Domain level: its indexes -->
    <div class="mb-lg flex items-center gap-2 flex-wrap">
      <div class="flex gap-2 max-w-md flex-1">
        <input bind:value={newIndexTitle} placeholder="New index, e.g. YouTube"
          class="flex-1 min-w-0 bg-bg-surface border border-border-default rounded px-3 py-2 font-body-sm text-body-sm text-on-surface" />
        <button onclick={createIndex} disabled={busy !== null || !newIndexTitle.trim()}
          class="px-4 py-2 border border-primary-container text-primary-container rounded font-label-md text-label-md uppercase tracking-wider disabled:opacity-40">Create</button>
      </div>
      <button onclick={() => refresh(openDomain.id)} disabled={busy !== null} class="px-3 py-2 border border-border-default rounded font-label-md text-label-md uppercase tracking-wider text-text-muted hover:text-primary">Refresh domain summary</button>
    </div>

    {#if openDomain.indexes.length === 0}
      <p class="font-body-lg text-body-lg text-text-tertiary">No indexes in this domain yet.</p>
    {/if}

    <div class="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
      {#each openDomain.indexes as i (i.id)}
        <div class="bg-bg-panel border border-border-default rounded-xl p-5 flex flex-col gap-3 border-l-4" style="border-left-color:{SCOPE.index.color}">
          <div class="flex items-start justify-between gap-2">
            <div class="min-w-0 flex items-center gap-2">
              <span class="material-symbols-outlined text-[20px]" style="color:{SCOPE.index.color}">{SCOPE.index.icon}</span>
              <span class="font-headline-sm text-headline-sm text-primary truncate">{i.title}</span>
            </div>
            {#if i.stale}<span class="shrink-0 w-2 h-2 rounded-full bg-status-error" title="Summary stale or missing"></span>{/if}
          </div>
          <div class="flex items-center gap-3 font-body-sm text-body-sm text-text-muted">
            <span>{i.node_count} nodes</span>
            <span title="Last summary refresh">summary {fmtDate(i.summary_updated_at)}</span>
          </div>
          {#if i.summary}
            <p class="font-body-sm text-body-sm text-text-tertiary line-clamp-3">{i.summary}</p>
          {:else}
            <p class="font-body-sm text-body-sm text-text-tertiary italic">No routing summary yet.</p>
          {/if}
          <div class="mt-auto flex items-center gap-2 pt-2">
            <a href={link(`/?index=${i.id}`)} class="px-3 py-1.5 border border-border-default rounded font-label-md text-label-md uppercase tracking-wider text-text-muted hover:text-primary hover:border-primary/50 flex items-center gap-1">
              <span class="material-symbols-outlined text-[16px]">auto_awesome</span> View stars
            </a>
            <button onclick={() => refresh(i.id)} disabled={busy !== null} title="Regenerate routing summary" class="w-8 h-8 flex items-center justify-center rounded border border-border-default text-text-muted hover:text-primary disabled:opacity-40">
              <span class="material-symbols-outlined text-[16px]">{busy === `refresh-${i.id}` ? 'hourglass_empty' : 'refresh'}</span>
            </button>
            <button onclick={() => remove(i.id, 'index', i.node_count)} disabled={busy !== null} title="Delete index" class="w-8 h-8 flex items-center justify-center rounded border border-border-default text-text-muted hover:text-status-error hover:border-status-error disabled:opacity-40">
              <span class="material-symbols-outlined text-[16px]">delete</span>
            </button>
          </div>
        </div>
      {/each}
    </div>
  {/if}
</div>
