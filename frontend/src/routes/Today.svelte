<script lang="ts">
  import { fade, fly, scale } from 'svelte/transition'
  import { flip } from 'svelte/animate'
  import { quintOut } from 'svelte/easing'
  import { api, planner, type Habit, type Task, type AreaGroup, type TodayData } from '../lib/api'
  import { QUADRANT, type Quadrant } from '../lib/theme'
  import { dayLabel } from '../lib/dates'
  import { appState } from '../lib/appstate.svelte'
  import { liveRefresh } from '../lib/useLive.svelte'
  import { dur } from '../lib/motion.svelte'
  import { taskSend, taskReceive } from '../lib/planner-motion'
  import InlineEdit from '../components/planner/InlineEdit.svelte'
  import AddItemDialog from '../components/planner/AddItemDialog.svelte'
  import DayStrip from '../components/planner/DayStrip.svelte'
  import HabitDetail from '../components/planner/HabitDetail.svelte'

  const QUADRANT_ORDER: Quadrant[] = ['Q1', 'Q2', 'Q3', 'Q4']

  // Flags each quadrant writes on drop (urgent as a manual override so placement wins).
  const Q_FLAGS: Record<Quadrant, { important: boolean; urgent: boolean }> = {
    Q1: { important: true, urgent: true },
    Q2: { important: true, urgent: false },
    Q3: { important: false, urgent: true },
    Q4: { important: false, urgent: false },
  }

  let data = $state<TodayData | null>(null)
  let projectMap = $state<Record<string, string>>({})
  let error = $state<string | null>(null)
  let dialog = $state<{ kind: 'task' | 'habit' | 'goal'; q?: Quadrant } | null>(null)
  let detailHabit = $state<Habit | null>(null)
  let editingIds = $state<Set<string>>(new Set())
  let overQ = $state<Quadrant | null>(null)
  // The viewed day, shared with Flow via the strip. Habits/streaks/weekly report are
  // computed for it; the quadrant board itself is the one global backlog.
  const date = $derived(appState.plannerDate)
  const label = $derived(dayLabel(date))

  function load() {
    appState.plannerVersion // reload after a transmute action
    planner.today(date).then((d) => (data = d)).catch((e) => (error = String(e)))
  }
  $effect(load)
  // Live updates; pause while a dialog or the habit calendar is open so it can't clobber.
  liveRefresh(load, { enabled: () => dialog === null && detailHabit === null })

  $effect(() => {
    api.graph().then((g) => {
      const m: Record<string, string> = {}
      for (const n of g.nodes) if (n.type === 'project') m[n.id] = n.title
      projectMap = m
    }).catch(() => {})
  })

  function fmtDateline(): string {
    return new Date(`${date}T00:00:00`).toLocaleDateString(undefined, { weekday: 'long', month: 'short', day: 'numeric' }).toUpperCase()
  }

  function setEditing(id: string, on: boolean) {
    const next = new Set(editingIds)
    on ? next.add(id) : next.delete(id)
    editingIds = next
  }

  // Drag a task into a quadrant -> write that quadrant's important/urgent flags.
  function moveTask(taskId: string, q: Quadrant) {
    const all = data ? Object.values(data.quadrants).flat() : []
    const t = all.find((x) => x.id === taskId)
    if (t && t.quadrant === q) return
    const f = Q_FLAGS[q]
    if (data && t) {
      const next: Record<Quadrant, Task[]> = { Q1: [], Q2: [], Q3: [], Q4: [] }
      for (const qq of QUADRANT_ORDER) next[qq] = data.quadrants[qq].filter((x) => x.id !== taskId)
      next[q] = [{ ...t, quadrant: q, important: f.important ? 1 : 0, urgent_manual: f.urgent ? 1 : 0 }, ...next[q]]
      data = { ...data, quadrants: next }
    }
    planner.modifyTask(taskId, { important: f.important, urgent_manual: f.urgent }).then(load).catch(() => load())
  }

  async function completeTask(id: string) {
    await planner.completeTask(id, true)
    load()
  }
  async function removeTask(title: string, id: string) {
    if (!confirm(`Delete "${title}"? This cannot be undone.`)) return
    await planner.deleteTask(id)
    load()
  }
  async function renameTask(id: string, title: string) {
    await planner.modifyTask(id, { title })
    load()
  }

  async function toggleHabit(id: string) {
    await planner.toggleHabit(id, date)
    load()
  }
  async function removeHabit(name: string, id: string) {
    if (!confirm(`Delete ritual "${name}"? Its streak history goes with it.`)) return
    await planner.deleteHabit(id)
    load()
  }

  async function removeGoal(id: string, title: string) {
    if (!confirm(`Delete goal "${title}"? Its tasks stay but are unlinked.`)) return
    await planner.deleteGoal(id)
    load()
  }
  async function renameGoal(id: string, title: string) {
    await planner.modifyGoal(id, { title })
    load()
  }

  const goalDefaults: Record<Quadrant, { important: boolean; urgent: boolean }> = Q_FLAGS
  const allGoals = $derived(data ? data.goals.flatMap((g) => g.goals) : [])
