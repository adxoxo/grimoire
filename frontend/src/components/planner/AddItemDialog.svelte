<script lang="ts">
  import { fade, fly } from 'svelte/transition'
  import { quintOut } from 'svelte/easing'
  import { api, planner, type LifeArea, type Goal, type Task } from '../../lib/api'
  import { dur } from '../../lib/motion.svelte'

  type Kind = 'task' | 'habit' | 'goal'

  let {
    kind,
    defaultQuadrant,
    scheduledStart,
    onClose,
    onCreated,
    onSchedule,
  }: {
    kind: Kind
    defaultQuadrant?: { important: boolean; urgent: boolean }
    // When set (task kind, from the Flow timeline), the dialog schedules the new task at
    // this ISO time instead of just dropping it in the pool. `onSchedule` gets the result.
    scheduledStart?: string
    onClose: () => void
    onCreated: () => void
    onSchedule?: (info: { task: Task; startISO: string; durationMin: number }) => void
  } = $props()

  // Snapshot the drop-quadrant default once (the dialog is remounted per open, so this
  // plain read is the correct seed and keeps the toggles user-controlled afterwards).
  const seed = defaultQuadrant

  // HH:MM from an ISO string, and the inverse (swap the time onto the scheduled date).
  const hhmm = (iso: string) => {
    const d = new Date(iso)
    return `${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}`
  }
  function combineStart(iso: string, time: string): string {
    const d = new Date(iso)
    const [h, m] = time.split(':').map(Number)
    d.setHours(h, m, 0, 0)
    return d.toISOString()
  }

  let title = $state('')
  let busy = $state(false)
  // task
  let important = $state(seed?.important ?? false)
  let urgent = $state(seed?.urgent ?? false)
  // In scheduled mode the estimate doubles as the block duration; seed a sensible default.
  let estimate = $state(scheduledStart ? '60' : '')
  let startTime = $state(scheduledStart ? hhmm(scheduledStart) : '')
  let goalId = $state('')
  let goals = $state<Goal[]>([])
  // habit
  let cadence = $state<'daily' | 'weekly'>('daily')
  let weeklyTarget = $state('3')
  let duration = $state('')
  let windowPref = $state('anytime')
  // goal
  let why = $state('')
  let area = $state('')
  let target = $state('')
  let areas = $state<LifeArea[]>([])
  // quest line link (tasks + goals)
  let questLine = $state('')
  let questLines = $state<{ id: string; title: string }[]>([])

  $effect(() => {
    if (kind === 'task') planner.goals().then((r) => (goals = r.goals)).catch(() => {})
    if (kind === 'goal') planner.areas().then((r) => { areas = r.areas; area = r.areas[0]?.name ?? '' }).catch(() => {})
    if (kind !== 'habit') {
      api.graph().then((g) => (questLines = g.nodes.filter((n) => n.type === 'project').map((n) => ({ id: n.id, title: n.title })))).catch(() => {})
    }
  })

  async function submit() {
    if (!title.trim() || busy) return
    busy = true
    try {
      if (kind === 'task') {
        const durationMin = estimate ? Number(estimate) : undefined
        const task = await planner.createTask({
          title: title.trim(), important, urgent_manual: urgent ? true : undefined,
          estimate_minutes: durationMin, goal_id: goalId || undefined,
          project_id: questLine || undefined,
        })
        if (scheduledStart && onSchedule) {
          onSchedule({ task, startISO: combineStart(scheduledStart, startTime), durationMin: durationMin ?? 60 })
          onClose()
          return
        }
      } else if (kind === 'habit') {
        await planner.createHabit({
          name: title.trim(), cadence_type: cadence,
          weekly_target: cadence === 'weekly' ? Number(weeklyTarget) : undefined,
          duration_minutes: duration ? Number(duration) : 0, window_preference: windowPref,
        })
      } else {
        await planner.createGoal({
          title: title.trim(), why: why.trim() || undefined, area: area || undefined,
          target_date: target ? new Date(target).toISOString() : undefined,
          project_id: questLine || undefined,
        })
      }
      onCreated()
      onClose()
    } catch (e) {
      alert(`could not create ${kind}: ${e}`)
    } finally {
      busy = false
    }
  }

  const heads: Record<Kind, string> = { task: 'Scribe a task', habit: 'Inscribe a ritual', goal: 'Set a vector' }
  const field = 'w-full bg-surface-container-low border border-border-default rounded px-3 py-2 text-on-surface font-body-md text-body-md focus:outline-none focus:border-rune-entity/60'
  const lbl = 'font-label-md text-label-md text-text-muted uppercase tracking-widest mb-1 block'
</script>

<!-- svelte-ignore a11y_no_static_element_interactions -->
<div
  class="fixed inset-0 z-[60] flex items-center justify-center bg-bg-page/70 backdrop-blur-sm px-4"
  role="presentation"
  transition:fade={{ duration: dur(160) }}
  onclick={(e) => e.target === e.currentTarget && onClose()}
  onkeydown={(e) => e.key === 'Escape' && onClose()}
