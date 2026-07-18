<script lang="ts">
  import { fade } from 'svelte/transition'
  import type { Block, FlowData } from '../../lib/api'
  import { dur } from '../../lib/motion.svelte'

  // Compact scale: a 15h day reads in ~600px, glanceable without scrolling. Blocks
  // show the title; click one for details (rename/remove live in the modal).
  const PX_PER_MIN = 0.65

  const BLOCK_STYLE: Record<Block['type'], { color: string; label: string }> = {
    anchor: { color: '#5b8dd9', label: 'Anchor' },
    habit: { color: '#d4a93f', label: 'Ritual' },
    task: { color: '#cdc6b7', label: 'Task' },
    goal: { color: '#d98b4a', label: 'Apex goal' },
    break: { color: '#9d6bd9', label: 'Break' },
  }

  let {
    blocks,
    windowStart,
    windowEnd,
    overlay,
    onMove,
    onOpen,
    onInteractingChange,
    onCreateAt,
  }: {
    blocks: Block[]
    windowStart: Date
    windowEnd: Date
    overlay: FlowData['overlay']
    onMove: (index: number, newStartISO: string) => void
    // Click a block (without dragging) to open its detail modal in the parent.
    onOpen?: (index: number) => void
    onInteractingChange?: (interacting: boolean) => void
    // Double-click an empty slot to create a task pinned to that time (Google-Calendar
    // style). Passes the snapped start ISO; the parent opens the create modal.
    onCreateAt?: (startISO: string) => void
  } = $props()

  let containerEl = $state<HTMLDivElement>()
  let drag = $state<{ i: number; topPx: number } | null>(null)
  // Cursor position (px from top) over empty timeline, for the "add here" affordance.
  let hoverPx = $state<number | null>(null)

  $effect(() => onInteractingChange?.(drag !== null))

  const lo = $derived(windowStart.getTime())
  const hi = $derived(windowEnd.getTime())
  const totalMin = $derived(Math.max(60, (hi - lo) / 60000))
  const height = $derived(totalMin * PX_PER_MIN)

  const topPxOf = (ms: number) => ((ms - lo) / 60000) * PX_PER_MIN
  const durMin = (b: { start: string; end: string }) => (new Date(b.end).getTime() - new Date(b.start).getTime()) / 60000
  const clock = (iso: string) => new Date(iso).toLocaleTimeString(undefined, { hour: '2-digit', minute: '2-digit' })

  const hours = $derived.by(() => {
    const out: Date[] = []
    const first = new Date(lo)
    first.setMinutes(0, 0, 0)
    if (first.getTime() < lo) first.setHours(first.getHours() + 1)
    for (let t = new Date(first); t.getTime() <= hi; t.setHours(t.getHours() + 1)) out.push(new Date(t))
    return out
  })

  const now = new Date()

  function startDrag(e: MouseEvent, i: number) {
    if ((e.target as HTMLElement).closest('button,input')) return
    const rect = containerEl!.getBoundingClientRect()
    const blockTop = topPxOf(new Date(blocks[i].start).getTime())
    const grab = e.clientY - rect.top - blockTop
    const downY = e.clientY
    let moved = false
    drag = { i, topPx: blockTop }

    const move = (ev: MouseEvent) => {
      if (Math.abs(ev.clientY - downY) > 4) moved = true
      const blockPx = durMin(blocks[i]) * PX_PER_MIN
      let topPx = ev.clientY - rect.top - grab
      topPx = Math.max(0, Math.min(topPx, height - blockPx))
      drag = { i, topPx }
    }
    const up = () => {
      if (drag && moved) {
        const snapped = Math.round(drag.topPx / PX_PER_MIN / 5) * 5
        onMove(drag.i, new Date(lo + snapped * 60000).toISOString())
      } else if (!moved) {
        onOpen?.(i) // a plain click opens the detail modal
      }
      drag = null
      window.removeEventListener('mousemove', move)
      window.removeEventListener('mouseup', up)
    }
    window.addEventListener('mousemove', move)
    window.addEventListener('mouseup', up)
  }

  // --- create-at-slot (Google-Calendar-style) ---------------------------------
  const SNAP_MIN = 15
  const snappedMin = (px: number) => Math.max(0, Math.round(px / PX_PER_MIN / SNAP_MIN) * SNAP_MIN)

  // Track the cursor over empty timeline to show the "double-click to add" ghost.
  function onBackgroundMove(e: MouseEvent) {
    if (drag !== null || (e.target as HTMLElement).closest('[data-block]')) {
      hoverPx = null
      return
    }
    if (containerEl) hoverPx = e.clientY - containerEl.getBoundingClientRect().top
  }
  // Double-click empty space -> create a task pinned to that (snapped) time.
  function createAtCursor(e: MouseEvent) {
    if (!onCreateAt || !containerEl || (e.target as HTMLElement).closest('[data-block]')) return
    onCreateAt(new Date(lo + snappedMin(e.clientY - containerEl.getBoundingClientRect().top) * 60000).toISOString())
  }
</script>

