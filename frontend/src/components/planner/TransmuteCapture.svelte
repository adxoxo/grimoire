<script lang="ts">
  import { fade, fly } from 'svelte/transition'
  import { appState, closeTransmute, refreshPlanner } from '../../lib/appstate.svelte'
  import { dayLabel } from '../../lib/dates'
  import { dur } from '../../lib/motion.svelte'
  import PlannerChat from './PlannerChat.svelte'

  // The transmute dialog: free-form sentences become planner actions (tasks, habits,
  // schedule edits) for the day the planner is looking at. Opened from the pill nav.
  const label = $derived(dayLabel(appState.plannerDate))
</script>

<svelte:window onkeydown={(e) => e.key === 'Escape' && appState.transmuteOpen && closeTransmute()} />

{#if appState.transmuteOpen}
  <div
    transition:fade={{ duration: dur(150) }}
    class="fixed inset-0 z-[60] bg-black/60 backdrop-blur-sm flex items-start justify-center pt-[12vh] px-4"
    onclick={(e) => e.target === e.currentTarget && closeTransmute()}
    role="presentation"
  >
    <div
      transition:fly={{ y: 14, duration: dur(200) }}
      role="dialog"
      aria-modal="true"
      aria-label="Transmute"
      class="w-full max-w-lg bg-bg-panel border border-border-default rounded-xl shadow-[0_20px_60px_rgba(0,0,0,0.7)]"
    >
      <div class="flex items-center justify-between px-5 pt-4 pb-3 border-b border-border-subtle">
        <h2 class="font-headline-sm text-headline-sm text-primary flex items-center gap-2">
          <span class="material-symbols-outlined text-rune-entity text-[20px]">auto_fix_high</span>
          Transmute
          <span class="font-label-md text-label-md text-text-tertiary normal-case tracking-normal">for {label}</span>
        </h2>
        <button
          onclick={closeTransmute}
          aria-label="Close"
          class="w-8 h-8 rounded-full flex items-center justify-center text-text-muted hover:text-on-surface hover:bg-bg-surface transition-colors"
        >
          <span class="material-symbols-outlined text-[20px]">close</span>
        </button>
      </div>
      <div class="p-5">
        <PlannerChat
          placeholder="Transmute thought to task or schedule..."
          context={{ date: appState.plannerDate, now: new Date().toISOString() }}
          quickPrompts={['regenerate my day', 'add a 30m break', 'how long is my day']}
          onActed={refreshPlanner}
        />
      </div>
    </div>
  </div>
{/if}
