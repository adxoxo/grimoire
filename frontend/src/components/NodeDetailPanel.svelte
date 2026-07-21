<script lang="ts">
  import { fly } from 'svelte/transition'
  import { quintOut } from 'svelte/easing'
  import type { GraphNode } from '../lib/api'
  import { RUNE } from '../lib/theme'
  import { navigate } from '../lib/router.svelte'
  import { dur } from '../lib/motion.svelte'

  interface EdgeRow {
    src: string
    dst: string
    rel: string
    otherTitle: string
  }

  let {
    node,
    connections,
    edges,
    onPrune,
    onDelete,
    onClose,
  }: {
    node: GraphNode
    connections: number
    edges: EdgeRow[]
    onPrune: (edge: EdgeRow) => void
    onDelete: (node: GraphNode) => void
    onClose: () => void
  } = $props()

  const rune = $derived(RUNE[node.type])
  const unreviewed = $derived(node.status === 'unreviewed')

  function banish() {
    if (confirm(`Banish "${node.title}"? This removes the ${rune.label.toLowerCase()} and all its links, chunks, and history. Irreversible.`)) {
      onDelete(node)
    }
  }
</script>

<aside
  transition:fly={{ x: 24, duration: dur(260), easing: quintOut }}
  class="absolute top-24 right-4 md:right-8 w-80 max-w-[calc(100vw-2rem)] bg-bg-panel border border-border-default rounded-xl shadow-[0_0_20px_0px_rgba(0,0,0,0.8)] flex flex-col z-30 border-t-2 max-h-[80vh]"
  style="border-top-color:{rune.color}"
>
  <div class="p-4 border-b border-border-subtle flex justify-between items-start">
    <div>
      <span
        class="inline-block px-2 py-1 font-label-md text-label-md rounded mb-2"
        style="color:{rune.color}; background-color:{`${rune.color}1a`}"
      >
        {rune.label}
      </span>
      <h3 class="font-headline-sm text-headline-sm text-primary leading-snug">{node.title}</h3>
    </div>
    <button class="text-text-muted hover:text-on-surface transition-colors" onclick={onClose} aria-label="Close">
      <span class="material-symbols-outlined text-[20px]">close</span>
    </button>
  </div>

  <div class="p-4 space-y-3 overflow-y-auto">
    <div class="flex items-center justify-between">
      <span class="font-label-md text-label-md text-text-muted">Status</span>
      <span class="font-label-md text-label-md flex items-center gap-2" style="color:{rune.color}">
        <span class="w-2 h-2 rounded-full {unreviewed ? 'svg-pulse' : ''}" style="background-color:{rune.color}; box-shadow:0 0 8px {rune.color}"></span>
        {node.status ?? 'unknown'}
      </span>
    </div>
    <div class="flex items-center justify-between">
      <span class="font-label-md text-label-md text-text-muted">Connections</span>
      <span class="font-label-md text-label-md text-on-surface">{connections} nodes</span>
    </div>

    {#if edges.length > 0}
      <div class="pt-2 border-t border-border-subtle">
        <span class="font-label-md text-label-md text-text-muted">Links</span>
        <ul class="mt-2 space-y-1">
          {#each edges as e, i (i)}
            <li class="flex items-center justify-between gap-2 group">
              <span class="font-body-sm text-body-sm text-on-surface-variant truncate">
                <span class="text-text-tertiary">{e.rel}</span> {e.otherTitle}
              </span>
              <button
                onclick={() => onPrune(e)}
                title="Prune this link"
                aria-label="Prune this link"
                class="material-symbols-outlined text-[18px] text-text-tertiary hover:text-status-error transition-colors shrink-0"
              >
                content_cut
              </button>
            </li>
          {/each}
        </ul>
      </div>
    {/if}
  </div>

  <div class="p-4 border-t border-border-subtle bg-surface-container-low rounded-b-xl">
    {#if node.type === 'project'}
      <button
        class="w-full py-2 bg-surface text-primary-container border border-primary-container rounded hover:bg-bg-surface hover:shadow-[0_0_15px_0px_rgba(212,169,63,0.3)] transition-all duration-300 font-label-md text-label-md"
        onclick={() => navigate(`/project/${encodeURIComponent(node.title)}`)}
      >
        Open quest line
      </button>
    {/if}
    {#if node.type === 'document'}
      <button
        class="w-full py-2 bg-surface text-rune-tome border border-rune-tome rounded hover:bg-bg-surface hover:shadow-[0_0_15px_0px_rgba(91,141,217,0.3)] transition-all duration-300 font-label-md text-label-md"
        onclick={() => navigate(`/tome/${encodeURIComponent(node.id)}`)}
      >
        Open tome
      </button>
    {/if}
    <button
      class="w-full mt-2 py-2 bg-transparent text-text-muted border border-border-default rounded hover:border-status-error hover:text-status-error transition-all duration-300 font-label-md text-label-md flex items-center justify-center gap-2"
      onclick={banish}
    >
      <span class="material-symbols-outlined text-[16px]">delete_forever</span>
      Banish node
    </button>
  </div>
</aside>
