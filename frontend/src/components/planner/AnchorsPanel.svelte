<script lang="ts">
  import { slide } from 'svelte/transition'
  import { planner, type Anchor } from '../../lib/api'
  import { dur } from '../../lib/motion.svelte'

  let { date, anchors, onChange }: { date: string; anchors: Anchor[]; onChange: () => void } = $props()

  let open = $state(false)
  let title = $state('')
  let kind = $state<'hard' | 'soft'>('hard')
  let time = $state('14:00')
  let winStart = $state('12:00')
  let winEnd = $state('14:00')
  let durationMin = $state('60')

  function combine(d: string, hhmm: string): Date {
    const [h, m] = hhmm.split(':').map(Number)
    const dt = new Date(`${d}T00:00:00`)
    dt.setHours(h, m, 0, 0)
    return dt
  }
  const clock = (iso: string) => new Date(iso).toLocaleTimeString(undefined, { hour: '2-digit', minute: '2-digit' })

  async function add() {
    if (!title.trim()) return
    await planner.createAnchor({
      title: title.trim(), date, kind, duration_minutes: Number(durationMin) || 30,
      start: kind === 'hard' ? combine(date, time).toISOString() : undefined,
      window_start: kind === 'soft' ? winStart : undefined,
      window_end: kind === 'soft' ? winEnd : undefined,
    })
    title = ''
    open = false
    onChange()
  }

  const field = 'bg-surface-container-low border border-border-default rounded px-2 py-1.5 text-on-surface font-body-sm text-body-sm focus:outline-none focus:border-rune-tome/60'
</script>

<div>
  <div class="flex justify-between items-center mb-2">
    <h4 class="font-label-md text-label-md text-text-muted uppercase tracking-widest">Anchors</h4>
    <button onclick={() => (open = !open)} class="material-symbols-outlined text-[18px] text-text-tertiary hover:text-on-surface" aria-label={open ? 'Close' : 'Add anchor'}>{open ? 'close' : 'add'}</button>
  </div>
  <div class="space-y-1.5">
    {#if anchors.length === 0 && !open}<p class="font-body-sm text-body-sm text-text-tertiary">No anchors. Pin a call or window the day.</p>{/if}
    {#each anchors as a (a.id)}
      <div transition:slide={{ duration: dur(200) }} class="flex items-center gap-2 bg-surface-container-low/50 border border-border-subtle rounded px-2 py-1.5">
        <span class="w-1.5 h-1.5 rounded-full shrink-0" style="background:{a.kind === 'hard' ? '#4fb6c9' : '#9d6bd9'}"></span>
        <span class="font-body-sm text-body-sm text-on-surface flex-1 truncate">{a.title}</span>
        <span class="font-label-md text-[9px] text-text-tertiary">{a.kind === 'hard' && a.start ? clock(a.start) : `${a.window_start ?? ''}–${a.window_end ?? ''}`}</span>
        <button onclick={async () => { await planner.deleteAnchor(a.id); onChange() }} class="material-symbols-outlined text-[14px] text-text-tertiary hover:text-status-error" aria-label="Delete anchor">close</button>
      </div>
    {/each}
  </div>
  {#if open}
    <div transition:slide={{ duration: dur(200) }} class="mt-2 space-y-2 bg-surface-container-low/40 border border-border-subtle rounded p-2">
      <input bind:value={title} placeholder="anchor title" class="{field} w-full" />
      <div class="flex gap-2">
        <select bind:value={kind} class="{field} flex-1">
          <option value="hard">Hard (pinned)</option>
          <option value="soft">Soft (window)</option>
        </select>
        <input bind:value={durationMin} type="number" class="{field} w-20" placeholder="min" />
      </div>
      {#if kind === 'hard'}
        <input bind:value={time} type="time" class="{field} w-full" />
      {:else}
        <div class="flex gap-2 items-center">
          <input bind:value={winStart} type="time" class="{field} flex-1" />
          <span class="text-text-tertiary">–</span>
          <input bind:value={winEnd} type="time" class="{field} flex-1" />
        </div>
      {/if}
      <button onclick={add} class="w-full py-1.5 bg-surface text-rune-tome border border-rune-tome/50 rounded hover:bg-rune-tome/10 font-label-md text-label-md uppercase tracking-wider">Add anchor</button>
    </div>
  {/if}
</div>
