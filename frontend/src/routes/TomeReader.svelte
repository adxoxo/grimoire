<script lang="ts">
  import { marked } from 'marked'
  import { api, type Document } from '../lib/api'
  import { link } from '../lib/router.svelte'

  let { id }: { id: string } = $props()

  let doc = $state<Document | null>(null)
  let error = $state<string | null>(null)

  $effect(() => {
    const wanted = id
    doc = null
    error = null
    api.document(wanted).then((d) => (doc = d)).catch((e) => (error = String(e)))
  })

  // Content is the user's own local markdown (trusted), rendered synchronously.
  const html = $derived(doc ? (marked.parse(doc.content, { async: false }) as string) : '')
</script>

<div class="min-h-screen overflow-y-auto px-margin py-lg">
  <a href={link('/')} class="font-label-md text-label-md text-text-muted hover:text-primary uppercase tracking-widest inline-flex items-center gap-1">
    <span class="material-symbols-outlined text-[16px]">arrow_back</span> Constellation
  </a>

  {#if error}
    <p class="font-body-sm text-body-sm text-status-error mt-8">{error}</p>
  {:else if !doc}
    <p class="font-headline-md text-headline-md text-text-tertiary animate-pulse mt-8">Unsealing the tome...</p>
  {:else}
    <article class="mt-6 mx-auto max-w-[800px]">
      <header class="mb-lg flex items-center gap-3 border-b border-border-subtle pb-6">
        <span class="material-symbols-outlined text-rune-tome text-[32px]" style="filter:drop-shadow(0 0 8px #5b8dd9)">menu_book</span>
        <div>
          <span class="font-label-md text-label-md text-rune-tome uppercase tracking-widest">Tome</span>
          <h1 class="font-headline-lg text-headline-lg text-primary leading-none">{doc.title}</h1>
        </div>
      </header>
      <!-- Content stays clean and plainly readable: Spectral, not stylised into illegibility -->
      <div class="tome-content bg-bg-panel border border-border-default rounded-lg border-t-2 border-t-rune-tome p-8">
        <!-- eslint-disable-next-line svelte/no-at-html-tags -->
        {@html html}
      </div>
    </article>
  {/if}
</div>