</script>

{#snippet habitPill(h: Habit)}
  {@const daily = h.cadence_type === 'daily'}
  {@const done = daily ? h.progress?.done_today : h.progress?.met}
  {@const count = h.progress?.count ?? 0}
  {@const target = h.progress?.target ?? h.weekly_target ?? 1}
  {@const streak = h.streak?.current ?? 0}
  <div class="flex-shrink-0 flex items-center gap-2 pl-3 pr-2 py-2 rounded-full grimoire-card hover:border-rune-quest/50 transition-colors snap-start group">
    <button onclick={() => toggleHabit(h.id)} class="flex items-center gap-2 shrink-0" aria-label={`Toggle ${h.name}`}>
      {#if daily}
        <span class="w-5 h-5 rounded-full border flex items-center justify-center {done ? 'border-rune-quest bg-rune-quest/20 shadow-[0_0_10px_rgba(212,169,63,0.4)]' : 'border-border-default'}">
          {#if done}<span class="w-2.5 h-2.5 rounded-full bg-rune-quest"></span>{/if}
        </span>
      {:else}
        <span class="relative w-5 h-5 flex items-center justify-center">
          <svg class="w-full h-full -rotate-90" viewBox="0 0 24 24">
            <circle cx="12" cy="12" r="10" fill="none" stroke="#35333e" stroke-width="2" />
            <circle cx="12" cy="12" r="10" fill="none" stroke={done ? '#d4a93f' : '#5b8dd9'} stroke-width="2"
              stroke-dasharray={62.8} stroke-dashoffset={62.8 * (1 - Math.min(count / target, 1))} stroke-linecap="round" />
          </svg>
          <span class="absolute font-label-md text-[8px] text-on-surface-variant">{count}</span>
        </span>
      {/if}
    </button>
    <button
      ondblclick={() => (detailHabit = h)}
      onkeydown={(e) => e.key === 'Enter' && (detailHabit = h)}
      title="Double-click for the completion calendar"
      class="font-body-md text-body-md text-left hover:text-primary transition-colors {done ? 'text-on-surface' : 'text-on-surface-variant'}"
    >{h.name}</button>
    {#if streak > 0}
      <span class="flex items-center text-secondary ml-0.5 shrink-0">
        <span class="material-symbols-outlined text-[14px]" style="font-variation-settings:'FILL' 1">local_fire_department</span>
        <span class="font-label-md text-[10px]">{streak}</span>
      </span>
    {/if}
    <button onclick={() => removeHabit(h.name, h.id)}
      class="material-symbols-outlined text-[15px] text-text-tertiary opacity-0 group-hover:opacity-100 hover:text-status-error transition-all shrink-0"
      aria-label={`Delete ${h.name}`}>close</button>
  </div>
{/snippet}

{#snippet taskChip(t: Task, accent: string, questLine: string | undefined)}
  {@const overdue = t.due && new Date(t.due) <= new Date()}
  <div class="flex items-start gap-3 p-3 rounded bg-surface-container-low/50 border border-border-subtle hover:border-[color:var(--accent)] transition-colors group"
    style="--accent:{`${accent}80`}">
    <button onclick={() => completeTask(t.id)}
      class="mt-0.5 w-4 h-4 rounded-sm border border-border-default flex-shrink-0 hover:bg-[color:var(--accent)] transition-colors"
      aria-label="Complete task"></button>
    <div class="flex-1 min-w-0">
      <InlineEdit value={t.title} onSave={(title) => renameTask(t.id, title)}
        onEditingChange={(on) => setEditing(t.id, on)}
        textClassName="font-body-md text-body-md text-on-surface leading-tight"
        inputClassName="w-full bg-surface-container-low border border-rune-entity/60 rounded px-1.5 py-0.5 text-on-surface font-body-md text-body-md focus:outline-none" />
      <div class="flex items-center gap-3 mt-1 flex-wrap">
        {#if t.area_name}
          <span class="font-label-md text-[9px] uppercase px-1.5 py-0.5 rounded border"
            style="color:{t.area_color ?? accent}; border-color:{`${t.area_color ?? accent}4d`}; background:{`${t.area_color ?? accent}0d`}">
            {t.area_name}
          </span>
        {/if}
        {#if t.goal_title}
          <span class="font-label-md text-[9px] uppercase text-text-tertiary flex items-center gap-0.5">
            <span class="material-symbols-outlined text-[11px]">flag</span>{t.goal_title}
          </span>
        {/if}
        {#if questLine}
          <a href={`#/project/${encodeURIComponent(questLine)}`} onclick={(e) => e.stopPropagation()}
            class="font-label-md text-[9px] uppercase text-rune-quest hover:underline flex items-center gap-0.5">
            <span class="material-symbols-outlined text-[11px]">account_tree</span>{questLine}
          </a>
        {/if}
        {#if t.estimate_minutes}
          <span class="font-label-md text-[10px] text-text-tertiary flex items-center gap-1">
            <span class="material-symbols-outlined text-[12px]">schedule</span>{t.estimate_minutes}m
          </span>
        {/if}
        {#if overdue}
          <span class="font-label-md text-[10px] text-status-error flex items-center gap-1">
            <span class="material-symbols-outlined text-[12px]">warning</span>DUE
          </span>
        {/if}
      </div>
    </div>
    <button onclick={() => removeTask(t.title, t.id)}
      class="material-symbols-outlined text-[16px] text-text-tertiary opacity-0 group-hover:opacity-100 hover:text-status-error transition-all self-start"
      aria-label="Delete task">delete</button>
  </div>
{/snippet}

{#snippet goalRow(group: AreaGroup)}
  {#each group.goals as g (g.id)}
    {@const total = (g.open_tasks ?? 0) + (g.done_tasks ?? 0)}
    {@const pct = total > 0 ? Math.round((100 * (g.done_tasks ?? 0)) / total) : 0}
    {@const color = g.area_color ?? group.color ?? '#d4a93f'}
    <div animate:flip={{ duration: dur(300) }} transition:fade={{ duration: dur(160) }}
      class="grimoire-card px-5 py-3 rounded-lg flex items-center gap-4 group">
      <span class="w-2 h-2 rounded-full flex-shrink-0" style="background:{color}; box-shadow:0 0 8px {`${color}99`}"></span>
      <div class="flex-1 min-w-0">
        <div class="flex justify-between items-baseline mb-1.5 gap-3">
          <InlineEdit value={g.title} onSave={(t) => renameGoal(g.id, t)} textClassName="font-body-md text-body-md text-on-surface" />
          <span class="font-label-md text-[10px] text-text-tertiary uppercase shrink-0">
            {g.target_date ? new Date(g.target_date).toLocaleDateString(undefined, { month: 'short', day: 'numeric' }) : 'no date'}
          </span>
        </div>
        <div class="w-full h-1 bg-surface-container-highest rounded-full overflow-hidden">
          <div class="h-full rounded-full transition-[width] duration-500" style="width:{pct}%; background:{color}"></div>
        </div>
      </div>
      <button onclick={() => removeGoal(g.id, g.title)}
        class="material-symbols-outlined text-[16px] text-text-tertiary opacity-0 group-hover:opacity-100 hover:text-status-error transition-all"
        aria-label="Delete goal">delete</button>
    </div>
  {/each}
{/snippet}

{#if error}
  <div class="min-h-screen flex items-center justify-center text-center px-6">
    <div>
      <p class="font-headline-sm text-headline-sm text-status-error">Could not reach the planner</p>
      <p class="font-body-sm text-body-sm text-text-tertiary mt-2">{error}. Is the API running on :8731?</p>
    </div>
  </div>
{:else if !data}
  <div class="min-h-screen flex items-center justify-center"><p class="font-headline-md text-headline-md text-text-tertiary animate-pulse">Consulting the grimoire...</p></div>
{:else}
  <main class="min-h-screen pb-24 flex flex-col items-center overflow-y-auto">
    <div class="w-full max-w-5xl px-8 md:px-14 py-md">
      <div class="mb-md"><DayStrip /></div>
      <header class="pb-md flex justify-between items-center">
        <div>
          <h1 class="font-headline-lg text-headline-lg text-rune-quest tracking-widest mb-0.5 capitalize">{label}</h1>
          <p class="font-label-md text-label-md text-text-muted uppercase tracking-[0.2em]">{fmtDateline()}</p>
        </div>
        <div class="relative w-10 h-10 flex items-center justify-center text-primary opacity-70 overflow-hidden">
          <span class="material-symbols-outlined text-[24px] sigil-spin">auto_awesome</span>
          <div class="absolute inset-0 bg-primary/15 blur-xl rounded-full"></div>
        </div>
      </header>

      <div class="flex flex-col gap-lg">
        <!-- habits strip -->
        <section class="flex flex-col gap-3">
          <div class="flex justify-between items-center px-1">
            <h3 class="font-label-md text-label-md text-text-muted tracking-widest uppercase">Rituals &amp; goals</h3>
            <div class="flex items-center gap-3">
              <span class="font-label-md text-label-md text-rune-quest/80">THIS WEEK · {data.weekly.overall_percent}%</span>
              <button onclick={() => (dialog = { kind: 'habit' })} class="material-symbols-outlined text-[18px] text-text-tertiary hover:text-on-surface" aria-label="Add ritual">add</button>
            </div>
          </div>
          <div class="flex gap-3 overflow-x-auto pb-2 pt-1 snap-x">
            {#if data.habits.length === 0}<p class="font-body-md text-body-sm text-text-tertiary py-2">No rituals yet. Add one to begin a streak.</p>{/if}
            {#each data.habits as h (h.id)}
              <div animate:flip={{ duration: dur(300) }} in:scale={{ start: 0.9, duration: dur(200) }}>
                {@render habitPill(h)}
              </div>
            {/each}
          </div>
        </section>

        <!-- eisenhower matrix -->
        <section class="grid grid-cols-1 md:grid-cols-2 gap-px bg-border-subtle rounded-xl overflow-hidden border border-border-subtle">
          {#each QUADRANT_ORDER as q (q)}
            {@const meta = QUADRANT[q]}
            {@const tasks = data.quadrants[q] ?? []}
            <!-- svelte-ignore a11y_no_static_element_interactions -->
            <div
              role="list"
              ondragover={(e) => { e.preventDefault(); if (e.dataTransfer) e.dataTransfer.dropEffect = 'move'; overQ = q }}
              ondragleave={(e) => { if (!e.currentTarget.contains(e.relatedTarget as Node)) overQ = null }}
              ondrop={(e) => { e.preventDefault(); overQ = null; const id = e.dataTransfer?.getData('text/plain'); if (id) moveTask(id, q) }}
              class="grimoire-card border-none rounded-none p-4 flex flex-col gap-2.5 relative min-h-[180px] max-h-[40vh] min-w-0 transition-shadow"
              style="box-shadow:{overQ === q ? `inset 0 0 0 2px ${meta.color}, 0 0 28px ${meta.glow}` : 'none'}"
            >
              {#if overQ === q}
                <div class="absolute inset-0 z-0 flex items-center justify-center pointer-events-none" style="background:{`${meta.color}0f`}" transition:fade={{ duration: dur(120) }}>
                  <span class="font-headline-md text-headline-md" style="color:{meta.color}">Drop into {meta.label}</span>
                </div>
              {/if}
              <div class="flex justify-between items-start relative z-10">
                <h3 class="font-headline-sm text-headline-sm flex items-center gap-2" style="color:{meta.color}">
                  <span class="material-symbols-outlined text-[18px]">{meta.icon}</span>{meta.label}
                </h3>
                <div class="flex items-center gap-2">
                  <button onclick={() => (dialog = { kind: 'task', q })} class="material-symbols-outlined text-[18px] text-text-tertiary hover:text-on-surface transition-colors" aria-label="Add task">add</button>
                  <span class="font-label-md text-label-md text-text-tertiary bg-surface-container-high px-2 py-1 rounded">{q}</span>
                </div>
              </div>
              <div class="flex flex-col gap-2 overflow-y-auto relative z-10 flex-1 min-h-0 pr-1">
                {#if tasks.length === 0}
                  <div class="flex-1 flex flex-col items-center justify-center text-center py-4">
                    <span class="material-symbols-outlined text-[20px] text-border-default mb-1">inbox</span>
                    <p class="font-body-md text-body-sm text-text-tertiary">{q === 'Q4' ? 'The void is empty. Keep it that way.' : 'Nothing here.'}</p>
                  </div>
                {:else}
                  {#each tasks as t (t.id)}
                    <div
                      draggable={!editingIds.has(t.id)}
                      ondragstart={(e) => { e.dataTransfer?.setData('text/plain', t.id); if (e.dataTransfer) e.dataTransfer.effectAllowed = 'move' }}
                      class="cursor-grab active:cursor-grabbing"
                      animate:flip={{ duration: dur(320) }}
                      in:taskReceive={{ key: t.id }}
                      out:taskSend={{ key: t.id }}
                    >
                      {@render taskChip(t, meta.color, t.project_id ? projectMap[t.project_id] : undefined)}
                    </div>
                  {/each}
                {/if}
              </div>
            </div>
          {/each}
        </section>

        <p class="font-body-md text-body-sm text-text-muted px-1 -mt-2">
          {data.estimate.label}
          <span class="text-text-tertiary"> · drag a task between quadrants to re-prioritize</span>
        </p>

        <!-- goals rail -->
        <section class="flex flex-col gap-3">
          <div class="flex justify-between items-center px-1">
            <h3 class="font-label-md text-label-md text-text-muted tracking-widest uppercase">Active vectors</h3>
            <button onclick={() => (dialog = { kind: 'goal' })} class="material-symbols-outlined text-[18px] text-text-tertiary hover:text-on-surface" aria-label="Add goal">add</button>
          </div>
          <div class="flex flex-col gap-2">
            {#if allGoals.length === 0}<p class="font-body-md text-body-sm text-text-tertiary">No goals yet. Set a vector to give the day direction.</p>{/if}
            {#each data.goals as group (group.id ?? 'unsorted')}
              {@render goalRow(group)}
            {/each}
          </div>
        </section>
      </div>
    </div>

    {#if dialog}
      <AddItemDialog kind={dialog.kind} defaultQuadrant={dialog.q ? goalDefaults[dialog.q] : undefined}
        onClose={() => (dialog = null)} onCreated={load} />
    {/if}

    {#if detailHabit}
      <HabitDetail habit={detailHabit} onClose={() => (detailHabit = null)} onChanged={load} />
    {/if}
  </main>
{/if}
