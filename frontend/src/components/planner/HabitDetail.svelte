<script lang="ts">
  import { fade, fly } from 'svelte/transition'
  import { quintOut } from 'svelte/easing'
  import { planner, type Habit, type Streak } from '../../lib/api'
  import { localDate } from '../../lib/theme'
  import { dur } from '../../lib/motion.svelte'
  import InlineEdit from './InlineEdit.svelte'

  // Double-clicking a ritual in Today opens this: a completion calendar (which days you
  // did it, which you didn't), streaks, and click-to-toggle any day (backfill included).
  let {
    habit,
    onClose,
    onChanged,
  }: {
    habit: Habit
    onClose: () => void
    onChanged: () => void
  } = $props()

  const WEEKS = 18
  const WEEKDAYS = ['Mon', '', 'Wed', '', 'Fri', '', '']
  const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']

  let dates = $state<string[]>([])
  let streak = $state<Streak | undefined>(habit.streak)
  let name = $state(habit.name) // local so a rename shows immediately, not the stale prop
  let busy = $state(false)
  const todayIso = localDate()

  async function loadHistory() {
    try {
      const h = await planner.habitHistory(habit.id)
      dates = h.dates ?? []
      if (h.streak) streak = h.streak
    } catch {
      dates = []
    }
  }
  $effect(() => {
    habit.id
    loadHistory()
  })

  function iso(d: Date): string {
    return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`
  }

  interface Day { iso: string; done: boolean; isToday: boolean; future: boolean }
  interface Week { days: Day[]; month: string | null }

  // 18 weeks up to today, columns = weeks (Mon..Sun). A month label sits above the first
  // column of each new month.
  const weeks = $derived.by(() => {
    const done = new Set(dates)
    const today = new Date(todayIso + 'T00:00:00')
    const dow = (today.getDay() + 6) % 7 // 0 = Monday
    const start = new Date(today)
    start.setDate(today.getDate() - dow - (WEEKS - 1) * 7)
    const out: Week[] = []
    let prevMonth = -1
    for (let w = 0; w < WEEKS; w++) {
      const days: Day[] = []
      let month: string | null = null
      for (let d = 0; d < 7; d++) {
        const cur = new Date(start)
        cur.setDate(start.getDate() + w * 7 + d)
        const id = iso(cur)
        if (d === 0 && cur.getMonth() !== prevMonth) {
          month = MONTHS[cur.getMonth()]
          prevMonth = cur.getMonth()
        }
        days.push({ iso: id, done: done.has(id), isToday: id === todayIso, future: id > todayIso })
      }
      out.push({ days, month })
    }
    return out
  })

  const total = $derived(dates.length)

  async function toggleDay(day: Day) {
    if (day.future || busy) return
    busy = true
    try {
      await planner.toggleHabit(habit.id, day.iso)
      await loadHistory()
      onChanged()
    } finally {
      busy = false
    }
  }

  async function rename(next: string) {
    name = next
    await planner.modifyHabit(habit.id, { name: next })
    onChanged()
  }

  async function remove() {
    if (!confirm(`Delete ritual "${name}"? Its streak history goes with it.`)) return
    await planner.deleteHabit(habit.id)
    onChanged()
    onClose()
  }
</script>

<!-- svelte-ignore a11y_no_static_element_interactions -->
<div
  class="fixed inset-0 z-[60] flex items-center justify-center bg-black/70 backdrop-blur-sm px-4"
  role="presentation"
  transition:fade={{ duration: dur(160) }}
  onclick={(e) => e.target === e.currentTarget && onClose()}
  onkeydown={(e) => e.key === 'Escape' && onClose()}
>
  <div transition:fly={{ y: 16, duration: dur(240), easing: quintOut }}
    class="w-full max-w-lg bg-bg-panel border border-border-default rounded-xl border-t-2 border-t-rune-quest shadow-[0_20px_60px_rgba(0,0,0,0.7)]">
    <!-- header -->
    <div class="px-6 py-4 border-b border-border-subtle flex items-start justify-between gap-3">
      <div class="min-w-0">
        <div class="flex items-center gap-2 mb-1">
          <span class="material-symbols-outlined text-rune-quest text-[20px]">bolt</span>
          <span class="font-label-md text-label-md text-rune-quest uppercase tracking-widest">
            {habit.cadence_type === 'weekly' ? `Ritual · ${habit.weekly_target ?? 1}×/week` : 'Daily ritual'}
          </span>
        </div>
        <div class="font-headline-md text-headline-md text-primary">
          <InlineEdit value={name} onSave={rename}
            textClassName="font-headline-md text-headline-md text-primary"
            inputClassName="bg-surface-container-low border border-rune-quest/60 rounded px-2 py-0.5 text-primary font-headline-md text-headline-md focus:outline-none" />
        </div>
      </div>
      <button onclick={onClose} class="text-text-muted hover:text-on-surface shrink-0" aria-label="Close">
        <span class="material-symbols-outlined text-[20px]">close</span>
      </button>
    </div>

    <!-- streak stats -->
    <div class="px-6 py-4 flex items-center gap-6 border-b border-border-subtle">
      <div class="flex items-center gap-2">
        <span class="material-symbols-outlined text-secondary text-[20px]" style="font-variation-settings:'FILL' 1">local_fire_department</span>
        <div>
          <p class="font-headline-sm text-headline-sm text-on-surface leading-none">{streak?.current ?? 0}</p>
          <p class="font-label-md text-label-md text-text-tertiary uppercase tracking-wider mt-0.5">Current</p>
        </div>
      </div>
      <div>
        <p class="font-headline-sm text-headline-sm text-on-surface leading-none">{streak?.best ?? 0}</p>
        <p class="font-label-md text-label-md text-text-tertiary uppercase tracking-wider mt-0.5">Best</p>
      </div>
      <div>
        <p class="font-headline-sm text-headline-sm text-on-surface leading-none">{total}</p>
        <p class="font-label-md text-label-md text-text-tertiary uppercase tracking-wider mt-0.5">Total</p>
      </div>
    </div>

    <!-- calendar -->
    <div class="px-6 py-5">
      <p class="font-label-md text-label-md text-text-muted uppercase tracking-widest mb-3">Last {WEEKS} weeks · tap a day to log it</p>
      <div class="overflow-x-auto pb-1">
        <div class="flex gap-[3px] min-w-max">
          <!-- weekday labels -->
          <div class="flex flex-col gap-[3px] mr-1 pt-[18px]">
            {#each WEEKDAYS as wd, i (i)}
              <span class="h-[14px] w-6 font-label-md text-[9px] text-text-tertiary leading-[14px]">{wd}</span>
            {/each}
          </div>
          {#each weeks as week, wi (wi)}
            <div class="flex flex-col gap-[3px]">
              <span class="h-[15px] font-label-md text-[9px] text-text-tertiary leading-none">{week.month ?? ''}</span>
              {#each week.days as day (day.iso)}
                {#if day.future}
                  <span class="w-[14px] h-[14px]"></span>
                {:else}
                  <button
                    onclick={() => toggleDay(day)}
                    disabled={busy}
                    title={`${day.iso}${day.done ? ' · done' : ' · not logged'}`}
                    aria-label={`${day.iso}${day.done ? ', done, tap to clear' : ', not logged, tap to log'}`}
                    class="w-[14px] h-[14px] rounded-sm border transition-colors disabled:opacity-60
                      {day.done ? 'bg-rune-quest border-rune-quest' : 'bg-surface-container border-border-subtle hover:border-rune-quest/50'}
                      {day.isToday ? 'ring-1 ring-primary ring-offset-1 ring-offset-bg-panel' : ''}"
                    style={day.done ? 'box-shadow:0 0 6px rgba(111,191,115,0.5)' : ''}
                  ></button>
                {/if}
              {/each}
            </div>
          {/each}
        </div>
      </div>
      <div class="flex items-center gap-2 mt-3 font-label-md text-[10px] text-text-tertiary">
        <span>Not logged</span>
        <span class="w-[12px] h-[12px] rounded-sm bg-surface-container border border-border-subtle"></span>
        <span class="w-[12px] h-[12px] rounded-sm bg-rune-quest border border-rune-quest"></span>
        <span>Done</span>
      </div>
    </div>

    <!-- footer -->
    <div class="px-6 py-4 border-t border-border-subtle flex justify-between items-center">
      <button onclick={remove}
        class="py-2 px-3 bg-transparent text-text-muted border border-border-default rounded hover:border-status-error hover:text-status-error transition-all font-label-md text-label-md uppercase tracking-wider flex items-center gap-1">
        <span class="material-symbols-outlined text-[16px]">delete</span> Delete ritual
      </button>
      <button onclick={onClose}
        class="py-2 px-4 bg-surface text-primary-container border border-primary-container rounded hover:bg-bg-surface hover:shadow-[0_0_15px_0px_rgba(127,201,138,0.3)] transition-all font-label-md text-label-md uppercase tracking-wider">
        Done
      </button>
    </div>
  </div>
</div>
