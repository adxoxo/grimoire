<script lang="ts">
  import { appState } from '../../lib/appstate.svelte'
  import { localDate } from '../../lib/theme'
  import { addDays } from '../../lib/dates'

  // The planner calendar: a fixed seven-day window centred on today. Clicking a day only
  // selects it (the window does not move); the arrows slide the whole window by ONE day
  // (17..23 -> 18..24). "Today" re-centres the window and selects today.
  const today = localDate()
  let offset = $state(0) // days the window is slid from its today-centred default
  const strip = $derived(Array.from({ length: 7 }, (_, i) => addDays(today, i - 3 + offset)))
  const slid = $derived(offset !== 0 || appState.plannerDate !== today)
</script>

<div class="flex items-center justify-center gap-1.5 flex-wrap">
  <button
    onclick={() => offset--}
    aria-label="Slide back a day"
    class="w-8 h-8 rounded-full flex items-center justify-center text-text-muted hover:text-on-surface hover:bg-bg-surface transition-colors"
  >
    <span class="material-symbols-outlined text-[20px]">chevron_left</span>
  </button>
  {#each strip as d (d)}
    {@const selected = appState.plannerDate === d}
    {@const isToday = d === today}
    {@const dt = new Date(`${d}T00:00:00`)}
    <button
      onclick={() => (appState.plannerDate = d)}
      aria-pressed={selected}
      aria-current={isToday ? 'date' : undefined}
      class="w-12 py-1.5 rounded-lg flex flex-col items-center gap-0.5 border transition-colors {selected
        ? 'border-rune-quest/60 bg-rune-quest/10'
        : isToday
          ? 'border-rune-quest/25 hover:bg-bg-surface'
          : 'border-transparent hover:bg-bg-surface'}"
    >
      <span class="font-label-md text-[10px] {selected ? 'text-rune-quest' : 'text-text-tertiary'}">
        {dt.toLocaleDateString(undefined, { weekday: 'short' })}
      </span>
      <span class="font-headline-sm text-headline-sm leading-none {selected ? 'text-primary' : 'text-text-muted'}">{dt.getDate()}</span>
      <span class="w-1 h-1 rounded-full {isToday ? 'bg-rune-quest' : 'bg-transparent'}"></span>
    </button>
  {/each}
  <button
    onclick={() => offset++}
    aria-label="Slide forward a day"
    class="w-8 h-8 rounded-full flex items-center justify-center text-text-muted hover:text-on-surface hover:bg-bg-surface transition-colors"
  >
    <span class="material-symbols-outlined text-[20px]">chevron_right</span>
  </button>
  {#if slid}
    <button
      onclick={() => { appState.plannerDate = today; offset = 0 }}
      class="ml-2 px-3 py-1.5 rounded-full border border-border-default font-label-md text-label-md text-text-muted hover:text-rune-quest hover:border-rune-quest/50 transition-colors"
    >
      Today
    </button>
  {/if}
</div>