>
  <div transition:fly={{ y: 16, duration: dur(240), easing: quintOut }} class="w-full max-w-md bg-bg-panel border border-border-default rounded-xl p-6 shadow-[0_20px_60px_rgba(0,0,0,0.7)]">
    <h3 class="font-headline-md text-headline-md text-primary mb-4">{scheduledStart ? 'Schedule a task' : heads[kind]}</h3>

    <div class="space-y-3">
      <div>
        <label class={lbl} for="ai-title">{kind === 'habit' ? 'Name' : 'Title'}</label>
        <!-- svelte-ignore a11y_autofocus -->
        <input id="ai-title" autofocus bind:value={title}
          onkeydown={(e) => e.key === 'Enter' && kind === 'task' && submit()}
          class={field} placeholder={kind === 'habit' ? 'meditation' : kind === 'goal' ? 'Ship the beta' : 'Finish the i2c driver'} />
      </div>

      {#if kind === 'task'}
        <div class="flex gap-3">
          <button onclick={() => (important = !important)}
            class="flex-1 py-2 rounded border text-body-sm font-body-sm transition-colors {important ? 'border-rune-quest text-rune-quest bg-rune-quest/10' : 'border-border-default text-text-muted'}">
            Important
          </button>
          <button onclick={() => (urgent = !urgent)}
            class="flex-1 py-2 rounded border text-body-sm font-body-sm transition-colors {urgent ? 'border-rune-chronicle text-rune-chronicle bg-rune-chronicle/10' : 'border-border-default text-text-muted'}">
            Urgent (override)
          </button>
        </div>
        {#if scheduledStart}
          <div class="flex gap-3">
            <div class="flex-1">
              <label class={lbl} for="ai-start">Start</label>
              <input id="ai-start" bind:value={startTime} type="time" class={field} />
            </div>
            <div class="flex-1">
              <label class={lbl} for="ai-dur2">Duration (min)</label>
              <input id="ai-dur2" bind:value={estimate} type="number" class={field} placeholder="60" />
            </div>
          </div>
          <div>
            <label class={lbl} for="ai-goal">Goal</label>
            <select id="ai-goal" bind:value={goalId} class={field}>
              <option value="">— none —</option>
              {#each goals as g (g.id)}<option value={g.id}>{g.title}</option>{/each}
            </select>
          </div>
        {:else}
          <div class="flex gap-3">
            <div class="flex-1">
              <label class={lbl} for="ai-est">Estimate (min)</label>
              <input id="ai-est" bind:value={estimate} type="number" class={field} placeholder="60" />
            </div>
            <div class="flex-1">
              <label class={lbl} for="ai-goal">Goal</label>
              <select id="ai-goal" bind:value={goalId} class={field}>
                <option value="">— none —</option>
                {#each goals as g (g.id)}<option value={g.id}>{g.title}</option>{/each}
              </select>
            </div>
          </div>
        {/if}
      {/if}

      {#if kind === 'habit'}
        <div class="flex gap-3">
          <select bind:value={cadence} class={field}>
            <option value="daily">Daily</option>
            <option value="weekly">Weekly</option>
          </select>
          {#if cadence === 'weekly'}
            <input bind:value={weeklyTarget} type="number" class={field} placeholder="times / week" />
          {/if}
        </div>
        <div class="flex gap-3">
          <div class="flex-1">
            <label class={lbl} for="ai-dur">Duration (min)</label>
            <input id="ai-dur" bind:value={duration} type="number" class={field} placeholder="20" />
          </div>
          <div class="flex-1">
            <label class={lbl} for="ai-win">Window</label>
            <select id="ai-win" bind:value={windowPref} class={field}>
              {#each ['anytime', 'morning', 'midday', 'evening'] as w (w)}<option value={w}>{w}</option>{/each}
            </select>
          </div>
        </div>
      {/if}

      {#if kind === 'goal'}
        <div>
          <label class={lbl} for="ai-why">Why (the spark filter)</label>
          <input id="ai-why" bind:value={why} class={field} placeholder="why this earns your time" />
        </div>
        <div class="flex gap-3">
          <div class="flex-1">
            <label class={lbl} for="ai-area">Life area</label>
            <select id="ai-area" bind:value={area} class={field}>
              {#each areas as a (a.id)}<option value={a.name}>{a.name}</option>{/each}
            </select>
          </div>
          <div class="flex-1">
            <label class={lbl} for="ai-target">Target date</label>
            <input id="ai-target" bind:value={target} type="date" class={field} />
          </div>
        </div>
      {/if}

      {#if kind !== 'habit' && questLines.length > 0}
        <div>
          <label class={lbl} for="ai-quest">Quest line</label>
          <select id="ai-quest" bind:value={questLine} class={field}>
            <option value="">— none —</option>
            {#each questLines as p (p.id)}<option value={p.id}>{p.title}</option>{/each}
          </select>
        </div>
      {/if}
    </div>

    <div class="flex justify-end gap-3 mt-6">
      <button onclick={onClose} class="px-4 py-2 text-text-muted hover:text-on-surface font-label-md text-label-md uppercase tracking-wider">Cancel</button>
      <button onclick={submit} disabled={busy || !title.trim()}
        class="px-5 py-2 bg-surface text-primary-container border border-primary-container rounded hover:shadow-[0_0_15px_rgba(212,169,63,0.3)] transition-all font-label-md text-label-md uppercase tracking-wider disabled:opacity-40">
        {busy ? 'Scribing...' : 'Scribe'}
      </button>
    </div>
  </div>
</div>
