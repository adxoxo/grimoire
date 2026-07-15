<script lang="ts">
  // Stand-in for views not yet ported in this vertical slice. Keeps the nav fully
  // walkable so the shell + Home can be judged in context, and states plainly what is
  // coming rather than 404-ing.
  import { link } from '../lib/router.svelte'

  let { title, eyebrow }: { title: string; eyebrow?: string } = $props()
</script>

<div class="min-h-screen flex flex-col items-center justify-center text-center px-6">
  <span class="material-symbols-outlined text-[40px] text-border-default mb-3">architecture</span>
  {#if eyebrow}
    <p class="font-label-md text-label-md text-text-tertiary uppercase tracking-widest mb-1">{eyebrow}</p>
  {/if}
  <h1 class="font-headline-lg text-headline-lg text-primary">{title}</h1>
  <p class="font-body-md text-body-md text-text-muted mt-3 max-w-sm">
    This chamber is being re-inscribed in the next pass. The constellation is ready — wander it from the
    <a href={link('/')} class="text-primary-container hover:underline">home view</a>.
  </p>
</div>
