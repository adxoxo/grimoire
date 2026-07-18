<script lang="ts">
  import { fly, fade } from 'svelte/transition'
  import { quintOut } from 'svelte/easing'
  import { planner, type Block, type FlowData, type PlanResult, type Task } from '../lib/api'
  import { localDate } from '../lib/theme'
  import { liveRefresh } from '../lib/useLive.svelte'
  import { dur } from '../lib/motion.svelte'
  import Timeline from '../components/planner/Timeline.svelte'
  import AnchorsPanel from '../components/planner/AnchorsPanel.svelte'
  import PlannerChat from '../components/planner/PlannerChat.svelte'
  import AddItemDialog from '../components/planner/AddItemDialog.svelte'

  const today = localDate()
  // The day being viewed/planned. Every operation (plan, anchors, to-dos, generate)
  // is scoped to it; the strip below switches between days.
  let date = $state(localDate())
  let weekOffset = $state(0)

  // Slot double-clicked on the timeline -> the ISO start for the create modal (null = closed).
  let createAt = $state<string | null>(null)

  let flow = $state<FlowData | null>(null)
  let result = $state<PlanResult | null>(null)
  let blocks = $state<Block[]>([])
  let dayTasks = $state<Task[]>([])
  let newTask = $state('')
  let wake = $state('08:00')
  let sleep = $state('23:00')
  let busy = $state(false)
  let interacting = $state(false)
  let error = $state<string | null>(null)
  let seededFor = ''

  function addDays(d: string, n: number): string {
    const dt = new Date(`${d}T00:00:00`)
    dt.setDate(dt.getDate() + n)
    return localDate(dt)
  }
  const strip = $derived(Array.from({ length: 7 }, (_, i) => addDays(today, i - 3 + weekOffset * 7)))
  const dayLabel = $derived.by(() => {
    if (date === today) return 'today'
    if (date === addDays(today, -1)) return 'yesterday'
    if (date === addDays(today, 1)) return 'tomorrow'
    return new Date(`${date}T00:00:00`).toLocaleDateString(undefined, { weekday: 'long', month: 'short', day: 'numeric' })
  })

  function combine(d: string, hhmm: string): Date {
    const [h, m] = hhmm.split(':').map(Number)
    const dt = new Date(`${d}T00:00:00`)
    dt.setHours(h, m, 0, 0)
    return dt
  }
  function hhmmFromIso(iso: string | null, fallback: string): string {
    if (!iso) return fallback
    const dt = new Date(iso)
    return `${String(dt.getHours()).padStart(2, '0')}:${String(dt.getMinutes()).padStart(2, '0')}`
  }

  function load() {
    const d = date
    planner.flow(d).then((f) => {
      flow = f
      blocks = f.plan?.blocks ?? []
      if (f.plan && seededFor !== d) {
        wake = hhmmFromIso(f.plan.wake_time, '08:00')
        sleep = hhmmFromIso(f.plan.sleep_target, '23:00')
        seededFor = d
      }
    }).catch((e) => (error = String(e)))
    loadDayTasks()
  }
  $effect(load)
  liveRefresh(load, { enabled: () => !interacting && !busy, intervalMs: 15000 })

  // The day's to-do list: everything due on the viewed date, open first. This is the
  // planning surface - list things onto a day, then generate its timetable.
  function loadDayTasks() {
    const d = date
    Promise.all([planner.tasks('open'), planner.tasks('done')])
      .then(([open, done]) => {
        dayTasks = [...open.tasks, ...done.tasks]
          .filter((t) => (t.due ?? '').slice(0, 10) === d)
          .sort((a, b) => (a.status === 'done' ? 1 : 0) - (b.status === 'done' ? 1 : 0))
      })
      .catch(() => {})
  }

  async function addDayTask() {
    let title = newTask.trim()
    if (!title) return
    newTask = ''
    // Untimed tasks defer to the pool instead of scheduling, so day-listed items get a
    // 30m default; a trailing "45m" or "1.5h" in the text sets the estimate instead.
    let estimate = 30
    const m = title.match(/\s+(\d+(?:\.\d+)?)\s*(m|min|h|hr)s?$/i)
    if (m) {
      estimate = Math.round(parseFloat(m[1]) * (m[2].toLowerCase().startsWith('h') ? 60 : 1))
      title = title.slice(0, m.index).trim()
    }
    await planner.createTask({ title, due: date, estimate_minutes: estimate })
    loadDayTasks()
  }

  async function toggleDayTask(t: Task) {
    await planner.completeTask(t.id, t.status !== 'done')
    loadDayTasks()
  }

  async function removeDayTask(t: Task) {
    await planner.deleteTask(t.id)
    loadDayTasks()
  }

  function saveBlocks(next: Block[]) {
    blocks = next
    planner.saveBlocks(date, next).catch((e) => (error = String(e)))
  }
  function moveBlock(i: number, newStartISO: string) {
    const b = blocks[i]
    const span = new Date(b.end).getTime() - new Date(b.start).getTime()
    const next = blocks.map((x, j) =>
      j === i ? { ...x, start: newStartISO, end: new Date(new Date(newStartISO).getTime() + span).toISOString(), locked: true } : x,
    )
    saveBlocks(next)
  }
  function renameBlock(i: number, title: string) {
    saveBlocks(blocks.map((x, j) => (j === i ? { ...x, title } : x)))
  }
  function deleteBlock(i: number) {
    saveBlocks(blocks.filter((_, j) => j !== i))
  }

  // Pin a freshly-created task to the clicked slot: append a locked block and persist.
  // Locked so it survives reflow; "generate my day" rebuilds from scratch (documented).
  function pinTask(info: { task: Task; startISO: string; durationMin: number }) {
    const end = new Date(new Date(info.startISO).getTime() + info.durationMin * 60000).toISOString()
    const block: Block = {
      start: info.startISO, end, type: 'task', title: info.task.title,
      ref_id: info.task.id, goal_block: false, locked: true, kind: null,
    }
    saveBlocks([...blocks, block].sort((a, b) => (a.start < b.start ? -1 : a.start > b.start ? 1 : 0)))
    createAt = null
  }

  // The fixed calendar frame: wake -> sleep (sleep rolls to next day if it's "earlier").
  const windowDates = $derived.by(() => {
    const start = combine(date, wake)
    let end = combine(date, sleep)
    if (end <= start) end = new Date(end.getTime() + 86400000)
    return { start, end }
  })
  const windowLabel = $derived.by(() => {
    const min = Math.round((windowDates.end.getTime() - windowDates.start.getTime()) / 60000)
    return `${Math.floor(min / 60)}h ${min % 60}m`
  })

  async function generate() {
    busy = true
    error = null
    try {
      const w = combine(date, wake)
      let s = combine(date, sleep)
      if (s <= w) s = new Date(s.getTime() + 86400000)
      const r = await planner.generateDay({
        date, wake_time: w.toISOString(), sleep_target: s.toISOString(),
        // Clamp to the present only when planning today; another day gets its full window.
        now: date === today ? new Date().toISOString() : undefined,
        if_enabled: flow?.plan?.if_enabled, first_meal: flow?.plan?.first_meal ?? undefined,
        eating_hours: flow?.plan?.eating_hours,
      })
      result = r
      blocks = r.blocks
      load() // refresh the persisted plan so the timeline appears on a first generate
    } catch (e) {
      error = String(e)
    } finally {
      busy = false
    }
  }

  async function reflow() {
    busy = true
    error = null
    try {
      const r = await planner.reflow({ date, now: new Date().toISOString() })
      result = r
      blocks = r.blocks
    } catch (e) {
      error = `reflow needs a day plan first — generate one. (${e})`
    } finally {
      busy = false
    }
  }

  async function toggleIF() {
    if (!flow?.plan) return
    const next = !flow.plan.if_enabled
    const first = flow.plan.first_meal ?? new Date().toISOString()
    await planner.flowMeta(date, { if_enabled: next, first_meal: next ? first : undefined })
    load()
  }

  async function saveTemplate() {
    const name = prompt('Name this day-shape (e.g. "deep work day")')
    if (!name) return
    await planner.saveTemplate(name, date)
    load()
  }

  const overlay = $derived(flow?.overlay ?? null)
  const notice = $derived(result?.notice ?? null)
  const deferred = $derived(result?.deferred ?? [])
