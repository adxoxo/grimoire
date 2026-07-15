<script lang="ts">
  import { router, link } from '../lib/router.svelte'
  import { openScribe } from '../lib/appstate.svelte'
  import { RUNE, type NodeType } from '../lib/theme'

  // Mobile: the sidebar is a slide-in drawer. Desktop (md+): a fixed rail.
  let navOpen = $state(false)

  // Any route change dismisses the drawer.
  $effect(() => {
    router.path
    router.query
    navOpen = false
  })

  const planner = [
    { to: '/today', label: 'Today', icon: 'wb_sunny', color: RUNE.project.color },
    { to: '/flow', label: 'Flow', icon: 'view_timeline', color: RUNE.entity.color },
  ]

  const types: { label: string; icon: string; color: string; type: NodeType | null }[] = [
    { label: RUNE.project.nav, icon: RUNE.project.icon, color: RUNE.project.color, type: null },
    { label: RUNE.document.nav, icon: RUNE.document.icon, color: RUNE.document.color, type: 'document' },
    { label: RUNE.memory.nav, icon: RUNE.memory.icon, color: RUNE.memory.color, type: 'memory' },
    { label: RUNE.entity.nav, icon: RUNE.entity.icon, color: RUNE.entity.color, type: 'entity' },
  ]

  // Type tabs are only active on the home constellation, driven by ?type=. On any other
  // route (Today, Flow, a tome, ...) none of them is active.
  const onHome = $derived(router.path === '/')

  function typeHref(t: NodeType | null): string {
    return link(t ? `/?type=${t}` : '/')
  }
  function scribe() {
    navOpen = false
    openScribe()
  }
</script>

<!-- Mobile top bar -->
<div class="md:hidden fixed top-0 inset-x-0 h-14 z-40 flex items-center justify-between px-4 bg-bg-panel/90 backdrop-blur-md border-b border-border-default">
  <a href={link('/')} class="flex items-center gap-2">
    <span class="material-symbols-outlined text-rune-quest">menu_book</span>
    <span class="font-headline-sm text-headline-sm text-primary">The Grimoire</span>
  </a>
  <button
    onclick={() => (navOpen = !navOpen)}
    aria-label={navOpen ? 'Close menu' : 'Open menu'}
    aria-expanded={navOpen}
    class="w-10 h-10 flex items-center justify-center text-text-muted hover:text-primary"
  >
    <span class="material-symbols-outlined">{navOpen ? 'close' : 'menu'}</span>
  </button>
</div>

<!-- Mobile backdrop -->
{#if navOpen}
  <button
    class="md:hidden fixed inset-0 z-40 bg-black/60 backdrop-blur-sm"
    aria-label="Close menu"
    onclick={() => (navOpen = false)}
  ></button>
{/if}

<nav
  class="fixed top-0 left-0 h-full w-64 z-50 flex flex-col pt-8 pb-8 bg-surface-container-lowest border-r border-border-default transition-transform duration-300 md:translate-x-0 {navOpen
    ? 'translate-x-0'
    : '-translate-x-full'}"
  aria-label="Primary"
>
  <!-- Archivist sigil -->
  <div class="px-6 mb-8 flex flex-col items-center border-b border-border-subtle pb-6">
    <a
      href={link('/')}
      class="w-16 h-16 rounded-full border border-rune-quest p-1 mb-4 flex items-center justify-center glow-quest"
      aria-label="Home — the constellation"
    >
      <span class="material-symbols-outlined text-rune-quest text-[28px]">menu_book</span>
    </a>
    <h2 class="font-headline-md text-headline-md text-primary text-center">The Archivist</h2>
    <p class="font-label-md text-label-md text-text-tertiary mt-1 uppercase tracking-widest">Level IV Seeker</p>
  </div>

  <!-- Planner: the daily action surfaces -->
  <div class="w-full mb-4">
    <ul class="space-y-1">
      {#each planner as item (item.to)}
        {@const active = router.path === item.to}
        <li>
          <a
            href={link(item.to)}
            aria-current={active ? 'page' : undefined}
            class="flex items-center gap-4 py-3 pl-4 transition-all duration-200 hover:translate-x-1 group border-l-2 {active
              ? 'text-primary font-semibold border-primary bg-surface-container-high'
              : 'text-text-muted hover:text-on-surface border-transparent hover:bg-surface-container'}"
          >
            <span class="material-symbols-outlined opacity-80 group-hover:opacity-100 transition-opacity" style="color:{item.color}">{item.icon}</span>
            <span class="font-headline-sm text-headline-sm">{item.label}</span>
          </a>
        </li>
      {/each}
    </ul>
    <div class="border-t border-border-subtle mt-4 mx-4"></div>
  </div>

  <!-- Type tabs -->
  <div class="flex-1 overflow-y-auto w-full">
    <p class="font-label-md text-label-md text-text-tertiary uppercase tracking-widest pl-4 mb-2">The grimoire</p>
    <ul class="space-y-1">
      {#each types as item (item.label)}
        {@const active = onHome && (item.type ?? null) === (router.query.type ?? null)}
        <li>
          <a
            href={typeHref(item.type)}
            aria-current={active ? 'page' : undefined}
            class="flex items-center gap-4 py-3 pl-4 transition-all duration-200 hover:translate-x-1 group border-l-2 {active
              ? 'text-primary font-semibold border-primary bg-surface-container-high'
              : 'text-text-muted hover:text-on-surface border-transparent hover:bg-surface-container'}"
          >
            <span class="material-symbols-outlined opacity-80 group-hover:opacity-100 transition-opacity" style="color:{item.color}">{item.icon}</span>
            <span class="font-headline-sm text-headline-sm">{item.label}</span>
          </a>
        </li>
      {/each}
    </ul>
  </div>

  <!-- CTA + footer -->
  <div class="px-6 mt-auto flex flex-col gap-4">
    <button
      onclick={scribe}
      class="w-full py-2 bg-surface text-primary-container border border-primary-container rounded hover:bg-bg-surface hover:shadow-[0_0_15px_0px_rgba(127,201,138,0.3)] transition-all duration-300 font-headline-sm text-headline-sm flex items-center justify-center gap-2"
    >
      <span class="material-symbols-outlined">add</span>
      Scribe new node
    </button>
    <div class="border-t border-border-subtle pt-4 space-y-1">
      <a href={link('/sanctum')} class="flex items-center gap-4 py-2 text-text-muted hover:text-on-surface transition-colors duration-200">
        <span class="material-symbols-outlined text-[20px]">fort</span>
        <span class="font-label-md text-label-md uppercase tracking-widest">Sanctum</span>
      </a>
      <a href={link('/settings')} class="flex items-center gap-4 py-2 text-text-muted hover:text-on-surface transition-colors duration-200">
        <span class="material-symbols-outlined text-[20px]">settings</span>
        <span class="font-label-md text-label-md uppercase tracking-widest">Settings</span>
      </a>
    </div>
  </div>
</nav>