<!-- svelte-ignore a11y_no_static_element_interactions -->
<div bind:this={containerEl} class="relative ml-14 select-none" style="height:{height}px"
  onmousemove={onBackgroundMove} onmouseleave={() => (hoverPx = null)} ondblclick={createAtCursor}>
  <!-- hour gridlines -->
  {#each hours as h, i (i)}
    <div class="absolute left-0 right-0 flex items-center" style="top:{topPxOf(h.getTime())}px">
      <span class="absolute -left-14 -translate-y-1/2 font-label-md text-[10px] text-text-tertiary tabular-nums">
        {h.toLocaleTimeString(undefined, { hour: '2-digit', minute: '2-digit' })}
      </span>
      <div class="w-full border-t border-border-subtle/60"></div>
    </div>
  {/each}

  <!-- IF eating window band -->
  {#if overlay}
    <div class="absolute left-0 right-0 rounded bg-rune-chronicle/5 border-y border-rune-chronicle/20 pointer-events-none"
      style="top:{topPxOf(new Date(overlay.eating_start).getTime())}px; height:{Math.max(0, durMin({ start: overlay.eating_start, end: overlay.eating_end })) * PX_PER_MIN}px">
      <span class="absolute top-1 right-2 font-label-md text-[9px] uppercase tracking-widest text-rune-chronicle/70 flex items-center gap-1">
        <span class="material-symbols-outlined text-[12px]">restaurant</span>eating window
      </span>
    </div>
  {/if}

  <!-- blocks -->
  {#each blocks as b, i (i)}
    {@const dragging = drag?.i === i}
    {@const top = dragging ? drag!.topPx : topPxOf(new Date(b.start).getTime())}
    {@const h = Math.max(18, durMin(b) * PX_PER_MIN)}
    {@const s = BLOCK_STYLE[b.type]}
    {@const apex = b.goal_block}
    {@const startLabel = clock(new Date(lo + (top / PX_PER_MIN) * 60000).toISOString())}
    <!-- svelte-ignore a11y_no_static_element_interactions -->
    <div
      data-block
      onmousedown={(e) => startDrag(e, i)}
      in:fade={{ duration: dur(180) }}
      class="absolute left-2 right-2 rounded-md px-2.5 overflow-hidden flex items-center gap-2 {apex ? 'border-2' : 'border'} {dragging ? 'cursor-grabbing z-30 shadow-2xl' : 'cursor-pointer transition-all hover:brightness-125'} {b.locked ? 'opacity-80' : ''}"
      style="top:{top}px; height:{h}px; border-color:{apex ? s.color : `${s.color}55`}; background:{apex ? `${s.color}1f` : 'rgba(22,20,43,0.92)'}; box-shadow:{dragging ? `0 8px 30px rgba(0,0,0,0.6), 0 0 0 1px ${s.color}` : apex ? `0 0 18px ${s.color}30` : 'inset 0 1px 0 rgba(255,255,255,0.05)'}"
      title="{b.title} · click for details, drag to move"
    >
      <span class="w-1.5 h-1.5 rounded-full shrink-0" style="background:{s.color}"></span>
      <span class="flex-1 min-w-0 truncate {apex ? 'font-headline-sm text-headline-sm' : 'font-body-sm text-body-sm'} text-on-surface leading-none">
        {#if apex}★ {/if}{b.title}
      </span>
      {#if b.locked}<span class="material-symbols-outlined text-[11px] text-text-tertiary shrink-0">lock</span>{/if}
      <span class="font-label-md text-[10px] text-text-tertiary tabular-nums shrink-0">{startLabel}</span>
    </div>
  {/each}

  <!-- create-at-slot ghost: shows the snapped time on hover over empty timeline -->
  {#if hoverPx !== null && onCreateAt}
    {@const gm = snappedMin(hoverPx)}
    <div class="absolute left-2 right-2 z-10 pointer-events-none flex items-center gap-2 rounded-md border border-dashed border-rune-quest/50 bg-rune-quest/5 px-3"
      style="top:{gm * PX_PER_MIN}px; height:{Math.max(20, 30 * PX_PER_MIN)}px">
      <span class="material-symbols-outlined text-[15px] text-rune-quest">add</span>
      <span class="font-label-md text-[10px] uppercase tracking-widest text-rune-quest">
        double-click to add · {clock(new Date(lo + gm * 60000).toISOString())}
      </span>
    </div>
  {/if}

  <!-- current-time marker -->
  {#if now.getTime() >= lo && now.getTime() <= hi}
    <div class="absolute left-0 right-0 z-20 pointer-events-none" style="top:{topPxOf(now.getTime())}px">
      <div class="flex items-center">
        <span class="absolute -left-14 -translate-y-1/2 font-label-md text-[10px] text-rune-entity font-bold">{clock(now.toISOString())}</span>
        <div class="w-full border-t-2 border-rune-entity/70"></div>
        <div class="absolute left-0 w-2 h-2 rounded-full bg-rune-entity -translate-y-1/2 shadow-[0_0_8px_rgba(157,107,217,0.8)]"></div>
      </div>
    </div>
  {/if}
</div>