</script>

<main class="min-h-screen pb-48 overflow-y-auto">
  <div class="max-w-[1200px] mx-auto px-6 md:px-margin py-lg mt-4 md:mt-8">
    <!-- day strip: switch between days; each keeps its own plan, anchors, and to-dos -->
    <div class="flex items-center justify-center gap-1.5 mb-md flex-wrap">
      <button onclick={() => weekOffset--} aria-label="Earlier days"
        class="w-8 h-8 rounded-full flex items-center justify-center text-text-muted hover:text-on-surface hover:bg-bg-surface transition-colors">
        <span class="material-symbols-outlined text-[20px]">chevron_left</span>
      </button>
      {#each strip as d (d)}
        {@const selected = date === d}
        {@const dt = new Date(`${d}T00:00:00`)}
        <button
          onclick={() => (date = d)}
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
      <button onclick={() => weekOffset++} aria-label="Later days"
        class="w-8 h-8 rounded-full flex items-center justify-center text-text-muted hover:text-on-surface hover:bg-bg-surface transition-colors">
        <span class="material-symbols-outlined text-[20px]">chevron_right</span>
      </button>
      {#if date !== today}
        <button onclick={() => { date = today; weekOffset = 0 }}
          class="ml-2 px-3 py-1.5 rounded-full border border-border-default font-label-md text-label-md text-text-muted hover:text-rune-quest hover:border-rune-quest/50 transition-colors">
          Today
        </button>
      {/if}
    </div>

    <!-- day setup bar -->
    <div class="grimoire-card rounded-xl p-4 flex flex-wrap items-center gap-4 md:gap-6 mb-lg">
      <div>
        <label class="font-label-md text-label-md text-text-muted uppercase tracking-widest block mb-1" for="wake">Woke at</label>
        <div class="flex items-center gap-2">
          <span class="material-symbols-outlined text-rune-quest text-[18px]">wb_twilight</span>
          <input id="wake" type="time" bind:value={wake} class="bg-surface-container-low border border-border-default rounded px-2 py-1.5 text-on-surface font-body-md text-body-md focus:outline-none focus:border-rune-quest/60" />
        </div>
      </div>
      <div class="font-label-md text-label-md text-text-tertiary self-end pb-2">window {windowLabel}</div>
      <div>
        <label class="font-label-md text-label-md text-text-muted uppercase tracking-widest block mb-1" for="sleep">Sleeping around</label>
        <div class="flex items-center gap-2">
          <span class="material-symbols-outlined text-rune-entity text-[18px]">bedtime</span>
          <input id="sleep" type="time" bind:value={sleep} class="bg-surface-container-low border border-border-default rounded px-2 py-1.5 text-on-surface font-body-md text-body-md focus:outline-none focus:border-rune-entity/60" />
        </div>
      </div>
      <div class="flex-1"></div>
      <button onclick={reflow} disabled={busy || date !== today} title={date !== today ? 'Reflow applies to today only' : undefined} class="flex items-center gap-2 py-2 px-4 border border-border-default rounded text-on-surface hover:border-rune-entity/60 transition-colors font-label-md text-label-md uppercase tracking-wider disabled:opacity-40">
        <span class="material-symbols-outlined text-[18px]">refresh</span>Reflow from now
      </button>
      <button onclick={generate} disabled={busy} class="flex items-center gap-2 py-2 px-5 bg-rune-entity/20 text-rune-entity border border-rune-entity/50 rounded hover:bg-rune-entity hover:text-bg-page transition-all font-label-md text-label-md uppercase tracking-wider disabled:opacity-40">
        <span class="material-symbols-outlined text-[18px]">auto_awesome</span>{busy ? 'Weaving...' : `Generate ${dayLabel}`}
      </button>
    </div>

    {#if error}<p class="font-body-sm text-body-sm text-status-error mb-4">{error}</p>{/if}

    <div class="flex flex-col lg:flex-row gap-lg">
      <!-- timeline -->
      <div class="flex-1 min-w-0">
        <h2 class="font-headline-md text-headline-md text-primary mb-4 flex items-center gap-2">
          <span class="material-symbols-outlined">view_timeline</span>The flow
        </h2>
        {#if flow?.plan}
          <Timeline {blocks} windowStart={windowDates.start} windowEnd={windowDates.end}
            {overlay} onMove={moveBlock} onRename={renameBlock} onDelete={deleteBlock}
            onInteractingChange={(v) => (interacting = v)} onCreateAt={(iso) => (createAt = iso)} />
          <p class="font-body-sm text-body-sm text-text-tertiary mt-3 ml-14">double-click a slot to add a task · drag a block to reschedule · double-click a block to rename</p>
        {:else}
          <div class="border border-dashed border-border-default rounded-xl py-20 text-center">
            <span class="material-symbols-outlined text-[40px] text-border-default mb-2">bedtime</span>
            <p class="font-body-md text-body-md text-text-muted">Set your window and weave the day.</p>
            <p class="font-body-sm text-body-sm text-text-tertiary mt-1">The schedule is a proposal. The goals are the constant.</p>
          </div>
        {/if}
      </div>

      <!-- intentions panel -->
      <aside class="lg:w-80 shrink-0 space-y-md">
        <h2 class="font-headline-md text-headline-md text-primary flex items-center gap-2">Intentions</h2>

        <!-- the day's to-do list: list things onto a day, then generate its timetable -->
        <div class="grimoire-card rounded-lg p-3">
          <div class="flex justify-between items-baseline mb-2">
            <h4 class="font-label-md text-label-md text-text-muted uppercase tracking-widest">To do {dayLabel}</h4>
            <span class="font-label-md text-label-md text-text-tertiary">{dayTasks.filter((t) => t.status !== 'done').length} open</span>
          </div>
          <div class="flex flex-col gap-1 max-h-64 overflow-y-auto">
            {#if dayTasks.length === 0}
              <p class="font-body-sm text-body-sm text-text-tertiary py-1">Nothing listed for this day yet.</p>
            {/if}
            {#each dayTasks as t (t.id)}
              {@const done = t.status === 'done'}
              <div class="flex items-center gap-2.5 py-1.5 px-1 rounded hover:bg-bg-surface/60 transition-colors group">
                <button
                  onclick={() => toggleDayTask(t)}
                  aria-label={done ? `Reopen ${t.title}` : `Complete ${t.title}`}
                  class="w-4 h-4 rounded-full border flex-shrink-0 flex items-center justify-center transition-colors {done
                    ? 'border-rune-quest bg-rune-quest/20'
                    : 'border-border-default hover:border-rune-quest'}"
                >
                  {#if done}<span class="material-symbols-outlined text-[12px] text-rune-quest">check</span>{/if}
                </button>
                <span class="flex-1 min-w-0 truncate font-body-sm text-body-sm {done ? 'text-text-tertiary line-through' : 'text-on-surface'}">{t.title}</span>
                {#if t.estimate_minutes}
                  <span class="font-label-md text-[10px] text-text-tertiary shrink-0">{t.estimate_minutes}m</span>
                {/if}
                <button
                  onclick={() => removeDayTask(t)}
                  aria-label="Delete task"
                  class="material-symbols-outlined text-[14px] text-text-tertiary opacity-0 group-hover:opacity-100 hover:text-status-error transition-all shrink-0"
                >delete</button>
              </div>
            {/each}
          </div>
          <input
            bind:value={newTask}
            onkeydown={(e) => e.key === 'Enter' && addDayTask()}
            placeholder="Add for {dayLabel}..."
            class="mt-2 w-full bg-bg-page border border-border-subtle rounded px-2.5 py-1.5 font-body-sm text-body-sm text-on-surface placeholder:text-text-tertiary outline-none focus:border-rune-quest/60 transition-colors"
          />
        </div>

        {#if notice}
          <div transition:fly={{ y: 8, duration: dur(220), easing: quintOut }} class="bg-rune-chronicle/5 border border-rune-chronicle/30 rounded-lg p-3">
            <p class="font-label-md text-label-md text-rune-chronicle uppercase tracking-wider flex items-center gap-1 mb-1">
              <span class="material-symbols-outlined text-[16px]">warning</span>Gentle notice
            </p>
            <p class="font-body-sm text-body-sm text-on-surface-variant">{notice}</p>
          </div>
        {/if}

        {#if deferred.length > 0}
          <div>
            <h4 class="font-label-md text-label-md text-text-muted uppercase tracking-widest mb-2">Unscheduled pool</h4>
            <div class="flex flex-wrap gap-2">
              {#each deferred as d, i (i)}
                <span in:fade={{ duration: dur(160) }} title={d.reason} class="font-body-sm text-body-sm text-on-surface-variant bg-surface-container-low/60 border border-border-subtle rounded px-2 py-1">
                  {d.title}
                </span>
              {/each}
            </div>
          </div>
        {/if}

        <!-- IF overlay toggle -->
        <div class="grimoire-card rounded-lg p-3 flex items-center justify-between">
          <div>
            <p class="font-body-md text-body-md text-on-surface">Fasting overlay</p>
            <p class="font-body-sm text-body-sm text-text-tertiary">{flow?.plan?.if_enabled ? 'on · anchored to first meal' : 'off · pressure-free'}</p>
          </div>
          <button onclick={toggleIF} disabled={!flow?.plan} aria-label="Toggle fasting overlay"
            class="w-11 h-6 rounded-full transition-colors relative {flow?.plan?.if_enabled ? 'bg-rune-chronicle/60' : 'bg-surface-container-high'} disabled:opacity-40">
            <span class="absolute top-0.5 w-5 h-5 rounded-full bg-on-surface transition-all {flow?.plan?.if_enabled ? 'left-[22px]' : 'left-0.5'}"></span>
          </button>
        </div>

        <div class="grimoire-card rounded-lg p-3">
          <AnchorsPanel {date} anchors={flow?.anchors ?? []} onChange={load} />
        </div>

        <!-- templates -->
        <div class="grimoire-card rounded-lg p-3">
          <div class="flex justify-between items-center mb-2">
            <h4 class="font-label-md text-label-md text-text-muted uppercase tracking-widest">Day-shapes</h4>
            <button onclick={saveTemplate} class="font-label-md text-label-md text-rune-quest hover:text-primary uppercase tracking-wider">Save</button>
          </div>
          <div class="flex flex-wrap gap-2">
            {#if (flow?.templates ?? []).length === 0}<p class="font-body-sm text-body-sm text-text-tertiary">No saved shapes yet.</p>{/if}
            {#each flow?.templates ?? [] as t (t.template_id)}
              <button onclick={async () => { await planner.loadTemplate(t.template_id, date); load() }}
                class="font-body-sm text-body-sm text-on-surface-variant bg-surface-container-low/60 border border-border-subtle rounded px-2 py-1 hover:border-rune-quest/50">
                {t.template_name} ({t.n})
              </button>
            {/each}
          </div>
        </div>
      </aside>
    </div>
  </div>

  {#if createAt}
    <AddItemDialog kind="task" scheduledStart={createAt}
      onClose={() => (createAt = null)} onCreated={load} onSchedule={pinTask} />
  {/if}

  <PlannerChat
    placeholder="Transmute thought to schedule..."
    context={{ date, now: new Date().toISOString() }}
    quickPrompts={['regenerate my day', 'add a 30m break', 'how long is my day']}
    onActed={load}
  />
</main>
