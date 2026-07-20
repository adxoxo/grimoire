<script lang="ts">
  import { router, link } from '../lib/router.svelte'
  import { openCapture, openTransmute } from '../lib/appstate.svelte'
  import { RUNE, SCOPE } from '../lib/theme'
  import { api } from '../lib/api'

  // The grimoire chrome in one floating pill: sigil, icon tabs, scribe. The 256px
  // rail this replaces spent a fifth of the viewport naming what these icons say.
  const tabs = [
    { to: '/today', label: 'Today', icon: 'wb_sunny', color: RUNE.project.color },
    { to: '/flow', label: 'Flow', icon: 'view_timeline', color: RUNE.entity.color },
    { to: '/', label: 'Constellation', icon: 'account_tree', color: RUNE.project.color },
    { to: '/galaxy', label: 'Galaxy', icon: 'hub', color: SCOPE.domain.color },
    { to: '/inbox', label: 'Inbox', icon: 'move_to_inbox', color: SCOPE.index.color },
    { to: '/sanctum', label: 'Sanctum', icon: 'fort', color: RUNE.memory.color },
    { to: '/settings', label: 'Settings', icon: 'settings', color: '#9b96b8' },
  ]

  const isActive = (to: string) => (to === '/' ? router.path === '/' : router.path.startsWith(to))

  // A small count badge on the Inbox tab so unfiled nodes are visible from anywhere.
  let inboxCount = $state(0)
  $effect(() => {
    let alive = true
    api.inbox(1).then((r) => { if (alive) inboxCount = r.total }).catch(() => {})
    return () => { alive = false }
  })

  // The CTA follows the surface: planner pages transmute thoughts into tasks and
  // schedule edits; knowledge surfaces scribe them into nodes.
  const onPlanner = $derived(router.path === '/today' || router.path === '/flow')
</script>

<nav
  aria-label="Primary"
  class="fixed top-4 left-1/2 -translate-x-1/2 z-50 flex items-center gap-1 rounded-full bg-bg-panel/85 backdrop-blur-md border border-border-default px-2 py-1.5 shadow-[0_4px_30px_rgba(0,0,0,0.55)]"
>
  <a
    href={link('/')}
    aria-label="The Grimoire — home"
    class="w-9 h-9 shrink-0 rounded-full border border-rune-quest/70 flex items-center justify-center mr-1 hover:shadow-[0_0_12px_rgba(212,169,63,0.45)] transition-shadow"
  >
    <span class="material-symbols-outlined text-rune-quest text-[18px]">menu_book</span>
  </a>

  <div class="w-px h-6 bg-border-subtle mx-1" aria-hidden="true"></div>

  {#each tabs as tab (tab.to)}
    {@const active = isActive(tab.to)}
    <a
      href={link(tab.to)}
      title={tab.label}
      aria-label={tab.label}
      aria-current={active ? 'page' : undefined}
      class="relative w-10 h-10 rounded-full flex items-center justify-center transition-colors {active
        ? 'bg-rune-quest/15'
        : 'hover:bg-bg-surface'}"
    >
      <span
        class="material-symbols-outlined text-[20px] transition-opacity {active ? 'opacity-100' : 'opacity-60 hover:opacity-90'}"
        style="color:{active ? tab.color : '#9b96b8'};font-variation-settings:'FILL' {active ? 1 : 0}"
      >
        {tab.icon}
      </span>
      {#if tab.to === '/inbox' && inboxCount > 0}
        <span
          class="absolute -top-0.5 -right-0.5 min-w-[16px] h-4 px-1 rounded-full bg-rune-quest text-bg-page text-[10px] font-label-md flex items-center justify-center"
          aria-label="{inboxCount} unclassified"
        >{inboxCount > 99 ? '99+' : inboxCount}</span>
      {/if}
    </a>
  {/each}

  <div class="w-px h-6 bg-border-subtle mx-1" aria-hidden="true"></div>

  {#if onPlanner}
    <button
      onclick={openTransmute}
      title="Transmute a thought into tasks or schedule changes"
      aria-label="Transmute"
      class="h-9 shrink-0 rounded-full border border-rune-entity/70 text-rune-entity px-3 flex items-center gap-1.5 hover:shadow-[0_0_15px_rgba(157,107,217,0.35)] transition-all font-label-md text-label-md"
    >
      <span class="material-symbols-outlined text-[18px]">auto_fix_high</span>
      <span class="hidden sm:inline">Transmute</span>
    </button>
  {:else}
    <button
      onclick={openCapture}
      title="Scribe a thought or attach a PDF / book"
      aria-label="Scribe"
      class="h-9 shrink-0 rounded-full border border-primary-container text-primary-container px-3 flex items-center gap-1.5 hover:shadow-[0_0_15px_rgba(212,169,63,0.3)] transition-all font-label-md text-label-md"
    >
      <span class="material-symbols-outlined text-[18px]">add</span>
      <span class="hidden sm:inline">Scribe</span>
    </button>
  {/if}
</nav>
