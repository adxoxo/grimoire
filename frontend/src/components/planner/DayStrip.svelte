<script lang="ts">
  import { appState } from '../../lib/appstate.svelte'
  import { localDate } from '../../lib/theme'
  import { addDays } from '../../lib/dates'

  // The planner calendar: seven day chips around today, arrows to page by week.
  // Writes the shared plannerDate so Today and Flow stay on the same day.
  const today = localDate()
  let weekOffset = $state(0)
  const strip = $derived(Array.from({ length: 7 }, (_, i) => addDays(today, i - 3 + weekOffset * 7)))
</script>

<div class="flex items-center justify-center gap-1.5 flex-wrap">
  <button
    onclick={() => weekOffset--}
    aria-label="Earlier days"
    class="w-8 h-8 rounded-full flex items-center justify-center text-text-muted hover:text-on-surface hover:bg-bg-surface transition-colors"
  >
    <span class="material-symbols-outlined text-[20px]">chevron_left</span>
  </button>
  {#each strip as d (d)}
    {@const selected = appState.plannerDate === d}
    {@const dt = new Date(`${d}T00:00:00`)}
    <button
      onclick={() => (appState.plannerDate = d)}
      aria-pressed={selected}
      class="w-12 py-1.5 rounded-lg flex flex-col items-center gap-0.5 border transition-colors {selected
        ? 'border-rune-quest/60 bg-rune-quest/10'
        : 'border-transparent hover:bg-bg-surface'}"
    >
      <span class="font-label-md text-[10px] uppercase tracking-wider {selected ? 'text-rune-quest' : 'text-text-tertiary'}">
        {dt.toLocaleDateString(undefined, { weekday: 'short' })}
      </span>
      <span class="font-headline-sm text-headline-sm leading-none {selected ? 'text-primary' : 'text-text-muted'}">{dt.getDate()}</span>
      <span class="w-1 h-1 rounded-full {d === today ? 'bg-rune-quest' : 'bg-transparent'}"></span>
    </button>
  {/each}
  <button
    onclick={() => weekOffset++}
    aria-label="Later days"
    class="w-8 h-8 rounded-full flex items-center justify-center text-text-muted hover:text-on-surface hover:bg-bg-surface transition-colors"
  >
    <span class="material-symbols-outlined text-[20px]">chevron_right</span>
  </button>
  {#if appState.plannerDate !== today}
    <button
      onclick={() => { appState.plannerDate = today; weekOffset = 0 }}
      class="ml-2 px-3 py-1.5 rounded-full border border-border-default font-label-md text-label-md text-text-muted hover:text-rune-quest hover:border-rune-quest/50 transition-colors"
    >
      Today
    </button>
  {/if}
</div>
